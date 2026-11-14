# -*- coding: utf-8 -*-
"""
estado_casa.py - o que da infraestrutura de casa está de pé (atalho "Infraestrutura da casa", 13/11/2026).

Desde 14/11/2026 é um PAINEL AO VIVO: enquanto a janela está aberta, atualiza a cada 3 s (pedido do Rafael: "precisa
atualizar o estado a cada 3 segundos pelo menos enquanto estiver aberto"). Fechar a janela (ou Ctrl+C) encerra.

Só lê; não muda nada. Mostra, em frases curtas:
  - FortiGate: CPU, memória, sessões, o DNS em uso e, por porta (WAN1, DMZ, LAN2), o enlace e a vazão agora;
  - internet: o tempo de resposta até a Cloudflare (1.1.1.1, conexão TCP: sem abrir o ping, que pisca janela);
  - A12 na DMZ: o repasse do ARENA (55440) e o endereço de ligar o PC (8000); se o A12 some com o enlace de pé, avisa
    da "rota presa" e do conserto (scripts\\religar_dmz.py);
  - Tailscale: este PC e o A12 online, e quem pode ser a SAÍDA para a internet (a VPN de casa) agora;
  - o que funciona com o PC desligado e o que precisa dele.
Nada de senha, MAC ou número de série na tela.

Como fica leve (as mesmas ideias do plano de desempenho do ARENA: não repetir trabalho, nada esperando à toa):
  - uma sessão só no FortiGate, aberta uma vez (antes: login a cada consulta); cada volta são 3 consultas de ~0,05 s;
  - as conferências correm juntas, cada uma com tempo-limite curto: uma porta fechada não segura as outras;
  - o Tailscale (o mais lento, ~1 s) só a cada 15 s; o DNS do FortiGate só a cada 60 s;
  - nenhum programa externo abre janela (CREATE_NO_WINDOW).

Uso:  python scripts\\estado_casa.py            (painel ao vivo; o atalho chama scripts\\estado-casa.cmd)
      python scripts\\estado_casa.py --uma-vez  (uma foto só, como antes)
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
TAILSCALE = r"C:\Program Files\Tailscale\tailscale.exe"
A12 = "10.0.10.50"
INTERVALO = 3.0
PORTAS = [("wan1", "WAN1 (internet, ONT)"), ("dmz", "DMZ (A12)"), ("internal2", "LAN2 (switch do ARENA)")]
SEM_JANELA = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def porta_aberta(ip, porta, espera=1.5):
    try:
        with socket.create_connection((ip, porta), timeout=espera):
            return True
    except OSError:
        return False


def tempo_ate(ip, porta, espera=1.5):
    """Milissegundos para abrir uma conexão TCP (a ida e volta), ou None.

    A conexão é BLOQUEANTE, numa linha à parte, e quem espera é o Event: com tempo-limite no próprio socket, o Python
    no Windows espera pelo select(), que soma ~10 ms a cada medida (14/11/2026: PC -> FortiGate deu 10,1 ms assim e
    0,70 ms bloqueante; a Cloudflare, 17,8 contra 8,9 ms). Sem resposta em `espera`, devolve None (a linha termina
    sozinha depois)."""
    import threading
    resultado, pronto = [], threading.Event()

    def medir():                    # a melhor de 3: a volta corre junto com as outras conferências e uma só oscila
        try:
            for _ in range(3):
                conexao = socket.socket()
                inicio = time.perf_counter()
                try:
                    conexao.connect((ip, porta))
                    resultado.append((time.perf_counter() - inicio) * 1000)
                except OSError:
                    return
                finally:
                    conexao.close()
        finally:
            pronto.set()
    threading.Thread(target=medir, daemon=True).start()
    pronto.wait(espera)
    return min(resultado) if resultado else None


class FortiGate:
    """Uma sessão só, reaberta se cair (o FortiGate reiniciou, a senha mudou...)."""

    def __init__(self):
        self.api = None
        self.anterior = {}            # bytes de cada porta na volta passada, para a vazão
        self.dns = None
        self.dns_lido = 0.0
        self.falha_desde = 0.0

    def _entrar(self):
        from fortigate_api import FortiAPI
        from provisionar_fortigate import ENV, ler_env
        env = ler_env(ENV)
        api = FortiAPI(env.get("FORTIGATE_IP", "10.0.20.1"), env.get("FORTIGATE_CERT_SHA256") or None, timeout=2.5)
        api.login("admin", env["ADMIN_SENHA"])
        self.api = api

    def sair(self):
        if self.api:
            try:
                self.api.logout()
            except Exception:  # noqa: BLE001 - saindo de qualquer jeito
                pass
            self.api = None

    def contadores_da_wan(self):
        """(bytes que entraram, bytes que saíram) da WAN1 agora, ou None (para o teste de internet conferir)."""
        try:
            if self.api is None:
                self._entrar()
            wan = (self.api.monitor("system/interface") or {}).get("wan1") or {}
            return wan.get("rx_bytes", 0), wan.get("tx_bytes", 0)
        except Exception:  # noqa: BLE001 - a conferência é bônus
            return None

    def ler(self):
        """{"linhas": [...], "dmz_de_pe": bool}."""
        agora = time.monotonic()
        if self.api is None and agora - self.falha_desde < 10:
            return {"linhas": ["⛔ FortiGate não respondeu (tento de novo em instantes)"], "dmz_de_pe": None}
        try:
            if self.api is None:
                self._entrar()
            recursos = {x["id"]: x.get("value") for x in self.api.monitor("system/resource")}
            portas = self.api.monitor("system/interface") or {}
            if agora - self.dns_lido > 60:
                dns = self.api.ler("system/dns")
                dns = dns[0] if isinstance(dns, list) else dns
                self.dns, self.dns_lido = dns.get("primary"), agora
        except Exception as falha:  # noqa: BLE001 - só leitura: o motivo vira frase
            self.sair()
            self.falha_desde = agora
            return {"linhas": ["⛔ FortiGate não respondeu (%s)" % str(falha)[:70]], "dmz_de_pe": None}
        sessoes = next((v for k, v in recursos.items() if "sess" in k), None)
        linhas = ["✅ FortiGate: CPU %s%%, memória %s%%%s, DNS %s" % (
            recursos.get("cpu.average"), recursos.get("mem.usage"),
            ", %s sessões" % sessoes if sessoes is not None else "", self.dns)]
        for nome, rotulo in PORTAS:
            p = portas.get(nome) or {}
            if not p.get("link"):
                linhas.append("   ➖ %-24s sem cabo/enlace" % rotulo)
                continue
            texto = "   ✅ %-24s %d Mbit/s %s" % (rotulo, p.get("speed") or 0, "full" if p.get("duplex") else "half")
            antes = self.anterior.get(nome)
            if antes:
                segundos = max(agora - antes[0], 0.5)
                desce = (p.get("rx_bytes", 0) - antes[1]) * 8 / segundos / 1e6
                sobe = (p.get("tx_bytes", 0) - antes[2]) * 8 / segundos / 1e6
                if desce >= 0 and sobe >= 0:
                    texto += "   entra %6.2f  sai %6.2f Mbit/s" % (desce, sobe)
            erros = (p.get("rx_errors") or 0) + (p.get("tx_errors") or 0)
            if erros:
                texto += "   ⚠️ %d erros" % erros
            linhas.append(texto)
            self.anterior[nome] = (agora, p.get("rx_bytes", 0), p.get("tx_bytes", 0))
        return {"linhas": linhas, "dmz_de_pe": bool((portas.get("dmz") or {}).get("link"))}


class Tailscale:
    def __init__(self):
        self.linhas = ["… Tailscale: lendo"]
        self.lido = 0.0

    def ler(self):
        if time.monotonic() - self.lido < 15:
            return self.linhas
        self.lido = time.monotonic()
        try:
            dados = json.loads(subprocess.run([TAILSCALE, "status", "--json"], capture_output=True, text=True,
                                              encoding="utf-8", timeout=10, **SEM_JANELA).stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            self.linhas = ["⛔ Tailscale deste PC não respondeu"]
            return self.linhas
        eu = dados.get("Self", {})
        linhas = ["✅ Tailscale: este PC online (%s)" % eu.get("DNSName", "").split(".")[0]]
        saidas = []
        if eu.get("ExitNodeOption") or "0.0.0.0/0" in (eu.get("AllowedIPs") or []):
            saidas.append("este PC")
        for par in (dados.get("Peer") or {}).values():
            nome = par.get("DNSName", "").split(".")[0] or par.get("HostName")
            linhas.append("   %s %s (%s)" % ("✅" if par.get("Online") else "➖", nome,
                                             "online" if par.get("Online") else "offline"))
            if par.get("ExitNodeOption") and par.get("Online"):
                saidas.append(nome)
        linhas.append(("✅ Saída da VPN de casa disponível: " + ", ".join(saidas)) if saidas else
                      "⚠️ Nenhuma saída da VPN de casa aprovada agora (aprovar o A12 no painel do Tailscale)")
        self.linhas = linhas
        return linhas


RODAPE = ("\nCom o PC DESLIGADO continuam: a VPN de casa pelo A12 (saída de reserva, mais lenta), o repasse do ARENA no"
          "\nA12, o ligar-pc (o favorito no celular liga o PC), o sentinela e a telemetria do A12."
          "\nPrecisam do PC LIGADO (ligue pelo favorito antes): webcam do celular, segunda tela, OBS, gravar jogos,"
          "\nÁrea de Trabalho Remota e o ARENA do PC.")


def ligar_cores_do_console():
    """Windows: liga as sequências de controle no console (limpar a tela e voltar ao topo a cada volta)."""
    if os.name != "nt":
        return
    import ctypes
    kernel = ctypes.windll.kernel32
    saida = kernel.GetStdHandle(-11)                       # STD_OUTPUT_HANDLE
    modo = ctypes.c_uint32()
    if kernel.GetConsoleMode(saida, ctypes.byref(modo)):
        kernel.SetConsoleMode(saida, modo.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING


class TesteDeInternet:
    """O teste de banda (scripts/teste_internet.py) numa linha à parte: só quando alguém aperta T."""

    def __init__(self, forti):
        self.forti, self.andamento, self.resultado, self.rodando = forti, "", None, False

    def comecar(self):
        if self.rodando:
            return
        self.rodando = True
        threading.Thread(target=self._rodar, daemon=True, name="teste-internet").start()

    def _rodar(self):
        import teste_internet
        try:
            self.resultado = teste_internet.medir(self.forti.contadores_da_wan,
                                                  aviso=lambda t: setattr(self, "andamento", t))
        finally:
            self.rodando, self.andamento = False, ""

    def linhas(self):
        import teste_internet
        if self.rodando:
            return ["⏳ Teste de internet: " + self.andamento]
        return teste_internet.linhas(self.resultado) or ["Teste de internet: aperte T (gasta uns 300 a 800 MB)"]


def uma_volta(forti, tailscale, grupo, extras=()):
    """Todas as conferências juntas; devolve o texto da tela. `extras`: os blocos de hardware e o teste de internet,
    que se leem sozinhos em segundo plano (aqui só se pega o último resultado)."""
    f_forti = grupo.submit(forti.ler)
    f_repasse = grupo.submit(porta_aberta, A12, 55440)
    f_ligar = grupo.submit(porta_aberta, A12, 8000)
    f_internet = grupo.submit(tempo_ate, "1.1.1.1", 443)
    f_tail = grupo.submit(tailscale.ler)
    forti_lido = f_forti.result()
    repasse, ligar, internet = f_repasse.result(), f_ligar.result(), f_internet.result()
    linhas = ["Infraestrutura da casa   %s   (a cada %d s; feche a janela para sair)" % (
        datetime.now().strftime("%H:%M:%S"), INTERVALO), ""]
    linhas += forti_lido["linhas"]
    linhas.append("✅ Internet: %.0f ms até a Cloudflare" % internet if internet is not None
                  else "⛔ Internet: a Cloudflare (1.1.1.1:443) não respondeu")
    a12 = repasse or ligar
    linhas.append("%s A12 na DMZ (%s)" % ("✅" if a12 else "⛔", A12))
    linhas.append("   %s repasse do ARENA (55440)" % ("✅" if repasse else "➖"))
    linhas.append("   %s endereço de ligar o PC (8000)" % ("✅" if ligar else "➖"))
    if not a12 and forti_lido["dmz_de_pe"]:
        linhas.append("   ⚠️ A DMZ tem enlace, mas o A12 não responde: provável \"rota presa\" (13 e 14/11)."
                      "\n      Conserto: python scripts\\religar_dmz.py")
    linhas += f_tail.result()
    for bloco in extras:
        linhas.append("")
        try:
            linhas += bloco.linhas()
        except Exception as falha:  # noqa: BLE001 - um bloco com defeito não derruba o painel
            linhas.append("(bloco %s com defeito: %s)" % (bloco.__class__.__name__, str(falha)[:60]))
    return "\n".join(linhas)


def tecla():
    """A tecla apertada na janela (minúscula), ou "" (Windows; sem esperar)."""
    if os.name != "nt":
        return ""
    import msvcrt
    if msvcrt.kbhit():
        return msvcrt.getwch().lower()
    return ""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    import hardware_casa
    forti, tailscale = FortiGate(), Tailscale()
    celular = hardware_casa.Celular()
    teste = TesteDeInternet(forti)
    extras = (hardware_casa.PC(), celular, hardware_casa.HardwareDoFortiGate(), teste)
    with ThreadPoolExecutor(max_workers=6) as grupo:
        try:
            if "--uma-vez" in sys.argv:
                for _ in range(50):                   # uma foto: espera o celular, o SSH e o Windows (até ~10 s)
                    if (celular.rapido and celular.estatico and extras[0].video
                            and extras[2].texto != "lendo pelo SSH…"):
                        break
                    time.sleep(0.2)
                print(uma_volta(forti, tailscale, grupo, extras) + "\n" + RODAPE)
                return 0
            ligar_cores_do_console()
            while True:
                inicio = time.monotonic()
                texto = uma_volta(forti, tailscale, grupo, extras)
                sys.stdout.write("\x1b[H\x1b[2J" + texto + "\n" + RODAPE + "\n   [T] teste de internet   [S] sair\n")
                sys.stdout.flush()
                while time.monotonic() - inicio < INTERVALO:  # espera a próxima volta, olhando o teclado
                    apertada = tecla()
                    if apertada == "t":
                        teste.comecar()
                        break
                    if apertada in ("s", "q"):
                        return 0
                    time.sleep(0.1)
        except KeyboardInterrupt:
            return 0
        finally:
            forti.sair()


if __name__ == "__main__":
    sys.exit(main())
