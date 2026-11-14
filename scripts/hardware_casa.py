# -*- coding: utf-8 -*-
"""
hardware_casa.py - o hardware e os sensores dos aparelhos da casa, para o painel "Infraestrutura da casa" (14/11/2026).

Pedido do Rafael: "deve ter o hardware dos aparelhos conectados, até mesmo o FortiGate, assim como o ARENA que mostra
tudo e todos os sensores do celular e do PC, como temperatura [...], consumo de energia".

O que cada aparelho deixa ler (conferido em 14/11/2026; o que não existe não aparece, nada é inventado):
  PC Ryzen     processador, núcleos, carga, RAM, vídeo, disco e tempo ligado, pelo próprio Windows (sem programa
               extra). Temperatura e consumo: o Windows deste PC não tem zona térmica nem medidor de energia; vêm do
               LibreHardwareMonitor, SE ele estiver aberto com o servidor web ligado (http://127.0.0.1:8085/data.json).
               Ele precisa do driver PawnIO (de kernel): instalar é decisão do Rafael (docs/DESEMPENHO-E-ACESSO-REMOTO.md).
  Galaxy A12   modelo, processador, RAM, armazenamento e bateria pelo leitor do ARENA (servidor/adb_aparelho.py), e a
               cada 10 s, pelo adb sem fio: temperaturas do serviço térmico do Android (processador, bateria, rádio),
               nível, corrente e voltagem da bateria (a potência que entra ou sai da bateria).
  FortiGate    modelo, CPU, RAM e flash (SSH, "get hardware status", uma vez) e o tempo ligado. O 60D NÃO tem sensor
               de temperatura nem de energia ("execute sensor list" nem existe no FortiOS dele).
Leve: cada leitor roda na sua linha, no seu ritmo; o painel só lê o último resultado guardado (nunca espera o adb).
Nada de MAC, número de série ou nome de conta na tela.
"""
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

PASTA = Path(__file__).resolve().parent
ARENA_SERVIDOR = Path(r"C:\Projetos\arena-console\servidor")
SEM_JANELA = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
A12_SEM_FIO = "192.168.18.4:5555"
LHM = "http://127.0.0.1:8085/data.json"


def _gb(bytes_):
    return bytes_ / (1 << 30)


def _duracao(segundos):
    segundos = int(segundos)
    dias, resto = divmod(segundos, 86400)
    return ("%d d " % dias if dias else "") + "%d h %02d min" % (resto // 3600, resto % 3600 // 60)


# ---------------------------------------------------------------- PC (Windows) ----------------------------------------
class _FILETIME(ctypes.Structure):
    _fields_ = [("baixo", ctypes.c_uint32), ("alto", ctypes.c_uint32)]

    def valor(self):
        return (self.alto << 32) | self.baixo


class _MEMORIA(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64)]


def _registro(caminho, nome):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, caminho) as chave:
            return str(winreg.QueryValueEx(chave, nome)[0]).strip()
    except OSError:
        return ""


def _pelo_windows():
    """(núcleos físicos, [placas de vídeo]) pelo próprio Windows (CIM), uma vez. O registro guarda placas que já
    saíram do PC (14/11: uma GeForce 210 antiga aparecia), então vale a lista dos aparelhos presentes."""
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "(Get-CimInstance Win32_Processor | Measure-Object NumberOfCores -Sum).Sum; "
                        "Get-CimInstance Win32_VideoController | ForEach-Object Name"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, **SEM_JANELA)
    linhas = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    fisicos = int(linhas[0]) if linhas and linhas[0].isdigit() else None
    placas = [l for l in linhas[1:] if "virtual" not in l.lower() and "remote" not in l.lower()]
    return fisicos, placas


def br(numero, casas=1):
    """Número com vírgula, como se escreve no Brasil."""
    return ("%%.%df" % casas % numero).replace(".", ",")


class PC:
    def __init__(self):
        self.cpu = _registro(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString")
        self.nucleos = os.cpu_count() or 0
        self.fisicos, self.video = None, []
        self._tempos = None
        self.lhm_ok, self.lhm_tentado = False, 0.0
        if os.name == "nt":
            threading.Thread(target=self._ler_windows, daemon=True, name="pc-cim").start()

    def _ler_windows(self):
        try:
            self.fisicos, self.video = _pelo_windows()
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

    def _carga(self):
        ocioso, kernel, usuario = _FILETIME(), _FILETIME(), _FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(ocioso), ctypes.byref(kernel), ctypes.byref(usuario)):
            return None
        agora = (ocioso.valor(), kernel.valor() + usuario.valor())
        antes, self._tempos = self._tempos, agora
        if not antes or agora[1] == antes[1]:
            return None
        return max(0.0, 100.0 * (1 - (agora[0] - antes[0]) / (agora[1] - antes[1])))

    def _sensores(self):
        """[(aparelho, tipo, sensor, valor)] do LibreHardwareMonitor, se ele estiver aberto (tenta de novo a cada 30 s
        quando não estava)."""
        if not self.lhm_ok and time.monotonic() - self.lhm_tentado < 30:
            return None
        self.lhm_tentado = time.monotonic()
        try:
            with urllib.request.urlopen(LHM, timeout=0.6) as resposta:
                arvore = json.loads(resposta.read(2_000_000).decode("utf-8", "replace"))
        except (OSError, ValueError):
            self.lhm_ok = False
            return None
        self.lhm_ok = True
        achados = []

        def andar(no, aparelho="", grupo=""):
            filhos = no.get("Children") or []
            texto = no.get("Text", "")
            if not filhos and grupo in ("Temperatures", "Powers") and no.get("Value"):
                achados.append((aparelho, grupo, texto, no["Value"]))
            for filho in filhos:
                if texto in ("Temperatures", "Powers", "Load", "Clocks", "Voltages", "Fans", "Data", "Throughput"):
                    andar(filho, aparelho, texto)
                else:
                    andar(filho, texto if (filho.get("Children") and not grupo) else aparelho, grupo)
        andar(arvore)
        return achados

    def linhas(self):
        nucleos = ("%d núcleos (%d lógicos)" % (self.fisicos, self.nucleos) if self.fisicos
                   else "%d núcleos lógicos" % self.nucleos)
        saida = ["🖥️  PC: %s, %s%s" % (self.cpu or "processador ?", nucleos,
                                       ("; vídeo " + ", ".join(self.video)) if self.video else "")]
        carga = self._carga() if os.name == "nt" else None
        memoria = _MEMORIA()
        memoria.dwLength = ctypes.sizeof(_MEMORIA)
        ram = ""
        if os.name == "nt" and ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memoria)):
            ram = "RAM %s de %s GB (%d%%)" % (br(_gb(memoria.ullTotalPhys - memoria.ullAvailPhys)),
                                              br(_gb(memoria.ullTotalPhys)), memoria.dwMemoryLoad)
        disco = shutil.disk_usage("C:\\")
        ligado = ctypes.windll.kernel32.GetTickCount64() / 1000 if os.name == "nt" else 0
        saida.append("   processador %s   %s   disco C: %.0f GB livres   ligado há %s" % (
            ("%.0f%%" % carga) if carga is not None else "…", ram, _gb(disco.free), _duracao(ligado)))
        sensores = self._sensores()
        if sensores is None:
            saida.append("   temperatura e consumo: abra o LibreHardwareMonitor com o servidor web (porta 8085)")
        else:
            temps = [s for s in sensores if s[1] == "Temperatures"]
            pot = [s for s in sensores if s[1] == "Powers" and ("Package" in s[2] or "GPU" in s[2] or "Total" in s[2])]
            if temps:
                saida.append("   🌡️ " + "   ".join("%s %s" % (s[2], s[3]) for s in temps[:6]))
            if pot:
                saida.append("   ⚡ " + "   ".join("%s %s" % (s[2], s[3]) for s in pot[:4]))
        return saida


# ---------------------------------------------------------------- Galaxy A12 (adb) ------------------------------------
LEITURA_RAPIDA = ("dumpsys battery; echo @@; dumpsys thermalservice | sed -n '/Current temperatures from HAL/,"
                  "/Current cooling/p'; echo @@; cat /proc/meminfo | head -3")


class Celular:
    """Lê o A12 numa linha à parte: o rápido a cada 10 s, o completo (leitor do ARENA) a cada 5 min."""

    def __init__(self, serie=A12_SEM_FIO):
        self.serie = serie
        self.estatico, self.rapido, self.erro = [], {}, "lendo…"
        self._adb = shutil.which("adb")
        threading.Thread(target=self._laco, daemon=True, name="a12").start()

    def _shell(self, comando, espera=15):
        r = subprocess.run([self._adb, "-s", self.serie, "shell", comando], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=espera, **SEM_JANELA)
        return r.stdout

    def _ler_estatico(self):
        if str(ARENA_SERVIDOR) not in sys.path:
            sys.path.insert(0, str(ARENA_SERVIDOR))
        import adb_aparelho
        resposta = adb_aparelho.procurar(self.serie)
        quero = ("Modelo", "Android", "Processador (SoC)", "Núcleos", "Placa de vídeo", "Armazenamento",
                 "Saúde, pelo Android", "Índice de saúde da Samsung (ASOC)")
        self.estatico = [(l[0], str(l[1])) for g in resposta.get("painel") or [] for l in g.get("linhas", [])
                         if l[0] in quero]

    def _ler_rapido(self):
        texto = self._shell(LEITURA_RAPIDA)
        bateria, termica, memoria = (texto.split("@@") + ["", "", ""])[:3]
        pares = dict(re.findall(r"^\s*([A-Za-z ]+):\s*(-?\d+)\s*$", bateria, re.M))
        temps = {n: float(v) for v, n in re.findall(r"mValue=([\d.]+), mType=\d+, mName=(\w+)", termica)
                 if float(v) > 0}
        mem = dict(re.findall(r"^(\w+):\s+(\d+) kB", memoria, re.M))
        self.rapido = {"nivel": pares.get("level"), "corrente_ma": pares.get("current now"),
                       "volts": int(pares["voltage"]) / 1000 if pares.get("voltage") else None,
                       "carregando": pares.get("status") == "2", "temps": temps,
                       "ram": (int(mem["MemTotal"]), int(mem.get("MemAvailable", 0))) if "MemTotal" in mem else None}

    def _laco(self):
        ultimo_estatico = 0.0
        while True:
            try:
                if not self._adb:
                    self.erro = "sem o adb neste PC"
                elif "%s\tdevice" % self.serie not in subprocess.run(
                        [self._adb, "devices"], capture_output=True, text=True, timeout=10, **SEM_JANELA).stdout:
                    subprocess.run([self._adb, "connect", self.serie], capture_output=True, timeout=10, **SEM_JANELA)
                    self.erro = "depuração sem fio desligada (reconectando)"
                else:
                    self._ler_rapido()
                    if time.monotonic() - ultimo_estatico > 300 or not self.estatico:
                        self._ler_estatico()
                        ultimo_estatico = time.monotonic()
                    self.erro = ""
            except Exception as falha:  # noqa: BLE001 - o painel nunca cai pelo celular
                self.erro = "não li o celular (%s)" % str(falha)[:60]
            time.sleep(10)

    def linhas(self):
        saida = ["📱 Galaxy A12" + (": " + self.erro if self.erro and not self.rapido else "")]
        fixo = dict(self.estatico)
        if fixo:
            saida.append("   %s, %s; %s" % (fixo.get("Processador (SoC)", "?"), fixo.get("Núcleos", ""),
                                           fixo.get("Armazenamento", "")))
        r = self.rapido
        if r:
            partes = []
            if r.get("ram"):
                total, livre = r["ram"]
                partes.append("RAM %s de %s GB" % (br((total - livre) / 1048576), br(total / 1048576)))
            if r.get("nivel"):
                partes.append("bateria %s%%%s" % (r["nivel"], " carregando" if r["carregando"] else ""))
            if r.get("corrente_ma") and r.get("volts"):
                ma = int(r["corrente_ma"])
                watts = abs(ma) / 1000 * r["volts"]
                partes.append("%+d mA (%s W %s)" % (ma, br(watts, 2), "entrando na bateria" if ma >= 0
                                                    else "saindo da bateria"))
            saida.append("   " + "   ".join(partes))
            nomes = {"AP": "processador", "BAT": "bateria", "PA": "rádio", "LRP": "placa", "USB": "USB"}
            temps = ["%s %s °C" % (nomes.get(n, n), br(v)) for n, v in r.get("temps", {}).items() if n in nomes]
            if temps:
                saida.append("   🌡️ " + "   ".join(temps))
            if self.erro:
                saida.append("   (%s)" % self.erro)
        return saida


# ---------------------------------------------------------------- FortiGate (SSH, uma vez) ----------------------------
class HardwareDoFortiGate:
    def __init__(self):
        self.texto, self.ligado_em = "lendo pelo SSH…", None
        threading.Thread(target=self._ler, daemon=True, name="fortigate-ssh").start()

    def _ler(self):
        try:
            sys.path.insert(0, str(PASTA))
            import fortios_console as fc
            from provisionar_fortigate import ENV, ler_env
            from provisionar_rede import CanalSSH
            env = ler_env(ENV)
            con = fc.Console(CanalSSH(env.get("FORTIGATE_IP", "10.0.20.1"), "admin", env["ADMIN_SENHA"]), pausa=1.0)
            try:
                con.acordar(tentativas=5)
                hw = con.comando("get hardware status", limite=15)
                perf = con.comando("get system performance status", limite=15)
            finally:
                con.fechar()
            campos = dict(re.findall(r"^([A-Za-z ]+):\s*(.+?)\s*$", hw, re.M))
            self.texto = "%s, %s (%s CPU), RAM %s, flash %s" % (
                campos.get("Model name", "?"), campos.get("CPU", "?"), campos.get("Number of CPUs", "?"),
                campos.get("RAM", "?"), campos.get("Compact Flash", "?").split(" /dev")[0])
            m = re.search(r"Uptime:\s*(\d+) days?,\s*(\d+) hours?,\s*(\d+) minutes?", perf)
            if m:
                self.ligado_em = time.time() - (int(m[1]) * 86400 + int(m[2]) * 3600 + int(m[3]) * 60)
        except Exception as falha:  # noqa: BLE001 - só leitura extra
            self.texto = "hardware não lido pelo SSH (%s)" % str(falha)[:60]

    def linhas(self):
        ligado = ("; ligado há %s" % _duracao(time.time() - self.ligado_em)) if self.ligado_em else ""
        return ["🛡️  FortiGate: %s%s" % (self.texto, ligado),
                "   sem sensor de temperatura nem de energia no 60D (o FortiOS dele não tem)"]
