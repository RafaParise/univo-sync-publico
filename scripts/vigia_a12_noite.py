# -*- coding: utf-8 -*-
r"""Vigia da noite do Galaxy A12 (14/11/2026, pedido do Rafael: "um vigia que mantém a tela acesa para ele ficar em
DMZ e em depuração Wi-Fi a noite toda").

Por que existe: a telemetria da bancada mostrava o A12 da DMZ (10.0.10.50) disponível só 42% do tempo. Com a tela
apagada o Android economiza (Wi-Fi e rede com fio em descanso), a depuração sem fio cai e o repasse do ARENA some.

O que faz, de minuto em minuto, até a hora de parar (--ate, padrão 07:30):
  1. reconecta a depuração sem fio (adb connect) se ela caiu;
  2. na primeira vez, guarda os ajustes do celular e liga "ficar acordado enquanto carrega" (stay_on_while_plugged_in)
     e o brilho no mínimo (a tela acesa a noite toda gasta e marca a tela; o mínimo basta);
  3. se a tela apagou, acende (KEYCODE_WAKEUP; o bloqueio continua: ninguém mexe no celular);
  4. anota: bateria e se carrega, a rede da DMZ (eth0 10.0.10.50), a do Wi-Fi e as portas do ARENA (8777) e do repasse
     (55440) escutando.
No fim, devolve os ajustes do celular como estavam. Bateria abaixo de 20% (mesmo no cabo, que nem sempre vence a
tela acesa): devolve os ajustes e deixa a tela apagar; volta a ajustar quando a bateria sobe.

Tudo escondido: nenhum comando abre janela (CREATE_NO_WINDOW), porque a tarefa roda sem console.
Registro: data/telemetria/vigia-a12-AAAA-MM-DD.jsonl (fora do git) e o resumo memoria/telemetria/VIGIA-A12.md, que o
Hermes, o Qwen e o Claude leem junto com o RESUMO.md da telemetria.

Uso:
    pythonw scripts\vigia_a12_noite.py [--ate 07:30] [--endereco 192.168.18.4:5555]
    python  scripts\vigia_a12_noite.py --uma-vez          (uma rodada só, para conferir)
"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "data" / "telemetria"
RESUMO = RAIZ / "memoria" / "telemetria" / "VIGIA-A12.md"
GUARDADO = DADOS / "vigia-a12-ajustes-antes.json"
SEM_JANELA = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
ENDERECOS = ["192.168.18.4:5555"]          # o A12 na rede de casa (Wi-Fi); a DMZ (eth0) o PC nao alcanca por adb
PORTA_ARENA, PORTA_REPASSE = 8777, 55440
BATERIA_MINIMA = 20                      # abaixo disso o vigia para de forcar a tela, mesmo no cabo
AJUSTES = [("global", "stay_on_while_plugged_in"), ("system", "screen_brightness"),
           ("system", "screen_brightness_mode")]


def argumento(nome, padrao):
    if nome in sys.argv:
        i = sys.argv.index(nome)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return padrao


def adb(*args, serie=None, segundos=20):
    programa = shutil.which("adb")
    if not programa:
        return None
    comando = [programa] + (["-s", serie] if serie else []) + list(args)
    try:
        r = subprocess.run(comando, capture_output=True, text=True, timeout=segundos, errors="replace", **SEM_JANELA)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout


def aparelho():
    """A serie do A12 conectado (reconecta pelo Wi-Fi se precisar), ou None."""
    for tentativa in range(2):
        lista = adb("devices") or ""
        for endereco in ENDERECOS:
            if re.search(re.escape(endereco) + r"\s+device", lista):
                return endereco
        usb = re.findall(r"^(\S+)\s+device$", lista, re.M)
        if usb:
            return usb[0]
        if tentativa == 0:
            for endereco in ENDERECOS:
                adb("connect", endereco, segundos=15)
    return None


def shell(serie, comando, segundos=20):
    return (adb("shell", comando, serie=serie, segundos=segundos) or "").strip()


def guardar_e_ajustar(serie):
    """Guarda os ajustes de antes (uma vez por noite) e liga o acordado com o brilho no minimo."""
    if not GUARDADO.exists():
        antes = {"%s/%s" % (t, n): shell(serie, "settings get %s %s" % (t, n)) for t, n in AJUSTES}
        GUARDADO.write_text(json.dumps(antes, ensure_ascii=False), encoding="utf-8")
    shell(serie, "settings put global stay_on_while_plugged_in 7")     # tomada, USB e sem fio
    brilho = shell(serie, "settings get system screen_brightness")
    if not brilho.isdigit() or int(brilho) > 5:                         # so baixa; brilho menor fica como esta
        shell(serie, "settings put system screen_brightness_mode 0")
        shell(serie, "settings put system screen_brightness 5")


def devolver(serie):
    """Os ajustes do celular de volta como estavam antes da noite."""
    if not GUARDADO.exists() or not serie:
        return False
    antes = json.loads(GUARDADO.read_text(encoding="utf-8"))
    for chave, valor in antes.items():
        tabela, nome = chave.split("/", 1)
        if valor in ("", "null"):
            shell(serie, "settings delete %s %s" % (tabela, nome))
        else:
            shell(serie, "settings put %s %s %s" % (tabela, nome, valor))
    GUARDADO.unlink()
    return True


def portas_escutando(serie):
    texto = shell(serie, "cat /proc/net/tcp /proc/net/tcp6")
    abertas = set()
    for linha in texto.splitlines():
        partes = linha.split()
        if len(partes) > 3 and partes[3] == "0A" and ":" in partes[1]:
            abertas.add(int(partes[1].rsplit(":", 1)[1], 16))
    return {"arena_8777": PORTA_ARENA in abertas, "repasse_55440": PORTA_REPASSE in abertas}


ESCURO = "--escuro" in sys.argv
TELA_APAGADA = Path(r"C:\Android Embeeded\scripts\tela-apagada.py")
RESPEITO_S = 15 * 60          # acendeu com a mao (dois toques, volume): o vigia espera 15 min para escurecer de novo


def tela_apagada(acao):
    """Roda o tela-apagada.py do Android Embeeded (camada preta + brilho 0, sem bloquear; memoria/TELA-APAGADA.md)."""
    subprocess.run([sys.executable, str(TELA_APAGADA), acao], capture_output=True, timeout=90, **SEM_JANELA)


def manter_escura(serie):
    """--escuro (14/11/2026, pedido do Rafael: "desligar a tela mas continuar em depuracao Wi-Fi"): a tela fica escura
    e o aparelho acordado (o tela-apagada.py conta uso a cada 5 s). Desligar o painel de verdade NAO: em 04/11 os dois
    jeitos deixaram a tela preta sem saida ou o toque morto (memoria/TELA-APAGADA.md do Android Embeeded). Se a camada
    sumiu sozinha, escurece de novo; se o Rafael acendeu com a mao, respeita por RESPEITO_S. Devolve se ficou escura."""
    if shell(serie, "dumpsys SurfaceFlinger 2>/dev/null | grep -c tela-preta") not in ("", "0"):
        return True
    ultima = shell(serie, "tail -n 1 /data/local/tmp/tela-vigia.historico 2>/dev/null")
    m = re.search(r"-> (\d\d):(\d\d):(\d\d) acendeu: (\w+)", ultima)
    if m and m.group(4) in ("toques", "volume", "energia", "alarme", "chamada"):
        quando = dt.datetime.now().replace(hour=int(m[1]), minute=int(m[2]), second=int(m[3]), microsecond=0)
        if quando > dt.datetime.now():
            quando -= dt.timedelta(days=1)
        if (dt.datetime.now() - quando).total_seconds() < RESPEITO_S:
            return False
    tela_apagada("apagar")
    return shell(serie, "dumpsys SurfaceFlinger 2>/dev/null | grep -c tela-preta") not in ("", "0")


def rodada(forcar_tela=True):
    agora = dt.datetime.now()
    amostra = {"quando": agora.isoformat(timespec="seconds")}
    serie = aparelho()
    amostra["adb"] = serie
    if not serie:
        return amostra
    bateria = shell(serie, "dumpsys battery")
    nivel = re.search(r"level: (\d+)", bateria)
    carrega = re.search(r"(AC|USB|Wireless) powered: true", bateria)
    amostra["bateria_pct"] = int(nivel.group(1)) if nivel else None
    amostra["carregando"] = bool(carrega)
    energia = shell(serie, "dumpsys power | grep -m1 mWakefulness=")
    amostra["tela"] = energia.split("=", 1)[-1] if "=" in energia else energia
    pct = amostra["bateria_pct"]
    if pct is not None and pct < BATERIA_MINIMA:
        # O cabo USB do PC nem sempre vence a tela acesa (14/11: 49% -> 48% carregando): abaixo do minimo, os ajustes
        # voltam ao normal e a tela pode apagar. Celular descarregado ate desligar sai da DMZ de vez.
        amostra["poupando"] = devolver(serie) or not GUARDADO.exists()
    elif forcar_tela and (amostra["carregando"] or (pct or 0) >= BATERIA_MINIMA):
        guardar_e_ajustar(serie)
        if amostra["tela"] != "Awake":
            shell(serie, "input keyevent KEYCODE_WAKEUP")
            amostra["acendeu"] = True
        if ESCURO:
            amostra["escura"] = manter_escura(serie)
    redes = shell(serie, "ip -4 addr")
    amostra["dmz_eth0"] = "10.0.10.50" in redes
    wifi = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/\d+[^\n]*wlan0", redes)
    amostra["wifi"] = wifi.group(1) if wifi else None
    amostra.update(portas_escutando(serie))
    return amostra


def anotar(amostra):
    DADOS.mkdir(parents=True, exist_ok=True)
    arquivo = DADOS / ("vigia-a12-%s.jsonl" % amostra["quando"][:10])
    with open(arquivo, "a", encoding="utf-8") as saida:
        saida.write(json.dumps(amostra, ensure_ascii=False) + "\n")
    linhas = []
    try:
        linhas = [json.loads(l) for l in arquivo.read_text(encoding="utf-8").splitlines() if l.strip()]
    except ValueError:
        pass
    total = len(linhas) or 1
    def pct(chave):
        return round(100 * sum(1 for l in linhas if l.get(chave)) / total)
    RESUMO.parent.mkdir(parents=True, exist_ok=True)
    RESUMO.write_text("\n".join([
        "# Vigia da noite do A12 (scripts/vigia_a12_noite.py)",
        "",
        "Atualizado em %s, %d rodadas de minuto em minuto. Dados em `data/telemetria/vigia-a12-*.jsonl`." % (
            amostra["quando"], len(linhas)),
        "",
        "- depuração sem fio conectada: %d%% das rodadas" % pct("adb"),
        "- na DMZ (eth0 10.0.10.50): %d%%" % pct("dmz_eth0"),
        "- ARENA escutando na 8777: %d%%; repasse na 55440: %d%%" % (pct("arena_8777"), pct("repasse_55440")),
        "- aparelho acordado: %d%% (o vigia acordou %d vez(es)); tela escura (--escuro): %d%%" % (
            round(100 * sum(1 for l in linhas if l.get("tela") == "Awake") / total), sum(1 for l in linhas if l.get("acendeu")),
            pct("escura")),
        "- última bateria: %s%%, carregando: %s" % (amostra.get("bateria_pct"), amostra.get("carregando")),
        "",
    ]), encoding="utf-8")


def principal():
    global ENDERECOS
    ENDERECOS = [argumento("--endereco", ENDERECOS[0])]
    if "--uma-vez" in sys.argv:
        amostra = rodada()
        anotar(amostra)
        print(json.dumps(amostra, ensure_ascii=False, indent=1))
        return 0
    if "--devolver" in sys.argv:
        print("devolvido" if devolver(aparelho()) else "nada para devolver")
        return 0
    hora, minuto = (int(x) for x in argumento("--ate", "07:30").split(":"))
    fim = dt.datetime.now().replace(hour=hora, minute=minuto, second=0, microsecond=0)
    if fim <= dt.datetime.now():
        fim += dt.timedelta(days=1)
    try:
        while dt.datetime.now() < fim:
            try:
                anotar(rodada())
            except Exception as falha:          # o vigia nunca cai por uma rodada ruim
                anotar({"quando": dt.datetime.now().isoformat(timespec="seconds"), "erro": str(falha)[:200]})
            time.sleep(60)
    finally:
        devolver(aparelho())
        if ESCURO:
            tela_apagada("acender")         # de manhã a tela volta ao normal (sem tecla de energia: ela bloquearia)
    return 0


if __name__ == "__main__":
    sys.exit(principal())
