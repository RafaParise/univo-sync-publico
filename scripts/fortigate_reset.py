#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fortigate_reset.py
Recuperacao/factory reset de um FortiGate 60D via console serial (equipamento proprio,
acesso fisico ao console). 9600 8-N-1, timeout=2.

Fluxo:
  1. Detecta a porta COM de um cabo de console REAL (FTDI/CH340/CP210x/Prolific/Fortinet).
     - RECUSA-SE a usar o VID da Samsung (0x04E8) -> nunca manda comando para o celular.
  2. Envia \\r\\n a cada 1s ate aparecer "login:".
  3. Loga: admin  / (senha em branco).
  4A. Se cair no prompt do sistema (ex.: "FortiGate-60D #") -> execute factoryreset -> confirma y.
  4B. Se "Login fail"/"incorrect" -> aborta e imprime o procedimento do usuario maintainer.

Uso:
    python fortigate_reset.py            # autodetecta a porta
    python fortigate_reset.py --port COM7  # forca uma porta
    python fortigate_reset.py --list     # so lista as portas e sai
    python fortigate_reset.py --dry-run  # conecta e loga, mas NAO envia factoryreset
"""

import sys
import time
import argparse

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("ERRO: pyserial nao instalado. Rode:  python -m pip install pyserial")

BAUD = 9600
TIMEOUT = 2

# VIDs de chips de cabo de console legitimos
VID_CONSOLE = {
    0x0403: "FTDI",
    0x1A86: "CH340/CH341 (WCH)",
    0x10C4: "CP210x (Silicon Labs)",
    0x067B: "Prolific PL2303",
    # A USB MGMT do 60D pode aparecer com outro VID; nesse caso, use --port COMx.
}
# VIDs que NUNCA devem receber comandos (dispositivos do Rafael, nao-console)
VID_PROIBIDO = {
    0x04E8: "Samsung (Galaxy A12 / celular)",
}


def listar_portas():
    portas = list(list_ports.comports())
    print("Portas seriais encontradas:")
    if not portas:
        print("  (nenhuma)")
    for p in portas:
        vid = f"{p.vid:04X}" if p.vid is not None else "----"
        pid = f"{p.pid:04X}" if p.pid is not None else "----"
        print(f"  {p.device:8} VID_{vid}&PID_{pid}  {p.description}")
    return portas


def detectar_porta():
    """Retorna o device de um cabo de console valido, ou None."""
    candidatas = []
    for p in list_ports.comports():
        if p.vid in VID_PROIBIDO:
            print(f"  [ignorado] {p.device}: {VID_PROIBIDO[p.vid]} -- nao e console, pulando.")
            continue
        if p.vid in VID_CONSOLE:
            candidatas.append((p, VID_CONSOLE[p.vid]))
    if not candidatas:
        return None
    if len(candidatas) > 1:
        print("Mais de um cabo de console encontrado; usando o primeiro. Use --port para escolher.")
    p, chip = candidatas[0]
    print(f"Cabo de console detectado: {p.device} ({chip})")
    return p.device


def ler(ser, segundos=2.0):
    """Le tudo que chegar durante 'segundos' e devolve como texto."""
    fim = time.time() + segundos
    buf = b""
    while time.time() < fim:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        else:
            time.sleep(0.1)
    txt = buf.decode(errors="replace")
    if txt.strip():
        print(txt, end="")
    return txt


def esperar(ser, alvos, tentativas=30, enviar_enter=False):
    """Espera por qualquer string de 'alvos' na saida. Retorna o alvo achado ou None."""
    acumulado = ""
    for _ in range(tentativas):
        if enviar_enter:
            ser.write(b"\r\n")
        acumulado += ler(ser, 1.0)
        baixo = acumulado.lower()
        for alvo in alvos:
            if alvo.lower() in baixo:
                return alvo
    return None


MAINTAINER = """
======================================================================
 CENARIO B: login padrao recusado. Senha do admin foi alterada.
 Recuperacao pelo usuario 'maintainer' (procedimento oficial Fortinet):
======================================================================
 1. Deixe o cabo de console conectado e um terminal aberto (9600 8-N-1).
 2. DESLIGUE o FortiGate da tomada e LIGUE de novo (power cycle fisico).
 3. Observe o boot no console e ANOTE o Serial Number (ex.: FGT60D4615XXXXXXX).
    Costuma aparecer como 'Serial number: ...' nos primeiros segundos.
 4. ASSIM QUE surgir o 'login:' (logo apos o boot) voce tem uma JANELA CURTA
    (~60 segundos). Logue IMEDIATAMENTE:
        login:    maintainer
        Password: bcpb<SERIAL_NUMBER_EM_MAIUSCULAS>
    Ex.: se o serial e FGT60D4615012345, a senha e:  bcpbFGT60D4615012345
 5. Entrou? Rode:   execute factoryreset
    Confirme com:   y
 Observacoes:
  - O serial vai GRUDADO em 'bcpb', sem espaco, sem < >.
  - Se perder a janela de 60s, repita o power cycle.
  - Requer que a conta maintainer esteja habilitada (padrao de fabrica: sim).
======================================================================
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="forca a porta COM (ex.: COM7)")
    ap.add_argument("--list", action="store_true", help="lista portas e sai")
    ap.add_argument("--dry-run", action="store_true", help="loga mas NAO envia factoryreset")
    args = ap.parse_args()

    if args.list:
        listar_portas()
        return

    porta = args.port or detectar_porta()
    if not porta:
        print("\nERRO: nenhum cabo de console valido encontrado.")
        print("Conecte o cabo (FTDI/CH340/CP210x) e instale o driver. Portas atuais:")
        listar_portas()
        sys.exit(2)

    print(f"\nAbrindo {porta} a {BAUD} 8-N-1 (timeout={TIMEOUT}s)...")
    try:
        ser = serial.Serial(porta, BAUD, timeout=TIMEOUT,
                            bytesize=8, parity="N", stopbits=1)
    except serial.SerialException as e:
        sys.exit(f"ERRO ao abrir {porta}: {e}")

    with ser:
        time.sleep(0.5)
        ser.reset_input_buffer()

        print("\n[1] Enviando ENTER ate aparecer 'login:' ...")
        achou = esperar(ser, ["login:"], tentativas=30, enviar_enter=True)
        if not achou:
            print("\nNao recebi 'login:'. Verifique cabo/baud/energia do FortiGate.")
            sys.exit(3)

        print("\n[2] Enviando usuario 'admin' ...")
        ser.write(b"admin\r\n")
        esperar(ser, ["password:"], tentativas=10)

        print("\n[3] Enviando senha em branco ...")
        ser.write(b"\r\n")
        res = esperar(ser, ["#", "login fail", "incorrect", "login:"], tentativas=12)

        if res in (None, "login fail", "incorrect", "login:"):
            print(MAINTAINER)
            sys.exit(10)  # Cenario B

        # Cenario A: prompt do sistema
        print("\n[4] Login OK (prompt do sistema).")
        if args.dry_run:
            print("--dry-run ativo: NAO vou enviar factoryreset. Saindo.")
            return

        print("    Enviando 'execute factoryreset' ...")
        ser.write(b"execute factoryreset\r\n")
        esperar(ser, ["(y/n)", "y/n", "continue"], tentativas=10)
        print("\n    Confirmando com 'y' ...")
        ser.write(b"y\r\n")
        ler(ser, 5.0)
        print("\n[OK] factoryreset enviado. O FortiGate vai reiniciar zerado.")


if __name__ == "__main__":
    main()
