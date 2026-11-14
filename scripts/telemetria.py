#!/usr/bin/env python3
"""
telemetria.py: a telemetria sutil da bancada (11/11/2026).

O que ela faz: a cada 5 minutos (tarefa agendada do usuário, sem administrador) colhe UMA amostra pequena da
saúde dos equipamentos e dos enlaces, guarda em data/telemetria/AAAA-MM-DD.jsonl (fora do git) e reescreve
memoria/telemetria/RESUMO.md, o arquivo que as IAs leem: o Hermes (parise-core-windows), o Qwen do A12
(pelas amostras locais dele) e o Claude Code. Com as amostras, elas enxergam enlace caindo, latência subindo,
FortiGate no limite, celular esquentando, e propõem o conserto com números em vez de palpite.

O que ela colhe (só o essencial, dos equipamentos do Rafael):
  - rede: ping ao FortiGate (10.0.20.1), ao A12 na DMZ (10.0.10.50), ao roteador da casa (gateway do Wi-Fi) e a
    dois DNS públicos (1.1.1.1 e 8.8.8.8): perda e latência;
  - FortiGate (API de monitoramento, conta do admin lida do .env): uso de CPU e memória, estado e contadores
    das interfaces, QUANTIDADE de endereços entregues por DHCP em cada rede (só o número);
  - este PC: memória livre, tempo ligado, estado dos adaptadores de rede;
  - Galaxy A12 (quando está no cabo USB): bateria, temperatura, memória livre, tempo ligado, endereço na DMZ;
    e as amostras que o sentinela do A12 escreve em /sdcard/parise-sync/telemetria/amostras.jsonl.

O que ela NUNCA colhe (a rede tem celular de aluno, menor de idade, na LAN2):
  - MAC, nome de aparelho, endereço ou tráfego de qualquer celular da LAN2: só a contagem de endereços do DHCP;
  - registro de tráfego (as regras do repasse ficam com logtraffic desligado);
  - senha, chave ou número de série (o .env é lido só para entrar na API; nada dele vai para a amostra);
  - nada sai deste computador: não há envio para serviço nenhum.

Uso:
    python scripts\\telemetria.py coletar          colhe uma amostra e reescreve o RESUMO.md
    python scripts\\telemetria.py resumo           só reescreve o RESUMO.md com as amostras que já existem
    python scripts\\telemetria.py mostrar          imprime a última amostra de cada fonte
    python scripts\\telemetria.py instalar-tarefa  registra a tarefa "Telemetria-Bancada" (a cada 5 min, usuário)
    python scripts\\telemetria.py remover-tarefa
"""
import ctypes
import datetime as dt
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

# A tarefa agendada roda no pythonw (sem console): sem esta marca, cada ping/route/netsh/adb abria uma janela
# preta do Terminal por cima de tudo, a cada 5 minutos (14/11/2026). CREATE_NO_WINDOW so existe no Windows.
SEM_JANELA = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

PASTA = Path(__file__).resolve().parent
RAIZ = PASTA.parent
sys.path.insert(0, str(PASTA))

DADOS = RAIZ / "data" / "telemetria"
RESUMO = RAIZ / "memoria" / "telemetria" / "RESUMO.md"
TAREFA = "Telemetria-Bancada"
JANELA_HORAS = 24
ALVOS_LAN = {"fortigate": "10.0.20.1", "a12_dmz": "10.0.10.50"}
ALVOS_INTERNET = {"dns_cloudflare": "1.1.1.1", "dns_google": "8.8.8.8"}
LIMITES = {"ping_lan_ms": 50, "ping_internet_ms": 150, "perda_pct": 20, "forti_cpu_pct": 80, "forti_mem_pct": 85,
           "pc_mem_livre_mb": 1024, "a12_temp_c": 45, "a12_bateria_pct": 15}
AMOSTRAS_A12 = "/sdcard/parise-sync/telemetria/amostras.jsonl"


def agora():
    return dt.datetime.now().replace(microsecond=0).isoformat()


# ---------- rede: ping ----------
def ping(host, vezes=3):
    """{'perda_pct', 'media_ms'} ou None se o ping não rodou. Funciona no ping do Windows (pt-BR e en)."""
    try:
        saida = subprocess.run(["ping", "-n", str(vezes), "-w", "1000", host], capture_output=True, text=True,
                               timeout=vezes * 2 + 5, errors="replace", **SEM_JANELA).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    perda = re.search(r"\((\d+)%", saida)
    media = re.search(r"(?:M[ée]dia|Average)\s*=\s*(\d+)\s*ms", saida)
    return {"perda_pct": int(perda.group(1)) if perda else 100, "media_ms": int(media.group(1)) if media else None}


def gateway_do_wifi():
    """O roteador da casa: o gateway padrão que não é o FortiGate."""
    try:
        saida = subprocess.run(["route", "print", "0.0.0.0"], capture_output=True, text=True, timeout=10,
                               errors="replace", **SEM_JANELA).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for g in re.findall(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)", saida, re.M):
        if g != ALVOS_LAN["fortigate"]:
            return g
    return None


def amostra_rede():
    alvos = dict(ALVOS_LAN)
    roteador = gateway_do_wifi()
    if roteador:
        alvos["roteador_casa"] = roteador
    alvos.update(ALVOS_INTERNET)
    return {"t": agora(), "fonte": "rede", "pings": {nome: ping(ip) for nome, ip in alvos.items()},
            "alvos": alvos}


# ---------- FortiGate ----------
def amostra_fortigate():
    """CPU, memória, interfaces e contagem do DHCP pela API de monitoramento do FortiOS 5.4."""
    try:
        from fortigate_api import ErroAPI, FortiAPI
        from provisionar_fortigate import ENV, ler_env
    except ImportError as e:
        return {"t": agora(), "fonte": "fortigate", "erro": f"sem o cliente da API: {e}"}
    env = ler_env(ENV) if ENV.exists() else {}
    host = env.get("FORTIGATE_IP", ALVOS_LAN["fortigate"])
    if not env.get("ADMIN_SENHA"):
        return {"t": agora(), "fonte": "fortigate", "erro": "sem ADMIN_SENHA no .env"}
    api = FortiAPI(host, env.get("FORTIGATE_CERT_SHA256") or None, timeout=15)
    amostra = {"t": agora(), "fonte": "fortigate", "host": host}
    try:
        api.login("admin", env["ADMIN_SENHA"])
    except Exception as e:                         # ErroAPI, OSError, ssl: o aparelho pode estar desligado
        amostra["erro"] = f"login: {str(e)[:120]}"
        return amostra
    try:
        # No 5.4 o caminho e' system/resource (lista de {id: "cpu.average", value: ...}); o resource/usage e' do 5.6+.
        for chave, caminho in (("recursos", "system/resource"), ("recursos", "system/resource/usage"),
                               ("interfaces", "system/interface"),
                               ("interfaces", "system/interface/select"), ("dhcp", "system/dhcp")):
            if chave in amostra:
                continue
            try:
                amostra[chave] = _enxugar(chave, api.monitor(caminho))
            except (ErroAPI, OSError, ValueError, KeyError, TypeError):
                continue
    finally:
        try:
            api.logout()
        except Exception:
            pass
    return amostra


def _enxugar(chave, dados):
    """Só o que a IA precisa: números por interface, nunca lista de clientes."""
    if chave == "recursos":
        saida = {}
        if isinstance(dados, list):                 # 5.4: [{"id": "cpu.average", "value": 3, "status": "normal"}, ...]
            for it in dados:
                if isinstance(it, dict) and it.get("id") and isinstance(it.get("value"), (int, float)):
                    saida[it["id"]] = it["value"]
            return saida
        for nome, valor in (dados or {}).items():
            if isinstance(valor, list) and valor and isinstance(valor[0], dict):
                saida[nome] = valor[0].get("current", valor[0])
            elif isinstance(valor, (int, float, str)):
                saida[nome] = valor
        return saida
    if chave == "interfaces":
        itens = dados.values() if isinstance(dados, dict) else dados
        saida = {}
        for it in itens or []:
            if not isinstance(it, dict) or not it.get("name"):
                continue
            saida[it["name"]] = {k: it.get(k) for k in ("link", "speed", "duplex", "rx_bytes", "tx_bytes",
                                                        "rx_errors", "tx_errors", "rx_packets", "tx_packets")
                                 if k in it}
        return saida
    if chave == "dhcp":
        # O 5.4 devolve [{"intf": "dmz", "list": [cliente, ...]}, ...]. Fica so a CONTAGEM por rede: a lista traz
        # MAC e nome de cada aparelho, e isso nao entra na amostra.
        contagem = {}
        for it in dados or []:
            if isinstance(it, dict) and "intf" in it:
                contagem[it["intf"]] = len(it.get("list") or [])
            elif isinstance(it, dict):
                contagem[it.get("interface", "?")] = contagem.get(it.get("interface", "?"), 0) + 1
        return {"enderecos_entregues": contagem}
    return dados


# ---------- este PC ----------
class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def amostra_pc():
    amostra = {"t": agora(), "fonte": "pc"}
    if os.name == "nt":
        m = _MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(m)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            amostra["mem_livre_mb"] = m.ullAvailPhys // (1024 * 1024)
            amostra["mem_uso_pct"] = m.dwMemoryLoad
        amostra["ligado_h"] = round(ctypes.windll.kernel32.GetTickCount64() / 3_600_000, 1)
        try:
            saida = subprocess.run(["netsh", "interface", "show", "interface"], capture_output=True, text=True,
                                   timeout=10, encoding="utf-8", errors="replace", **SEM_JANELA).stdout
            adaptadores = {}
            for linha in saida.splitlines():
                partes = linha.split()
                if len(partes) >= 4 and partes[0] in ("Habilitado", "Enabled", "Desabilitado", "Disabled"):
                    adaptadores[" ".join(partes[3:])] = partes[1]      # Conectado / Desconectado
            amostra["adaptadores"] = adaptadores
        except (OSError, subprocess.TimeoutExpired):
            pass
    return amostra


# ---------- Galaxy A12 pelo cabo ----------
def _adb(*args, segundos=15):
    adb = shutil.which("adb")
    if not adb:
        return None
    try:
        r = subprocess.run([adb] + list(args), capture_output=True, text=True, timeout=segundos, errors="replace", **SEM_JANELA)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def amostra_a12():
    estado = _adb("get-state")
    if not estado or "device" not in estado:
        return {"t": agora(), "fonte": "a12", "no_cabo": False}
    amostra = {"t": agora(), "fonte": "a12", "no_cabo": True}
    bateria = _adb("shell", "dumpsys", "battery") or ""
    for chave, campo, escala in (("bateria_pct", "level", 1), ("bateria_temp_c", "temperature", 10)):
        m = re.search(rf"{campo}: (\d+)", bateria)
        if m:
            amostra[chave] = int(m.group(1)) / escala
    temps = _adb("shell", "cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null") or ""
    valores = [int(v) / (1000 if int(v) > 1000 else 1) for v in re.findall(r"\d+", temps)]
    valores = [v for v in valores if 0 < v < 120]
    if valores:
        amostra["temp_max_c"] = round(max(valores), 1)
    mem = _adb("shell", "grep MemAvailable /proc/meminfo") or ""
    m = re.search(r"(\d+)", mem)
    if m:
        amostra["mem_livre_mb"] = int(m.group(1)) // 1024
    up = _adb("shell", "cat /proc/uptime") or ""
    if up.split():
        amostra["ligado_h"] = round(float(up.split()[0]) / 3600, 1)
    ip = _adb("shell", "ip -o -4 addr show wlan0 2>/dev/null") or ""
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", ip)
    if m:
        amostra["wifi_ip"] = m.group(1)
        amostra["na_dmz"] = m.group(1).startswith("10.0.10.")
    # As amostras do sentinela do A12 (termux): só as que ainda não vieram.
    locais = _adb("shell", f"tail -n 50 {AMOSTRAS_A12} 2>/dev/null") or ""
    amostra["amostras_do_sentinela"] = [json.loads(l) for l in locais.splitlines() if l.startswith("{")][-12:]
    return amostra


# ---------- guardar e resumir ----------
def guardar(amostras):
    DADOS.mkdir(parents=True, exist_ok=True)
    arquivo = DADOS / (dt.date.today().isoformat() + ".jsonl")
    with arquivo.open("a", encoding="utf-8") as f:
        for a in amostras:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    return arquivo


def ler_janela(horas=JANELA_HORAS):
    limite = dt.datetime.now() - dt.timedelta(hours=horas)
    itens = []
    for arquivo in sorted(DADOS.glob("*.jsonl"))[-3:]:
        for linha in arquivo.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                a = json.loads(linha)
                if dt.datetime.fromisoformat(a["t"]) >= limite:
                    itens.append(a)
            except (ValueError, KeyError):
                continue
    return itens


def _num(valores):
    v = [x for x in valores if isinstance(x, (int, float))]
    if not v:
        return None
    return {"n": len(v), "mediana": round(statistics.median(v), 1), "max": round(max(v), 1), "min": round(min(v), 1)}


def resumir(itens):
    por_fonte = {}
    for a in itens:
        por_fonte.setdefault(a.get("fonte"), []).append(a)
    linhas, alertas = [], []
    # Rede
    rede = por_fonte.get("rede", [])
    if rede:
        nomes = sorted({n for a in rede for n in a.get("pings", {})})
        linhas.append(f"**Enlaces (ping, {len(rede)} amostras):**")
        for nome in nomes:
            ps = [a["pings"].get(nome) for a in rede if a.get("pings")]
            ok = [p for p in ps if p]
            disp = sum(1 for p in ok if p["perda_pct"] < 100) / max(1, len(ps)) * 100
            lat = _num([p["media_ms"] for p in ok if p.get("media_ms") is not None])
            alvo = next((a["alvos"].get(nome) for a in reversed(rede) if a.get("alvos", {}).get(nome)), "?")
            texto = f"- {nome} ({alvo}): disponível {disp:.0f}%"
            if lat:
                texto += f"; latência mediana {lat['mediana']} ms, máxima {lat['max']} ms"
            linhas.append(texto)
            limite = LIMITES["ping_lan_ms"] if alvo.startswith("10.0.") else LIMITES["ping_internet_ms"]
            if ok and ok[-1]["perda_pct"] >= LIMITES["perda_pct"] and nome != "a12_dmz":
                alertas.append(f"{nome}: perda de {ok[-1]['perda_pct']}% na última amostra")
            if lat and lat["max"] > limite:
                alertas.append(f"{nome}: latência chegou a {lat['max']} ms (limite {limite})")
    # FortiGate
    forti = [a for a in por_fonte.get("fortigate", []) if "erro" not in a]
    erros_forti = [a for a in por_fonte.get("fortigate", []) if "erro" in a]
    if forti or erros_forti:
        linhas.append(f"**FortiGate ({len(forti)} amostras com resposta, {len(erros_forti)} sem):**")
        def _medida(a, *chaves):
            r = a.get("recursos") or {}
            for k in chaves:
                if k in r:
                    return r[k]
            return None
        cpu = _num([_medida(a, "cpu.average", "cpu") for a in forti])
        mem = _num([_medida(a, "mem.usage", "mem.average", "mem", "memory.average") for a in forti])
        if cpu:
            linhas.append(f"- CPU: mediana {cpu['mediana']}%, máxima {cpu['max']}%")
            if cpu["max"] > LIMITES["forti_cpu_pct"]:
                alertas.append(f"FortiGate: CPU chegou a {cpu['max']}%")
        if mem:
            linhas.append(f"- memória: mediana {mem['mediana']}%, máxima {mem['max']}%")
            if mem["max"] > LIMITES["forti_mem_pct"]:
                alertas.append(f"FortiGate: memória chegou a {mem['max']}%")
        ultimo = forti[-1] if forti else {}
        for nome, it in sorted((ultimo.get("interfaces") or {}).items()):
            if nome in ("wan1", "wan2", "internal", "internal2", "internal3", "dmz"):   # internal3: uplink só na opção B
                linhas.append(f"- {nome}: enlace {it.get('link', '?')}, {it.get('speed', '?')}, erros rx/tx "
                              f"{it.get('rx_errors', '?')}/{it.get('tx_errors', '?')}")
        dhcp = (ultimo.get("dhcp") or {}).get("enderecos_entregues")
        if dhcp:
            linhas.append("- endereços entregues por DHCP: " + ", ".join(f"{k} {v}" for k, v in sorted(dhcp.items())))
        if erros_forti and not forti:
            alertas.append(f"FortiGate sem resposta: {erros_forti[-1]['erro']}")
    # PC
    pc = por_fonte.get("pc", [])
    if pc:
        mem = _num([a.get("mem_livre_mb") for a in pc])
        linhas.append(f"**Este PC ({len(pc)} amostras):** memória livre mínima {mem['min'] if mem else '?'} MB; "
                      f"ligado há {pc[-1].get('ligado_h', '?')} h; adaptadores: " +
                      ", ".join(f"{k} {v}" for k, v in sorted((pc[-1].get("adaptadores") or {}).items())))
        if mem and mem["min"] < LIMITES["pc_mem_livre_mb"]:
            alertas.append(f"PC: memória livre caiu a {mem['min']} MB (o restore do FortiGate já foi cortado por isso)")
    # A12
    a12 = [a for a in por_fonte.get("a12", []) if a.get("no_cabo")]
    fora = [a for a in por_fonte.get("a12", []) if not a.get("no_cabo")]
    if a12 or fora:
        linhas.append(f"**Galaxy A12 ({len(a12)} amostras no cabo, {len(fora)} fora):**")
        if a12:
            u = a12[-1]
            temp = _num([a.get("temp_max_c", a.get("bateria_temp_c")) for a in a12])
            bat = _num([a.get("bateria_pct") for a in a12])
            linhas.append(f"- bateria {u.get('bateria_pct', '?')}%, temperatura "
                          f"{u.get('temp_max_c', u.get('bateria_temp_c', '?'))} °C "
                          f"(máxima {temp['max'] if temp else '?'}), memória livre {u.get('mem_livre_mb', '?')} MB, "
                          f"ligado há {u.get('ligado_h', '?')} h, Wi-Fi {u.get('wifi_ip', 'sem')}"
                          f"{' (na DMZ)' if u.get('na_dmz') else ''}")
            if temp and temp["max"] > LIMITES["a12_temp_c"]:
                alertas.append(f"A12: temperatura chegou a {temp['max']} °C")
            if bat and bat["min"] < LIMITES["a12_bateria_pct"]:
                alertas.append(f"A12: bateria caiu a {bat['min']}%")
            sent = u.get("amostras_do_sentinela") or []
            if sent:
                linhas.append(f"- sentinela do A12: {len(sent)} amostras locais; última: "
                              + json.dumps(sent[-1], ensure_ascii=False)[:160])
    return linhas, alertas


def escrever_resumo(itens):
    linhas, alertas = resumir(itens)
    RESUMO.parent.mkdir(parents=True, exist_ok=True)
    texto = ["# Telemetria da bancada: resumo das últimas %d horas" % JANELA_HORAS, "",
             f"Gerado em {agora()} por `scripts/telemetria.py` ({len(itens)} amostras). Este arquivo é lido pelo "
             "Hermes (parise-core-windows), pelo Qwen do A12 e pelo Claude Code. Dados brutos em "
             "`data/telemetria/*.jsonl` (fora do git).", ""]
    texto += ["## Sinais de alerta", ""] + ([f"- {a}" for a in alertas] or ["- nenhum"]) + [""]
    texto += ["## Medidas", ""] + (linhas or ["- ainda sem amostras: rode `python scripts\\telemetria.py coletar`"])
    texto += ["", "## Para as IAs (como usar)", "",
              "- Um alerta é uma hipótese com número: proponha a causa e o conserto, e peça ao Claude Code para "
              "aplicar o que mexe no FortiGate.",
              "- Compare com o esperado: LAN abaixo de %d ms, internet abaixo de %d ms, FortiGate abaixo de %d%% de CPU, "
              "PC com mais de %d MB livres, A12 abaixo de %d °C." % (LIMITES["ping_lan_ms"], LIMITES["ping_internet_ms"],
                                                                     LIMITES["forti_cpu_pct"], LIMITES["pc_mem_livre_mb"],
                                                                     LIMITES["a12_temp_c"]),
              "- O que NÃO está aqui, de propósito: MAC, nome, endereço ou tráfego de celular de aluno (LAN2); só "
              "contagens. Nada disso deve ser pedido nem inferido.", ""]
    RESUMO.write_text("\n".join(texto), encoding="utf-8")
    return alertas


def conserto_da_dmz(rede):
    """A "rota presa" da DMZ (13 e 14/11/2026): o A12 some do PC com o enlace de pe. Se o ping ao A12 perdeu tudo,
    o religar_dmz confere e, se for ela, derruba e religa a dmz (no maximo uma vez a cada 30 min)."""
    perda = ((rede.get("pings") or {}).get("a12_dmz") or {}).get("perda_pct")
    if perda != 100:
        return None
    try:
        import religar_dmz
        feito = religar_dmz.consertar_se_preciso()
    except Exception as falha:  # noqa: BLE001 - a telemetria nunca cai por isso
        feito = "religar_dmz falhou: %s" % str(falha)[:120]
    return {"t": agora(), "fonte": "dmz_conserto", "feito": feito} if feito else None


def coletar():
    amostras = [amostra_rede(), amostra_fortigate(), amostra_pc(), amostra_a12()]
    conserto = conserto_da_dmz(amostras[0])
    if conserto:
        amostras.append(conserto)
    arquivo = guardar(amostras)
    alertas = escrever_resumo(ler_janela())
    print(f"amostra guardada em {arquivo}; resumo em {RESUMO}; alertas: {len(alertas)}")
    for a in alertas:
        print("  ! " + a)
    return 0


def mostrar():
    ultimas = {}
    for a in ler_janela():
        ultimas[a.get("fonte")] = a
    for fonte, a in ultimas.items():
        print(f"== {fonte}")
        print(json.dumps(a, ensure_ascii=False, indent=1)[:1500])
    return 0


def instalar_tarefa():
    python = Path(sys.executable).with_name("pythonw.exe")
    if not python.exists():
        python = Path(sys.executable)
    comando = f'"{python}" "{PASTA / "telemetria.py"}" coletar'
    r = subprocess.run(["schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", "5", "/TN", TAREFA, "/TR", comando],
                       capture_output=True, text=True, errors="replace")
    print((r.stdout + r.stderr).strip())
    return r.returncode


def remover_tarefa():
    r = subprocess.run(["schtasks", "/Delete", "/F", "/TN", TAREFA], capture_output=True, text=True, errors="replace")
    print((r.stdout + r.stderr).strip())
    return r.returncode


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    verbo = argv[0] if argv else "coletar"
    acoes = {"coletar": coletar, "resumo": lambda: (escrever_resumo(ler_janela()), 0)[1], "mostrar": mostrar,
             "instalar-tarefa": instalar_tarefa, "remover-tarefa": remover_tarefa}
    if verbo not in acoes:
        print(__doc__)
        return 2
    return acoes[verbo]()


if __name__ == "__main__":
    sys.exit(main())
