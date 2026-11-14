# -*- coding: utf-8 -*-
"""
medir_dns.py
Mede quanto cada servidor de DNS demora para responder (só leitura; nada muda). Pergunta nomes comuns e um nome
inventado por rodada (que nenhum cache tem), para medir o caminho inteiro. Saída: mediana e pior caso em ms.

Uso:  python scripts\\medir_dns.py                 (os servidores de sempre)
      python scripts\\medir_dns.py 1.1.1.1 8.8.8.8
"""
import os
import random
import socket
import statistics
import struct
import sys
import time

PADRAO = {
    "FortiGuard (EUA, o atual do FortiGate)": "208.91.112.53",
    "Cloudflare": "1.1.1.1",
    "Google": "8.8.8.8",
    "Quad9": "9.9.9.9",
    "ONT Huawei (DNS da operadora)": "192.168.18.1",
    "FortiGate (o que o PC usa)": "10.0.20.1",
}
NOMES = ("google.com", "youtube.com", "github.com", "netflix.com", "whatsapp.net", "steampowered.com")


def pergunta(nome):
    ident = random.randint(0, 65535)
    cabeca = struct.pack(">HHHHHH", ident, 0x0100, 1, 0, 0, 0)
    corpo = b"".join(bytes([len(p)]) + p.encode() for p in nome.split(".")) + b"\x00" + struct.pack(">HH", 1, 1)
    return ident, cabeca + corpo


def medir(servidor, nome, espera=2.0):
    ident, pacote = pergunta(nome)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(espera)
        inicio = time.perf_counter()
        try:
            s.sendto(pacote, (servidor, 53))
            while True:
                dados, _ = s.recvfrom(1500)
                if len(dados) >= 2 and struct.unpack(">H", dados[:2])[0] == ident:
                    return (time.perf_counter() - inicio) * 1000
        except OSError:
            return None


def main(argv):
    servidores = {a: a for a in argv} or PADRAO
    print("%-40s %10s %10s %10s %6s" % ("servidor", "conhecido", "inventado", "pior", "falhas"))
    for rotulo, ip in servidores.items():
        conhecidos, inventados, falhas = [], [], 0
        for _ in range(3):
            for nome in NOMES:
                t = medir(ip, nome)
                conhecidos.append(t) if t is not None else None
                falhas += t is None
            t = medir(ip, "arena-%s.example.com" % os.urandom(4).hex())
            inventados.append(t) if t is not None else None
            falhas += t is None
        todos = conhecidos + inventados
        if not todos:
            print("%-40s %10s" % (rotulo, "sem resposta"))
            continue
        print("%-40s %8.1fms %8.1fms %8.1fms %6d" % (rotulo, statistics.median(conhecidos) if conhecidos else -1,
                                                       statistics.median(inventados) if inventados else -1,
                                                       max(todos), falhas))


if __name__ == "__main__":
    main(sys.argv[1:])
