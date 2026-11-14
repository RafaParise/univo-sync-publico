#!/usr/bin/env python3
"""
provisionar_rede.py
Configura o FortiGate 60D (FortiOS 5.4) pela REDE, via API REST, a partir da porta 1.
Caminho principal; o provisionar_fortigate.py (console serial) fica como plano B.

  python scripts/provisionar_rede.py              mostra os passos, não muda nada (nem conecta)
  python scripts/provisionar_rede.py --mostrar-cli  idem, e mostra o bloco de CLI (VIPs e regras) do restore
  python scripts/provisionar_rede.py --conferir   entra no FortiGate e SÓ LÊ: diz o que o --aplicar mudaria
  python scripts/provisionar_rede.py --aplicar    aplica (pode repetir: cada passo sobrescreve)
  --uplink wan1|internal3  porta que vai à internet (padrão: FORTIGATE_UPLINK do .env, senão wan1)

Desenho (docs/decisoes-provisionamento.md e docs/TOPOLOGIA-2026-11-12.md):
  wan1                            = UPLINK: internet pela ONT Huawei (DHCP da rede 192.168.18.0/24; 192.168.18.40
                                    desde 12/11/2026, ~18h50)
  internal (switch: portas 1,3-7) = LAN1 10.0.20.0/24  PC Ryzen na porta 1 -> 10.0.20.100
  internal2 (porta 2)             = LAN2 10.0.30.0/24  switch da ARENA
  dmz                             = 10.0.10.0/24       Galaxy A12 -> 10.0.10.50
Opção B (--uplink internal3, só se a WAN1 não puder ser usada): tira a porta 3 do switch e leva o uplink, as
regras e os VIPs para ela; a WAN1 fica com distância 15 e sem regra. Para desfazer, --uplink wan1 e devolver a
porta 3 à LAN1 à mão, depois do restore (passo D2 de docs/TOPOLOGIA-2026-11-12.md).
O último passo troca o IP da LAN1 (192.168.1.99 -> 10.0.20.1) e renova o IP deste PC.
"""
import argparse
import secrets
import subprocess
import sys
import time
from pathlib import Path

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA))
from fortigate_api import ErroAPI, FortiAPI  # noqa: E402
from provisionar_fortigate import ENV, LOGS, MAC, SENHA_OK, gravar_env, ler_env  # noqa: E402

IP_FABRICA, IP_LAN1 = "192.168.1.99", "10.0.20.1"
M24, M32 = "255.255.255.0", "255.255.255.255"
# Porta que leva à internet. Desde 12/11/2026 (~18h50) o cabo da ONT Huawei está na WAN1, o padrão. A opção B
# (internal3, a porta 3) continua disponível: de fábrica ela faz parte do switch "internal" (LAN1) e por isso o
# script a tira dele antes de virar uplink.
UPLINKS = ("wan1", "internal3")
UPLINK_PADRAO = "wan1"


def nomes(*n):
    return [{"name": x} for x in n]


def faixa(ini, fim):
    return [{"id": 1, "start-ip": ini, "end-ip": fim}]


def dhcp(id_, intf, rede, ini, fim, reservas=()):
    d = {"id": id_, "interface": intf, "default-gateway": f"{rede}.1", "netmask": M24,
         "dns-service": "local", "ip-range": faixa(f"{rede}.{ini}", f"{rede}.{fim}")}
    if reservas:
        d["reserved-address"] = [{"id": i + 1, "ip": ip, "mac": mac} for i, (ip, mac) in enumerate(reservas)]
    return d


def politica(pid, nome, src, dst, saddr, daddr, servicos, **extra):
    p = {"policyid": pid, "name": nome, "srcintf": nomes(src), "dstintf": nomes(dst),
         "srcaddr": nomes(saddr), "dstaddr": nomes(daddr), "action": "accept",
         "schedule": "always", "service": nomes(*servicos)}
    p.update(extra)
    return p


# ---------- passos (nome, opcional, função) ----------
def portas_fora_do_switch(uplink):
    """Portas que não podem ficar no switch de hardware "internal" (LAN1)."""
    return ["internal2"] + ([uplink] if uplink.startswith("internal") else [])


def montar_passos(env, uplink=UPLINK_PADRAO):
    mac_pc, mac_a12 = env["MAC_RYZEN"], env.get("MAC_A12", "")
    fora = portas_fora_do_switch(uplink)
    wans = [uplink] + [w for w in ("wan1", "wan2") if w != uplink]
    passos = []

    def passo(nome, opcional=False):
        def reg(f):
            passos.append((nome, opcional, f))
            return f
        return reg

    @passo("nome do aparelho")
    def _(api):
        api.ajustar("system/global", {"hostname": "FG60D-BANCADA"})

    @passo(f"separar {' e '.join(fora)} do switch da LAN1")
    def _(api):
        # A porta 1 (PC) continua no switch: separar as outras não derruba a sessão deste PC.
        portas = [p["name"] for p in api.ler("system/virtual-switch/internal")[0]["port"]]
        if any(p in portas for p in fora):
            api.ajustar("system/virtual-switch/internal",
                        {"port": nomes(*[p for p in portas if p not in fora])})

    @passo(f"interfaces {', '.join(wans)} (DHCP), internal2 e dmz")
    def _(api):
        # Só ping de fora: a ONT pode estar com DMZ apontando para o FortiGate, então nada de https/ssh no uplink.
        for w in wans:
            api.ajustar(f"system/interface/{w}", {"mode": "dhcp", "allowaccess": "ping", "defaultgw": "enable"})
        api.ajustar("system/interface/internal2", {"ip": f"10.0.30.1 {M24}", "allowaccess": "ping"})
        api.ajustar("system/interface/dmz", {"ip": f"10.0.10.1 {M24}", "allowaccess": "ping https"})

    @passo("DNS local nas três redes (bancada.lan)")
    def _(api):
        for i in ("internal", "internal2", "dmz"):
            api.gravar("system/dns-server", i, {"name": i, "mode": "recursive"})
        api.gravar("system/dns-database", "bancada", {
            "name": "bancada", "domain": "bancada.lan", "authoritative": "disable",
            "dns-entry": [{"id": n + 1, "type": "A", "hostname": h, "ip": ip} for n, (h, ip) in
                          enumerate((("fortigate", IP_LAN1), ("arena", "10.0.20.100"), ("a12", "10.0.10.50"),
                                     # Repasse do ARENA (11/11/2026): o A12 e o PC sao os dois hospedeiros.
                                     ("repasse", "10.0.10.50"), ("repasse-pc", "10.0.20.100")))]})

    @passo(f"descrições das interfaces e distâncias ({uplink} principal)", opcional=True)
    def _(api):
        desc_wan1 = ({"description": "WAN1 - internet principal", "distance": 10} if uplink == "wan1" else
                     {"description": "WAN1 - sem cabo (uplink na porta 3)", "distance": 15})
        lan1 = "1,3-7" if uplink == "wan1" else "1,4-7"
        extra = (((uplink, {"description": "UPLINK - ONT Huawei (porta 3)", "distance": 10}),)
                 if uplink != "wan1" else ())
        for intf, dados in extra + (("wan1", desc_wan1),
                                    ("wan2", {"description": "WAN2 - internet reserva", "distance": 20}),
                                    ("internal", {"description": f"LAN1 - PC Ryzen e bancada (portas {lan1})"}),
                            ("internal2", {"description": "LAN2 - controles ARENA (porta 2)"}),
                            ("dmz", {"description": "DMZ - Galaxy A12"})):
            api.ajustar(f"system/interface/{intf}", dados)

    @passo("DHCP da DMZ e da LAN2 (reservas do A12 e dos controles)")
    def _(api):
        # A DMZ recebe o A12 (.50) e, quando o Rafael o liga no hub da DMZ, o proprio PC (.60): os dois hospedam o
        # repasse do ARENA e trabalham juntos (11/11/2026). O PC continua com o .100 na LAN1 quando esta na porta 1.
        res_dmz = ([("10.0.10.50", mac_a12)] if mac_a12 else []) + [("10.0.10.60", mac_pc)]
        controles = [(ip, env[k]) for ip, k in (("10.0.30.10", "MAC_CONTROLE_1"), ("10.0.30.11", "MAC_CONTROLE_2"))
                     if env.get(k)]
        api.gravar("system.dhcp/server", 2, dhcp(2, "dmz", "10.0.10", 50, 60, res_dmz))
        api.gravar("system.dhcp/server", 3, dhcp(3, "internal2", "10.0.30", 10, 150, controles))

    @passo("objetos e serviços")
    def _(api):
        for n, sub in (("PC_RYZEN", f"10.0.20.100 {M32}"), ("A12_PARISE_CORE", f"10.0.10.50 {M32}"),
                       ("PC_RYZEN_DMZ", f"10.0.10.60 {M32}"),      # o PC no hub da DMZ (11/11/2026)
                       ("ARENA_CONTROLES", f"10.0.30.0 {M24}")):
            api.gravar("firewall/address", n, {"name": n, "subnet": sub})
        # Quem pode hospedar o repasse do ARENA: o A12 e o PC (na LAN1 ou na DMZ). As regras 7 e 10 usam o grupo.
        api.gravar("firewall/addrgrp", "REPASSE_ARENA_HOSPEDEIROS", {
            "name": "REPASSE_ARENA_HOSPEDEIROS", "member": nomes("A12_PARISE_CORE", "PC_RYZEN", "PC_RYZEN_DMZ")})
        for n, porta in (("ADB_5555", "5555"), ("ARENA_WEBSOCKET", "8780"),   # o celular como controle do ARENA (servidor/controle_remoto.py); era 8080 no plano, 10/11/2026
                         ("A12_SAUDE_API", "8000"), ("TERMUX_SSH", "8022"),
                         ("ARENA_REPASSE", "55440")):   # repasse do ARENA no A12 (partida entre casas, 10/11/2026)
            api.gravar("firewall.service/custom", n, {"name": n, "protocol": "TCP/UDP/SCTP", "tcp-portrange": porta})
        # Wake-on-LAN (13/11/2026): o "pacote magico" que o A12 manda para ligar o PC (scripts/ligar_pc.py).
        api.gravar("firewall.service/custom", "WOL_UDP9", {"name": "WOL_UDP9", "protocol": "TCP/UDP/SCTP",
                                                            "udp-portrange": "9"})

    @passo("ARP fixo do PC (Wake-on-LAN)", opcional=True)
    def _(api):
        # Com o PC desligado, o FortiGate esquece o endereco fisico dele e nao entrega o pacote magico do A12. A entrada
        # fixa vale ligado ou desligado (e' o mesmo endereco da placa), 13/11/2026.
        api.gravar("system/arp-table", 1, {"id": 1, "interface": "internal", "ip": "10.0.20.100", "mac": mac_pc})

    @passo("QoS (shapers)")
    def _(api):
        api.gravar("firewall.shaper/traffic-shaper", "ARENA_INPUT_SHAPER", {
            "name": "ARENA_INPUT_SHAPER", "guaranteed-bandwidth": 5000, "maximum-bandwidth": 10000, "priority": "high"})
        api.gravar("firewall.shaper/traffic-shaper", "OBS_UPLOAD_SHAPER", {
            "name": "OBS_UPLOAD_SHAPER", "maximum-bandwidth": 20000, "priority": "medium"})

    @passo("apagar a regra de fábrica (internal -> wan1, tudo)")
    def _(api):
        for p in api.ler("firewall/policy") or []:
            if not p.get("name"):
                api.apagar("firewall/policy", p["policyid"])

    @passo("bloquear *.samsung.net no DNS da DMZ", opcional=True)
    def _(api):
        api.gravar("dnsfilter/urlfilter", 1, {"id": 1, "name": "TELEMETRIA_SAMSUNG", "entries": [
            {"id": 1, "url": "*.samsung.net", "type": "wildcard", "action": "block"}]})
        # Campos do FortiOS 5.4 (13/11/2026): "urlfilter-table" (o "domain-filter" e' do 6.x e o 5.4 o ignorava: a
        # lista nunca ficou ligada). E "error-allow": sem licenca, a FortiGuard nao classifica nome nenhum, e sem
        # essa opcao TODO nome da DMZ ia para a pagina de bloqueio (208.91.112.55) -- o Android do A12 marcava o cabo
        # como "sem internet" e respondia ao PC pelo Wi-Fi.
        api.gravar("dnsfilter/profile", "BLOQUEIA_TELEMETRIA", {
            "name": "BLOQUEIA_TELEMETRIA", "urlfilter": {"urlfilter-table": 1},
            "ftgd-dns": {"options": "error-allow", "filters": []}, "block-botnet": "disable"})
        api.gravar("system/dns-server", "dmz", {"name": "dmz", "mode": "recursive",
                                                "dnsfilter-profile": "BLOQUEIA_TELEMETRIA"})

    @passo("syslog para o PC", opcional=True)
    def _(api):
        api.ajustar("log.syslogd/setting", {"status": "enable", "server": "10.0.20.100"})

    @passo("conta de API do A12 (só firewall, só a partir do A12)", opcional=True)
    def _(api):
        # A API do 5.4 não cria admin (403); vai pelo CLI via SSH.
        if env.get("FORTIGATE_API_SENHA") and api.existe("system/admin/parise_core_api"):
            return
        import fortios_console as fc
        senha = env.get("FORTIGATE_API_SENHA") or secrets.token_urlsafe(18)
        con = fc.Console(CanalSSH(api.host, "admin", env["ADMIN_SENHA"]), pausa=1.0)
        try:
            con.acordar(tentativas=10)
            for linha in ("config system accprofile", 'edit "parise_core_api"', "set fwgrp read-write", "next", "end",
                          "config system admin", 'edit "parise_core_api"', 'set accprofile "parise_core_api"',
                          'set vdom "root"', f'set password "{senha}"', f"set trusthost1 10.0.10.50 {M32}",
                          "next", "end"):
                con.comando(linha, confirmar=True)
        except (fc.FalhaFortiOS, fc.FalhaLogin) as e:
            raise ErroAPI(str(e).replace(senha, "****")[:300])
        finally:
            con.fechar()
        gravar_env(ENV, "FORTIGATE_API_USUARIO", "parise_core_api")
        gravar_env(ENV, "FORTIGATE_API_SENHA", senha)

    return passos


def montar_regras(uplink=UPLINK_PADRAO):
    """As 11 regras; a internet é a porta do uplink (wan1, o padrão; internal3 na opção B)."""
    u = uplink
    return [
        politica(1, "PC_PARA_INTERNET", "internal", u, "PC_RYZEN", "all", ["ALL"], nat="enable"),
        politica(2, "PC_PARA_A12_ADB", "internal", "dmz", "PC_RYZEN", "A12_PARISE_CORE", ["ADB_5555"], logtraffic="all"),
        politica(3, "PC_PARA_A12_GERENCIA", "internal", "dmz", "PC_RYZEN", "A12_PARISE_CORE",
                 ["A12_SAUDE_API", "TERMUX_SSH", "PING", "ARENA_REPASSE"]),
        politica(4, "ARENA_CONTROLES_PARA_PC", "internal2", "internal", "ARENA_CONTROLES", "PC_RYZEN",
                 ["ARENA_WEBSOCKET", "PING"], **{"traffic-shaper": "ARENA_INPUT_SHAPER",
                                                 "diffserv-forward": "enable", "diffservcode-forward": "101110"}),
        politica(5, "A12_PARA_INTERNET", "dmz", u, "A12_PARISE_CORE", "all", ["ALL"], nat="enable", logtraffic="all"),
        # Repasse do ARENA (10/11/2026): a internet so alcanca a porta 55440 do A12, pelo VIP abaixo. Sem registro do
        # trafego: quem chega sao alunos (menores) jogando, e o endereco deles nao precisa ficar guardado no FortiGate.
        politica(6, "INTERNET_PARA_REPASSE_ARENA", u, "dmz", "all", "ARENA_REPASSE_VIP", ["ARENA_REPASSE"],
                 logtraffic="disable"),
        # Campeonato no switch (LAN2): os celulares dos alunos tambem jogam pelo repasse do A12, pelo codigo da sala (a
        # descoberta por broadcast nao passa de uma rede para a outra). Endereco interno: a12.bancada.lan:55440.
        politica(7, "CONTROLES_PARA_REPASSE_ARENA", "internal2", "dmz", "ARENA_CONTROLES", "REPASSE_ARENA_HOSPEDEIROS",
                 ["ARENA_REPASSE"], logtraffic="disable"),
        # O PC como segundo hospedeiro do repasse (11/11/2026): os dois trabalham juntos. Pela internet, o A12 atende na
        # porta 55440 do uplink (regra 6) e o PC na 55441 (regra 9: o VIP leva para a 55440 dele na LAN1). O aluno de fora
        # escreve "endereco:55440" ou "endereco:55441" nos Ajustes do ARENA. Sem nenhum dos dois ligado, o ARENA usa os
        # repasses publicos do RetroArch (servidor\graficos.py, REPASSES), e as regras ficam sem uso, sem quebrar nada.
        politica(8, "PC_DMZ_PARA_INTERNET", "dmz", u, "PC_RYZEN_DMZ", "all", ["ALL"], nat="enable"),
        politica(9, "INTERNET_PARA_REPASSE_PC", u, "internal", "all", "ARENA_REPASSE_VIP_PC", ["ARENA_REPASSE"],
                 logtraffic="disable"),
        politica(10, "CONTROLES_PARA_REPASSE_PC", "internal2", "internal", "ARENA_CONTROLES", "REPASSE_ARENA_HOSPEDEIROS",
                 ["ARENA_REPASSE"], logtraffic="disable"),
        # Ligar o PC de longe (13/11/2026): so o A12 (sempre ligado, na DMZ) manda o pacote magico (UDP 9) e o ping que
        # diz se o PC ligou. Com o PC desligado o FortiGate nao acharia o endereco fisico dele: o ARP fixo (passo
        # "ARP fixo do PC") resolve. A DMZ continua sem alcancar mais nada da LAN1.
        politica(11, "A12_LIGA_PC_WOL", "dmz", "internal", "A12_PARISE_CORE", "PC_RYZEN", ["WOL_UDP9", "PING"],
                 logtraffic="disable"),
    ]


# Os VIPs (porta do uplink -> hospedeiro do repasse) vao pelo restore junto com as regras e ANTES delas (as regras 6 e 9
# usam os VIPs). O FortiOS 5.4 leva uma porta externa a um so endereco: 55440 -> A12, 55441 -> PC (na LAN1).
def cli_vips(uplink=UPLINK_PADRAO):
    return ["config firewall vip",
            '    edit "ARENA_REPASSE_VIP"', '        set comment "repasse do ARENA no A12"',
            f'        set extintf "{uplink}"', "        set portforward enable", "        set mappedip 10.0.10.50",
            "        set protocol tcp", "        set extport 55440", "        set mappedport 55440", "    next",
            '    edit "ARENA_REPASSE_VIP_PC"', '        set comment "repasse do ARENA no PC (LAN1)"',
            f'        set extintf "{uplink}"', "        set portforward enable", "        set mappedip 10.0.20.100",
            "        set protocol tcp", "        set extport 55441", "        set mappedport 55440", "    next",
            "end"]


REGRAS = montar_regras()      # o desenho padrão (uplink na WAN1), para quem só importa a lista
ENTRE_ASPAS = {"name", "schedule", "traffic-shaper"}


def cli_regras(uplink=UPLINK_PADRAO):
    """As regras e os VIPs em sintaxe de CLI (a API do 5.4 não cria regra: devolve 405)."""
    out = cli_vips(uplink) + ["config firewall policy"]
    for r in montar_regras(uplink):
        out.append(f"    edit {r['policyid']}")
        for k, v in r.items():
            if k == "policyid":
                continue
            if isinstance(v, list):
                v = " ".join(f'"{x["name"]}"' for x in v)
            elif k in ENTRE_ASPAS:
                v = f'"{v}"'
            out.append(f"        set {k} {v}")
        out.append("    next")
    out.append("end")
    return out


CLI_IP_LAN1 = ["config system interface", '    edit "internal"', f"        set ip {IP_LAN1} {M24}",
               "        set allowaccess ping https ssh", "    next", "end"]


def cli_lan1(mac_pc):
    return CLI_IP_LAN1 + cli_dhcp_lan1(mac_pc)


def cli_dhcp_lan1(mac_pc):
    return [
        "config system dhcp server", "    edit 1", '        set interface "internal"',
        "        set default-gateway 10.0.20.1", f"        set netmask {M24}", "        set dns-service local",
        "        config ip-range", "            edit 1", "                set start-ip 10.0.20.50",
        "                set end-ip 10.0.20.150", "            next", "        end",
        "        config reserved-address", "            edit 1", "                set ip 10.0.20.100",
        f"                set mac {mac_pc}", "            next", "        end", "    next", "end",
    ]


def _intf(lista):
    return sorted(x.get("name") for x in lista or [])


def divergencias(api, uplink=UPLINK_PADRAO):
    """O que o restore ainda precisa mudar: regras faltando, regras ou VIPs na interface errada, IP da LAN1.
    Só lê. Antes de 12/11/2026 só os nomes eram conferidos, e trocar a interface de uma regra existente não
    disparava o restore."""
    faltas = []
    vistas = {p.get("name"): p for p in api.ler("firewall/policy") or []}
    for r in montar_regras(uplink):
        p = vistas.get(r["name"])
        if p is None:
            faltas.append(f"regra {r['name']} não existe")
            continue
        for campo in ("srcintf", "dstintf"):
            if _intf(p.get(campo)) != _intf(r[campo]):
                faltas.append(f"regra {r['name']}: {campo} {_intf(p.get(campo))} -> {_intf(r[campo])}")
    for v in api.ler("firewall/vip") or []:
        if v.get("name", "").startswith("ARENA_REPASSE_VIP") and v.get("extintf") != uplink:
            faltas.append(f"VIP {v['name']}: extintf {v.get('extintf')} -> {uplink}")
    if not api.ler("system/interface/internal")[0]["ip"].startswith(IP_LAN1):
        faltas.append(f"LAN1 fora de {IP_LAN1}")
    return faltas


def precisa_restore(api, uplink=UPLINK_PADRAO):
    return bool(divergencias(api, uplink))


def conferir(api, uplink, log):
    """Modo --conferir: compara o aparelho com o desenho, sem gravar nada."""
    portas = [p["name"] for p in api.ler("system/virtual-switch/internal")[0]["port"]]
    presas = [p for p in portas_fora_do_switch(uplink) if p in portas]
    log(f"  switch da LAN1: {', '.join(portas)}" + (f"  (sairiam: {', '.join(presas)})" if presas else ""))
    if not presas:
        i = api.ler(f"system/interface/{uplink}")[0]
        log(f"  {uplink}: modo {i.get('mode')}, ip {i.get('ip')}, acesso '{i.get('allowaccess')}', "
            f"distância {i.get('distance')}")
    faltas = divergencias(api, uplink)
    for f in faltas:
        log(f"  restore mudaria: {f}")
    log("  regras e VIPs já batem com o desenho." if not faltas else
        f"  {len(faltas)} diferença(s): o --aplicar faria o restore (o FortiGate reinicia, uns 3 minutos).")
    return faltas


def tentar_restore(api, env, log, uplink=UPLINK_PADRAO):
    """Backup + regras + LAN1 nova no fim do arquivo + restore. True se o aparelho aceitou (e reinicia)."""
    texto = api.backup().rstrip("\n").split("\n")
    texto += cli_regras(uplink) + cli_lan1(env["MAC_RYZEN"])
    LOGS.mkdir(exist_ok=True)
    (LOGS / "ultimo-restore.conf").write_text("\n".join(texto) + "\n", encoding="utf-8")  # fora do git
    st, resp = api.restaurar("\n".join(texto) + "\n")
    ok = st is None or (resp.get("results") or {}).get("config_restored") is True
    log(f"  restore: {'aceito; o FortiGate reinicia (uns 3 minutos)' if ok else (resp.get('results') or resp)}")
    return ok


class CanalSSH:
    """Faz um shell SSH (paramiko) parecer uma porta serial para o fortios_console.Console."""

    def __init__(self, host, usuario, senha):
        import paramiko
        self.cli = paramiko.SSHClient()
        self.cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # cabo direto PC -> porta 1
        self.cli.connect(host, username=usuario, password=senha, look_for_keys=False,
                         allow_agent=False, timeout=15)
        self.ch = self.cli.invoke_shell(width=200)

    @property
    def in_waiting(self):
        return 65536 if self.ch.recv_ready() else 0

    def read(self, n=1):
        if self.ch.recv_ready():
            return self.ch.recv(n)
        time.sleep(0.05)
        return b""

    def write(self, dados):
        self.ch.send(dados)
        return len(dados)

    def reset_input_buffer(self):
        while self.ch.recv_ready():
            self.ch.recv(65536)

    def close(self):
        self.cli.close()


def aplicar_por_ssh(host, env, log, uplink=UPLINK_PADRAO):
    """Regras e DHCP pelo CLI via SSH; por último o IP da LAN1 (a sessão cai nessa hora)."""
    import fortios_console as fc
    con = fc.Console(CanalSSH(host, "admin", env["ADMIN_SENHA"]), pausa=1.0)
    try:
        con.acordar(tentativas=10)
    except fc.FalhaLogin:
        con.fechar()
        raise ErroAPI("O CLI do FortiGate não responde nem pelo SSH (processo interno travado). "
                      "Desligue o FortiGate da tomada por 10 s, ligue, espere 3 min e rode de novo.")
    try:
        for linha in ["config system console", "set output standard", "end"] + cli_regras(uplink) + \
                cli_dhcp_lan1(env["MAC_RYZEN"]) + CLI_IP_LAN1[:-1]:
            con.comando(linha.strip(), confirmar=True)
        con.enviar("end")          # aplica o IP novo; a sessão cai aqui
        time.sleep(3)
    except fc.FalhaFortiOS as e:
        raise ErroAPI(f"CLI recusou: {e}")
    finally:
        con.fechar()
    log("  aplicado pelo CLI")


def esperar_lan1(api, env, nic, log):
    """Renova o IP deste PC até entrar no FortiGate em 10.0.20.1."""
    api.host = IP_LAN1
    for _ in range(30):                  # até ~5 minutos
        time.sleep(10)
        ps(f"ipconfig /renew '{nic}' | Out-Null")
        if ip_do_pc(nic).startswith("10.0.20."):
            try:
                api.login("admin", env["ADMIN_SENHA"])
                log(f"  voltou: {IP_LAN1}; IP deste PC {ip_do_pc(nic)}")
                # Depois de reiniciar, a rota da DMZ pode ficar presa (13/11, depois do restore do Wake-on-LAN: o PC
                # nao alcancou o A12 por 5 h). Da 1 minuto para o A12 pegar o endereco e confere/conserta.
                try:
                    import religar_dmz
                    time.sleep(60)
                    log("  DMZ: " + (religar_dmz.consertar_se_preciso(intervalo_minimo=0) or "o A12 responde"))
                except Exception as falha:  # noqa: BLE001 - conferencia extra: nunca derruba o provisionamento
                    log(f"  DMZ: nao conferi ({falha})")
                return
            except ErroAPI:
                pass
    raise ErroAPI("O FortiGate não voltou em 10.0.20.1. Veja logs/ultimo-restore.conf e o IP do PC.")


# ---------- IP deste PC ----------
def ps(cmd):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True)
    return r.stdout.strip()


def ip_do_pc(nic):
    return ps(f"(Get-NetIPAddress -InterfaceAlias '{nic}' -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress")


# ---------- principal ----------
def entrar(api, env, log):
    """Entra com a senha nova; se ainda for a de fábrica (vazia), troca."""
    try:
        api.login("admin", env["ADMIN_SENHA"])
        return
    except ErroAPI:
        api.login("admin", "")
    log("[admin] login de fábrica sem senha; trocando para a ADMIN_SENHA")
    api.ajustar("system/admin/admin", {"password": env["ADMIN_SENHA"]})
    api.login("admin", env["ADMIN_SENHA"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument("--aplicar", action="store_true", help="aplica (o restore reinicia o FortiGate)")
    modo.add_argument("--conferir", action="store_true", help="entra e só lê: o que o --aplicar mudaria")
    ap.add_argument("--mostrar-cli", action="store_true", help="mostra o bloco de CLI do restore, sem conectar")
    ap.add_argument("--uplink", choices=UPLINKS, help="porta da internet (padrão: FORTIGATE_UPLINK ou wan1)")
    args = ap.parse_args(argv)
    env = ler_env(ENV)
    uplink = args.uplink or env.get("FORTIGATE_UPLINK") or UPLINK_PADRAO
    if uplink not in UPLINKS:
        print(f"FORTIGATE_UPLINK inválido: {uplink} (use {' ou '.join(UPLINKS)}).")
        return 1
    if not SENHA_OK.match(env.get("ADMIN_SENHA", "")) or not MAC.match(env.get("MAC_RYZEN", "")):
        print("Preencha ADMIN_SENHA e MAC_RYZEN no .env (veja .env.example).")
        return 1
    for k in ("MAC_A12", "MAC_CONTROLE_1", "MAC_CONTROLE_2"):
        if env.get(k) and not MAC.match(env[k]):
            print(f"{k} inválido (formato AA:BB:CC:DD:EE:FF).")
            return 1
    passos = montar_passos(env, uplink)
    if not (args.aplicar or args.conferir):
        print(f"Uplink (internet): {uplink}")
        for n, (nome, opc, _) in enumerate(passos, 1):
            print(f"{n:2}. {nome}{'  (opcional)' if opc else ''}")
        print(f"{len(passos) + 1:2}. regras e VIPs pelo restore (o FortiGate reinicia), LAN1 em {IP_LAN1}")
        if args.mostrar_cli:
            print("\n# bloco que o restore acrescenta ao backup:")
            print("\n".join(cli_regras(uplink)))
        print("\nNada foi enviado (nem conectou). Use --conferir para só ler o aparelho, --aplicar para aplicar.")
        return 0

    nic = env.get("NIC_PC", "Cabo FortiGate 60D")   # era "Ethernet 2" ate 14/11/2026 (renomeada)
    host = env.get("FORTIGATE_IP") or (IP_LAN1 if ip_do_pc(nic).startswith("10.0.20.") else IP_FABRICA)
    api = FortiAPI(host, impressao=env.get("FORTIGATE_CERT_SHA256"))
    log = print
    try:
        if args.conferir:
            api.login("admin", env["ADMIN_SENHA"])     # só lê: nada de trocar senha de fábrica neste modo
        else:
            entrar(api, env, log)
        if not env.get("FORTIGATE_CERT_SHA256"):
            gravar_env(ENV, "FORTIGATE_CERT_SHA256", api.impressao_vista)
            api.impressao = api.impressao_vista
        fw = api.monitor("system/firmware")["current"]
        log(f"[FortiOS] {fw['version']} build {fw['build']} em {host}; uplink {uplink}")
        if args.conferir:
            conferir(api, uplink, log)
            log("\nNada foi gravado (modo --conferir).")
            return 0
        falhas = []
        for nome, opcional, f in passos:
            try:
                f(api)
                log(f"[ok]     {nome}")
            except ErroAPI as e:
                if not opcional:
                    log(f"[PAROU]  {nome}\n         {e}")
                    return 3
                falhas.append(nome)
                log(f"[pulado] {nome}\n         {e}")
        if precisa_restore(api, uplink):
            log("[final]  regras de firewall, VIPs e LAN1 em 10.0.20.1")
            if not tentar_restore(api, env, log, uplink):
                log("  tentando pelo CLI via SSH")
                aplicar_por_ssh(api.host, env, log, uplink)
            esperar_lan1(api, env, nic, log)
            gravar_env(ENV, "FORTIGATE_IP", IP_LAN1)
        regras = [p.get("name") for p in api.ler("firewall/policy")]
        lan1 = api.ler("system/interface/internal")[0]["ip"]
        log(f"[conferido] LAN1 {lan1} | regras: {', '.join(regras)}")
        log("\nPronto." + (f" Opcionais recusados pelo FortiOS 5.4: {', '.join(falhas)}." if falhas else ""))
        return 0
    except ErroAPI as e:
        log(f"\nPAROU: {e}")
        return 3
    finally:
        api.logout()


if __name__ == "__main__":
    sys.exit(main())
