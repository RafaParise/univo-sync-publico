#!/usr/bin/env python3
"""
sentinela_a12.py - roda no Termux do Galaxy A12 (DMZ, 10.0.10.50).

Junta os dois rascunhos de sentinela (térmico e "zero trust" do ADB), adaptados
ao FortiOS 5.4 do 60D (o que mudou está em docs/decisoes-provisionamento.md):
  - o 5.4 não tem token de API: login de sessão com a conta parise_core_api, que só
    mexe no firewall e só aceita login vindo deste IP;
  - liga/desliga a REGRA 2 (PC_PARA_A12_ADB) com status enable/disable; não apaga nada;
  - certificado do FortiGate preso pela impressão SHA-256 (nada de verify=False cego);
  - nenhuma senha no código: tudo vem de ~/.parise-sentinela.env.

No A12: copie sentinela_a12.py e fortigate_api.py para a mesma pasta e crie
~/.parise-sentinela.env com FORTIGATE_IP=10.0.10.1, FORTIGATE_CERT_SHA256,
FORTIGATE_API_USUARIO e FORTIGATE_API_SENHA (os mesmos valores do .env do PC).

  python sentinela_a12.py              vigia sem parar
  python sentinela_a12.py --uma-vez    uma leitura e sai
  python sentinela_a12.py --liberar    religa a regra do ADB (depois de um bloqueio)
  python sentinela_a12.py --teste-api  desliga e religa a regra (testa a conta)

Sem o ~/.parise-sentinela.env (o A12 ainda fora da DMZ, 12/11/2026), roda em modo "so telemetria": mede e guarda as
amostras do aparelho (amostrar), avisa uma vez que o FortiGate fica de fora e nao tenta falar com ele. Assim a senha
da API so vai para o celular quando ele estiver na DMZ e puder alcancar o aparelho. No A12 o comando e' `sentinela`
(ligar, desligar, estado, registro, amostras), instalado pelo PC com scripts/instalar_sentinela_a12.py.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fortigate_api import ErroAPI, FortiAPI  # noqa: E402

CONF = Path.home() / ".parise-sentinela.env"
REGRA_ADB = 2                 # PC_PARA_A12_ADB
PC_AUTORIZADO = "10.0.20.100"
LIMITE_C, HISTERESE_C = 45.0, 3.0
# Telemetria sutil (11/11/2026): uma linha JSON por volta do vigia, so com a saude deste aparelho (temperatura,
# bateria, memoria, tempo ligado, ping ao gateway). Fica em /sdcard (o PC le pelo cabo, scripts/telemetria.py)
# ou, sem o acesso ao /sdcard, na pasta do Termux (o Qwen do A12 le ali). Nunca nada de outro aparelho.
AMOSTRAS_SDCARD = Path("/sdcard/parise-sync/telemetria/amostras.jsonl")
AMOSTRAS_HOME = Path.home() / "telemetria" / "amostras.jsonl"
MAX_AMOSTRAS = 2000
AMOSTRA_A_CADA_S = 60         # o vigia da por volta a cada 10 s (barato: sysfs e /proc); a amostra, com o termux-api
                              # e um ping, so a cada minuto, para nao pesar no aparelho (4 GB, sempre no limite)


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def avisar(titulo, texto):
    """Notificação no celular, se o Termux:API estiver instalado."""
    if shutil.which("termux-notification"):
        subprocess.run(["termux-notification", "--title", titulo, "--content", texto], timeout=10)


def ler_conf(caminho):
    conf = {}
    if caminho.exists():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.strip().startswith("#"):
                k, v = linha.split("=", 1)
                conf[k.strip()] = v.strip()
    return conf


# ---------- temperatura ----------
def temperatura():
    """Maior temperatura plausível dos sensores da CPU (sysfs); senão a da bateria. None se não der."""
    leituras, cpu = [], []
    for zona in Path("/sys/class/thermal").glob("thermal_zone*"):
        try:
            v = float((zona / "temp").read_text().strip())
            tipo = (zona / "type").read_text().strip().lower()
        except (OSError, ValueError):
            continue
        v = v / 1000 if v > 1000 else v
        if 0 < v < 120:
            leituras.append(v)
            if "cpu" in tipo or "soc" in tipo:
                cpu.append(v)
    if cpu or leituras:
        return max(cpu or leituras)
    if shutil.which("termux-battery-status"):
        try:
            saida = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=15).stdout
            return float(json.loads(saida)["temperature"])
        except (ValueError, KeyError, subprocess.TimeoutExpired):
            pass
    return None


def bateria():
    """Porcentagem da bateria pelo Termux:API, ou None."""
    if shutil.which("termux-battery-status"):
        try:
            saida = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=15).stdout
            return int(json.loads(saida)["percentage"])
        except (ValueError, KeyError, subprocess.TimeoutExpired):
            pass
    return None


def wifi():
    """O Wi-Fi deste aparelho pelo Termux:API: {"ip": ..., "rssi": ...} ou {} (sem nome de rede nem MAC: nao
    interessam, e o Android 12 ja os esconde)."""
    if shutil.which("termux-wifi-connectioninfo"):
        try:
            saida = subprocess.run(["termux-wifi-connectioninfo"], capture_output=True, text=True, timeout=15).stdout
            dados = json.loads(saida)
            return {"ip": dados.get("ip") or None, "rssi": dados.get("rssi")}
        except (ValueError, subprocess.TimeoutExpired):
            pass
    return {}


def gateway_provavel(conf, wifi_ip=None):
    """O gateway a medir. O Android 12 nega /proc/net/route ao Termux (12/11/2026), entao: o FortiGate da conf
    (na DMZ), senao o /proc/net/route (quando o Android deixa), senao o .1 da rede do Wi-Fi."""
    if conf.get("FORTIGATE_IP"):
        return conf["FORTIGATE_IP"]
    try:
        for linha in Path("/proc/net/route").read_text().splitlines()[1:]:
            campos = linha.split()
            if len(campos) > 2 and campos[1] == "00000000":
                return hex_para_ip(campos[2])
    except (OSError, ValueError):
        pass
    if wifi_ip and wifi_ip.count(".") == 3:
        return wifi_ip.rsplit(".", 1)[0] + ".1"
    return None


def ping_gateway(conf=None, wifi_ip=None):
    """Latência (ms) ao gateway provável; None se não der."""
    alvo = gateway_provavel(conf or {}, wifi_ip)
    if not alvo:
        return None
    try:
        saida = subprocess.run(["ping", "-c", "1", "-W", "1", alvo], capture_output=True, text=True,
                               timeout=5).stdout
        m = re.search(r"time=([\d.]+)", saida)
        return float(m.group(1)) if m else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def tempo_ligado_h():
    """Horas desde que o aparelho ligou, pelo relógio de boot (o /proc/uptime é negado ao Termux no Android 12)."""
    try:
        return round(time.clock_gettime(time.CLOCK_BOOTTIME) / 3600, 1)
    except (AttributeError, OSError):
        return None


def amostrar(t, conf=None):
    """Guarda a amostra desta volta (e apara o arquivo em MAX_AMOSTRAS linhas)."""
    rede = wifi()
    amostra = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "temp_c": None if t is None else round(t, 1),
               "bateria_pct": bateria(), "ping_gateway_ms": ping_gateway(conf, rede.get("ip")),
               "wifi_rssi_dbm": rede.get("rssi"), "ligado_h": tempo_ligado_h()}
    try:
        for linha in Path("/proc/meminfo").read_text().splitlines():
            if linha.startswith("MemAvailable"):
                amostra["mem_livre_mb"] = int(linha.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    for arquivo in (AMOSTRAS_SDCARD, AMOSTRAS_HOME):
        try:
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            with arquivo.open("a", encoding="utf-8") as f:
                f.write(json.dumps(amostra, ensure_ascii=False) + "\n")
            linhas = arquivo.read_text(encoding="utf-8").splitlines()
            if len(linhas) > MAX_AMOSTRAS:
                arquivo.write_text("\n".join(linhas[-MAX_AMOSTRAS:]) + "\n", encoding="utf-8")
            return arquivo
        except OSError:
            continue
    return None


# ---------- conexões na porta do ADB ----------
def hex_para_ip(h):
    """Endereço de /proc/net/tcp (hex, little-endian) para texto."""
    if len(h) == 8:
        return ".".join(str(int(h[i:i + 2], 16)) for i in (6, 4, 2, 0))
    if h.upper().startswith("0000000000000000FFFF0000"):
        return hex_para_ip(h[-8:])
    return "ipv6:" + h.lower()


def ips_na_porta(texto, porta=5555):
    """IPs remotos com conexão ESTABELECIDA na porta local (texto de /proc/net/tcp ou tcp6)."""
    ips = set()
    for linha in texto.splitlines()[1:]:
        c = linha.split()
        if len(c) < 4 or c[3] != "01":           # 01 = ESTABLISHED
            continue
        if int(c[1].split(":")[1], 16) == porta:
            ips.add(hex_para_ip(c[2].split(":")[0]))
    return ips


def conexoes_adb():
    """Conjunto de IPs no ADB, ou None se o Android não deixar ler (Android 10+ sem root)."""
    ips, lido = set(), False
    for arq in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            ips |= ips_na_porta(Path(arq).read_text())
            lido = True
        except OSError:
            pass
    return ips if lido else None


# ---------- FortiGate ----------
def regra_adb(conf, ligar):
    """Liga ou desliga a regra do ADB no FortiGate. Levanta ErroAPI se falhar."""
    api = FortiAPI(conf.get("FORTIGATE_IP", "10.0.10.1"), impressao=conf["FORTIGATE_CERT_SHA256"])
    api.login(conf["FORTIGATE_API_USUARIO"], conf["FORTIGATE_API_SENHA"])
    try:
        api.ajustar(f"firewall/policy/{REGRA_ADB}", {"status": "enable" if ligar else "disable"})
    finally:
        api.logout()


def vigiar(conf, intervalo, uma_vez=False, so_telemetria=False):
    adb_ligado, travado = True, False   # travado = bloqueio por intruso; só sai com --liberar
    aviso_proc = False
    ultima_amostra = None
    if so_telemetria:
        log("Modo so telemetria: sem a conf do FortiGate, este vigia mede e guarda as amostras, e nao mexe em regra.")
    while True:
        t = temperatura()
        ips = conexoes_adb()
        log(f"temperatura {t if t is None else round(t, 1)} C | ADB {sorted(ips) if ips is not None else 'sem acesso'}")
        if ultima_amostra is None or time.monotonic() - ultima_amostra >= AMOSTRA_A_CADA_S:
            amostrar(t, conf)
            ultima_amostra = time.monotonic()
        if ips is None and not aviso_proc:
            log("Aviso: o Android não deixa ler /proc/net/tcp sem root; o vigia de ADB fica desligado.")
            aviso_proc = True
        if so_telemetria:
            if uma_vez:
                return
            time.sleep(intervalo)
            continue
        try:
            intrusos = sorted(ip for ip in (ips or ()) if ip not in (PC_AUTORIZADO, "127.0.0.1"))
            if intrusos and not travado:
                log(f"ALERTA: ADB acessado por {intrusos}. Desligando a regra do ADB no FortiGate.")
                avisar("Sentinela A12", f"ADB acessado por {', '.join(intrusos)}; regra desligada")
                regra_adb(conf, False)
                adb_ligado, travado = False, True
            elif t is not None and t > LIMITE_C and adb_ligado:
                log(f"Temperatura {t:.1f} C acima de {LIMITE_C}. Desligando o ADB.")
                regra_adb(conf, False)
                adb_ligado = False
            elif t is not None and t <= LIMITE_C - HISTERESE_C and not adb_ligado and not travado:
                log("Temperatura normal. Religando o ADB.")
                regra_adb(conf, True)
                adb_ligado = True
        except (ErroAPI, KeyError) as e:
            log(f"Falha ao falar com o FortiGate: {e}")
        if uma_vez:
            return
        time.sleep(intervalo)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Sentinela do A12 (temperatura e ADB).")
    ap.add_argument("--uma-vez", action="store_true")
    ap.add_argument("--liberar", action="store_true", help="religa a regra do ADB")
    ap.add_argument("--teste-api", action="store_true", help="desliga e religa a regra")
    ap.add_argument("--intervalo", type=int, default=10)
    ap.add_argument("--conf", default=str(CONF))
    args = ap.parse_args(argv)
    conf = ler_conf(Path(args.conf))
    faltam = [k for k in ("FORTIGATE_CERT_SHA256", "FORTIGATE_API_USUARIO", "FORTIGATE_API_SENHA") if not conf.get(k)]
    if faltam and (args.liberar or args.teste_api):
        print(f"Faltam em {args.conf}: {', '.join(faltam)}")
        return 1
    if faltam:
        log(f"Sem {', '.join(faltam)} em {args.conf}: o FortiGate fica de fora (modo so telemetria).")
    try:
        if args.liberar or args.teste_api:
            if args.teste_api:
                regra_adb(conf, False)
                log("regra do ADB desligada")
            regra_adb(conf, True)
            log("regra do ADB ligada")
            return 0
    except ErroAPI as e:
        log(f"Falhou: {e}")
        return 3
    log("Sentinela iniciado.")
    vigiar(conf, args.intervalo, args.uma_vez, so_telemetria=bool(faltam))
    return 0


if __name__ == "__main__":
    sys.exit(main())
