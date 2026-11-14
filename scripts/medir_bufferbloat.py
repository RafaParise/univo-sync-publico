# -*- coding: utf-8 -*-
"""
medir_bufferbloat.py
O PC enchendo a internet piora o Wi-Fi da casa? (13/11/2026)

Quem mede é o A12, que está no Wi-Fi da ONT Huawei como a TV e o outro celular: ele faz ping no 1.1.1.1 (pelo adb)
em três momentos: parado, com o PC baixando forte pelo cabo do FortiGate e com o PC enviando forte. Se o ping do A12
sobe muito com a carga do PC, a fila está na ONT/operadora, e vale um modelador no FortiGate segurando o PC um pouco
abaixo do limite da linha (a fila passa a ser a do FortiGate, e o resto da casa não sente). Se não sobe, nada a fazer.

A carga usa o teste público da Cloudflare (speed.cloudflare.com), 4 ligações ao mesmo tempo, 20 s cada fase.
Só mede; não muda nada. Uso:  python scripts\\medir_bufferbloat.py
"""
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.request

ALVO = "1.1.1.1"
FASE = 20
LIGACOES = 4
BAIXAR = "https://speed.cloudflare.com/__down?bytes=50000000"  # 100 MB ou mais: 403 (conferido 13/11)
# Sem um nome de programa, a Cloudflare recusa (403) o urllib. Nome generico, sem dado de ninguem.
CABECALHO = {"User-Agent": "medir-bufferbloat/1.0"}
ENVIAR = "https://speed.cloudflare.com/__up"


def ping_do_a12(segundos):
    r = subprocess.run(["adb", "shell", "ping", "-i", "0.2", "-W", "2", "-w", str(segundos), ALVO],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    tempos = [float(t) for t in re.findall(r"time=([\d.]+)", r.stdout)]
    enviados = re.search(r"(\d+) packets transmitted, (\d+) received", r.stdout)
    perda = 0.0
    if enviados and int(enviados.group(1)):
        perda = 100.0 * (1 - int(enviados.group(2)) / int(enviados.group(1)))
    return tempos, perda


ALVO_WIFI = "1.0.0.1"     # o outro endereco da Cloudflare: so ele ganha a rota pelo Wi-Fi durante a medida


def _ps(comando):
    return subprocess.run(["powershell", "-NoProfile", "-Command", comando], capture_output=True, text=True).stdout.strip()


def ping_do_wifi_do_pc(segundos):
    """O ping sai pelo Wi-Fi do PC (que esta na ONT, como a TV), por uma rota TEMPORARIA so para o 1.0.0.1
    (ActiveStore: some no reinicio, e o finally apaga no fim). O ping do Windows manda um por segundo."""
    porta = _ps("(Get-NetRoute -InterfaceAlias 'Wi-Fi' -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 | "
                "Select-Object -First 1).NextHop")
    if not porta:
        return [], 100.0
    _ps("New-NetRoute -DestinationPrefix '%s/32' -InterfaceAlias 'Wi-Fi' -NextHop '%s' -PolicyStore ActiveStore "
        "-RouteMetric 1 | Out-Null" % (ALVO_WIFI, porta))
    try:
        r = subprocess.run(["ping", "-n", str(segundos), "-w", "1500", ALVO_WIFI], capture_output=True, text=True,
                           encoding="cp850", errors="replace")
    finally:
        _ps("Remove-NetRoute -DestinationPrefix '%s/32' -InterfaceAlias 'Wi-Fi' -Confirm:$false" % ALVO_WIFI)
    tempos = [float(t) for t in re.findall(r"(?:tempo|time)[=<]([0-9.]+)ms", r.stdout)]
    return tempos, 100.0 * (1 - len(tempos) / max(segundos, 1))


def resumo(nome, tempos, perda, mbits=None):
    if not tempos:
        return "%-22s sem resposta%s" % (nome, ("   PC a %.0f Mbit/s" % mbits) if mbits else "")
    tempos = sorted(tempos)
    p95 = tempos[int(len(tempos) * 0.95) - 1] if len(tempos) > 20 else tempos[-1]
    texto = "%-22s mediana %6.1f ms   p95 %6.1f ms   perda %4.1f%%" % (nome, statistics.median(tempos), p95, perda)
    if mbits is None:
        return texto
    return texto + ("   PC a %.0f Mbit/s" % mbits if mbits > 1 else "   A CARGA FALHOU: medida sem valor")


def carga(modo, segundos, contador):
    fim = time.monotonic() + segundos

    def baixar():
        while time.monotonic() < fim:
            try:
                with urllib.request.urlopen(urllib.request.Request(BAIXAR, headers=CABECALHO), timeout=10) as resposta:
                    while time.monotonic() < fim:
                        pedaco = resposta.read(1 << 16)
                        if not pedaco:
                            break
                        contador[0] += len(pedaco)
            except OSError:
                time.sleep(0.5)

    def enviar():
        bloco = b"0" * (1 << 20)
        while time.monotonic() < fim:
            try:
                urllib.request.urlopen(urllib.request.Request(ENVIAR, data=bloco * 25, method="POST", headers=CABECALHO), timeout=15).read()
                contador[0] += len(bloco) * 25
            except OSError:
                time.sleep(0.5)

    linhas = [threading.Thread(target=baixar if modo == "baixar" else enviar, daemon=True) for _ in range(LIGACOES)]
    for t in linhas:
        t.start()
    return linhas


def fase(nome, modo=None):
    contador = [0]
    inicio = time.monotonic()
    linhas = carga(modo, FASE + 3, contador) if modo else []
    if modo:
        time.sleep(3)                      # deixa a carga chegar ao máximo antes de medir
    tempos, perda = MEDIDOR[0](FASE)
    mbits = contador[0] * 8 / 1e6 / max(time.monotonic() - inicio, 1) if modo else None
    for t in linhas:
        t.join(timeout=20)
    return resumo(nome, tempos, perda, mbits), tempos


MEDIDOR = [ping_do_a12]


def main():
    if "--pelo-wifi-do-pc" in sys.argv:
        MEDIDOR[0] = ping_do_wifi_do_pc
        print("O Wi-Fi do PC (na ONT, como a TV) mede o ping ao %s; o cabo do PC faz a carga." % ALVO)
    else:
        print("O A12 mede o ping ao %s (ele está no Wi-Fi da casa); o PC faz a carga pelo cabo." % ALVO)
    parado, base = fase("parado")
    print(parado)
    for nome, modo in (("PC baixando forte", "baixar"), ("PC enviando forte", "enviar")):
        texto, tempos = fase(nome, modo)
        print(texto)
        if base and tempos:
            print("%-22s +%.1f ms na mediana com a carga do PC" % ("", statistics.median(tempos) - statistics.median(base)))


if __name__ == "__main__":
    main()
