# -*- coding: utf-8 -*-
"""
proxy_compartilhado.py - compartilha a internet de casa (pela VPN do Tailscale) com quem está no hotspot, 13/11/2026.

Por que um proxy: o hotspot do Android não manda pela VPN o tráfego de quem se conecta a ele (o VpnService cobre só os
apps do próprio aparelho). Este proxy É um programa do aparelho: o que ele busca passa pela VPN até a saída de casa
(o PC, ou o A12 com o PC desligado). Quem está no hotspot põe, nas configurações do Wi-Fi, "Proxy manual" com o
endereço deste aparelho e a porta 8888. Pedido do Rafael (administrador da rede da escola, com autorização).

Criptografia: do aluno ao aparelho, a do Wi-Fi (WPA2/3 do hotspot); do aparelho a casa, a do Tailscale (WireGuard); do
site em diante, o próprio HTTPS (o proxy só passa os bytes do CONNECT, não abre nada).

Padrão: DNS comum. Com --familia (só quando o Rafael pedir, 13/11/2026), os nomes vão ao DNS família da Cloudflare
(1.1.1.3), que bloqueia malware e conteúdo adulto. O proxy não guarda endereço visitado (só contagens).
Só atende redes locais (hotspot, casa) e o Tailscale; não abre porta para a internet.

  python proxy_compartilhado.py              porta 8888, DNS comum
  python proxy_compartilhado.py --familia    com o DNS família (malware e conteúdo adulto bloqueados)
  python proxy_compartilhado.py --porta 3128
Só a biblioteca padrão (roda no Termux e no Windows).
"""
import argparse
import ipaddress
import random
import re
import select
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
import urllib.parse

PORTA = 8888
DNS_FAMILIA = "1.1.1.3"        # Cloudflare for Families: malware + conteúdo adulto (o 1.0.0.3 é o reserva)
QUEM_PODE = [ipaddress.ip_network(r) for r in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
                                                "127.0.0.0/8")]
MAX_LIGACOES = 64
ESPERA = 30
_CONTAGEM = {"ligacoes": 0, "bloqueados": 0}
_TRAVA = threading.Lock()
_CACHE_DNS = {}


def pode(endereco):
    try:
        ip = ipaddress.ip_address(endereco)
    except ValueError:
        return False
    return any(ip in rede for rede in QUEM_PODE)


def separar_destino(texto, porta_padrao):
    """'site.com:443' -> ('site.com', 443); '[::1]:80' -> ('::1', 80). None se vier lixo."""
    texto = texto.strip()
    if texto.startswith("["):
        fim = texto.find("]")
        if fim < 0:
            return None
        maquina, resto = texto[1:fim], texto[fim + 1:]
        porta = resto[1:] if resto.startswith(":") else str(porta_padrao)
    else:
        maquina, _, porta = texto.rpartition(":") if texto.count(":") == 1 else (texto, "", str(porta_padrao))
        if not maquina:
            maquina, porta = texto, str(porta_padrao)
    if not porta.isdigit() or not 0 < int(porta) < 65536 or not maquina or len(maquina) > 253:
        return None
    return maquina, int(porta)


def pergunta_dns(maquina, ident):
    """Pergunta DNS do tipo A (o formato da RFC 1035)."""
    cabeca = struct.pack(">HHHHHH", ident, 0x0100, 1, 0, 0, 0)
    nome = b"".join(bytes([len(p)]) + p.encode("idna") for p in maquina.rstrip(".").split(".")) + b"\x00"
    return cabeca + nome + struct.pack(">HH", 1, 1)


def _pular_nome(dados, i):
    while i < len(dados):
        tamanho = dados[i]
        if tamanho == 0:
            return i + 1
        if tamanho & 0xC0 == 0xC0:          # ponteiro de compressao: 2 bytes
            return i + 2
        i += tamanho + 1
    raise ValueError("resposta DNS cortada")


def ler_resposta_dns(dados, ident):
    """Resposta DNS -> lista de IPv4 (vazia se bloqueado: 0.0.0.0; ou se o nome nao existe)."""
    if len(dados) < 12:
        raise ValueError("resposta DNS curta")
    rid, _flags, perguntas, respostas = struct.unpack(">HHHH", dados[:8])
    if rid != ident:
        raise ValueError("resposta de outra pergunta")
    i = 12
    for _ in range(perguntas):
        i = _pular_nome(dados, i) + 4
    ips = []
    for _ in range(respostas):
        i = _pular_nome(dados, i)
        tipo, _classe, _ttl, tamanho = struct.unpack(">HHIH", dados[i:i + 10])
        i += 10
        if tipo == 1 and tamanho == 4:
            ips.append(socket.inet_ntoa(dados[i:i + 4]))
        i += tamanho
    return [ip for ip in ips if ip != "0.0.0.0"]


def resolver(maquina, familia):
    """IPv4 do nome. Com --familia, pelo DNS familia da Cloudflare (1.1.1.3; 0.0.0.0 = bloqueado). O pedido vai
    dentro da VPN ate a casa (criptografado ate la). Cache curto (5 min)."""
    try:
        ipaddress.ip_address(maquina)
        return [maquina]                      # ja e' um endereco
    except ValueError:
        pass
    if not familia:
        try:
            return list(dict.fromkeys(i[4][0] for i in socket.getaddrinfo(maquina, None, socket.AF_INET)))
        except OSError:
            return []
    agora = time.monotonic()
    guardado = _CACHE_DNS.get(maquina)
    if guardado and agora - guardado[0] < 300:
        return guardado[1]
    ips = None
    for _tentativa in range(2):
        ident = random.randint(0, 65535)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(3)
                s.sendto(pergunta_dns(maquina, ident), (DNS_FAMILIA, 53))
                ips = ler_resposta_dns(s.recv(4096), ident)
                break
        except (OSError, ValueError, UnicodeError, struct.error):
            continue
    if ips is None:
        return []
    _CACHE_DNS[maquina] = (agora, ips)
    if len(_CACHE_DNS) > 2000:
        _CACHE_DNS.clear()
    return ips


def passar(a, b):
    """Os bytes nos dois sentidos até um dos lados fechar (ou 5 min parados)."""
    lados = [a, b]
    while True:
        prontos, _, erro = select.select(lados, [], lados, 300)
        if erro or not prontos:
            return
        for lado in prontos:
            try:
                dados = lado.recv(65536)
            except OSError:
                return
            if not dados:
                return
            (b if lado is a else a).sendall(dados)


class Atendente(socketserver.BaseRequestHandler):
    familia = False

    def responder(self, codigo, frase):
        corpo = frase.encode("utf-8")
        self.request.sendall(("HTTP/1.1 %d %s\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: %d\r\n"
                              "Connection: close\r\n\r\n" % (codigo, "Recusado" if codigo >= 400 else "OK",
                                                              len(corpo))).encode("ascii") + corpo)

    def handle(self):
        if not pode(self.client_address[0]):
            return
        self.request.settimeout(ESPERA)
        cabeca = b""
        while b"\r\n\r\n" not in cabeca and len(cabeca) < 65536:
            pedaco = self.request.recv(4096)
            if not pedaco:
                return
            cabeca += pedaco
        linha, _, resto_cabeca = cabeca.partition(b"\r\n")
        partes = linha.decode("latin-1").split()
        if len(partes) != 3:
            return self.responder(400, "Pedido estranho.")
        metodo, alvo, versao = partes
        with _TRAVA:
            _CONTAGEM["ligacoes"] += 1
        if metodo.upper() == "CONNECT":
            destino = separar_destino(alvo, 443)
            corpo_inicial = b""
        else:
            url = urllib.parse.urlsplit(alvo)
            if url.scheme != "http" or not url.hostname:
                return self.responder(400, "Use o proxy só para sites (http ou https).")
            destino = (url.hostname, url.port or 80)
            caminho = urllib.parse.urlunsplit(("", "", url.path or "/", url.query, ""))
            # o pedido segue com o caminho relativo e sem os cabeçalhos do proxy
            linhas = [l for l in resto_cabeca.split(b"\r\n") if not l.lower().startswith(b"proxy-")]
            corpo_inicial = ("%s %s %s\r\n" % (metodo, caminho, versao)).encode("latin-1") + b"\r\n".join(linhas)
        if not destino:
            return self.responder(400, "Endereço inválido.")
        ips = resolver(destino[0], self.familia)
        if not ips:
            with _TRAVA:
                _CONTAGEM["bloqueados"] += 1
            return self.responder(403, "Endereço bloqueado pelo filtro de família ou inexistente.")
        try:
            remoto = socket.create_connection((ips[0], destino[1]), timeout=ESPERA)
        except OSError:
            return self.responder(502, "O site não respondeu.")
        with remoto:
            remoto.settimeout(None)
            self.request.settimeout(None)
            if metodo.upper() == "CONNECT":
                self.request.sendall(b"HTTP/1.1 200 Conexao estabelecida\r\n\r\n")
            else:
                remoto.sendall(corpo_inicial)
            passar(self.request, remoto)


class Servidor(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, endereco, atendente):
        super().__init__(endereco, atendente)
        self.vagas = threading.BoundedSemaphore(MAX_LIGACOES)

    def process_request(self, pedido, endereco):
        if not self.vagas.acquire(blocking=False):      # cheio: recusa em vez de travar o aparelho
            self.shutdown_request(pedido)
            return
        super().process_request(pedido, endereco)

    def process_request_thread(self, pedido, endereco):
        try:
            super().process_request_thread(pedido, endereco)
        finally:
            self.vagas.release()


def enderecos_locais():
    """Os endereços deste aparelho que quem está no hotspot ou em casa pode usar (para mostrar na tela)."""
    achados = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            achados.add(info[4][0])
    except OSError:
        pass
    # No Android o nome do aparelho costuma dar so "localhost": o ifconfig (do proprio Android, sem root) lista os
    # enderecos, inclusive o do hotspot.
    try:
        saida = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5).stdout
        achados.update(re.findall(r"inet (?:addr:)?(\d+\.\d+\.\d+\.\d+)", saida))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return sorted(ip for ip in achados if pode(ip) and not ip.startswith("127.") and not ip.startswith("100."))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compartilha a internet de casa (pela VPN) com quem está no hotspot.")
    ap.add_argument("--porta", type=int, default=PORTA)
    ap.add_argument("--familia", action="store_true", help="DNS família da Cloudflare (só quando pedido)")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    Atendente.familia = args.familia
    servidor = Servidor(("0.0.0.0", args.porta), Atendente)
    print("Proxy da internet de casa na porta %d (%s)." % (args.porta, "com o DNS família da Cloudflare" if args.familia else
                                                            "DNS comum"))
    for ip in enderecos_locais():
        print("  Quem está na rede deste aparelho: Wi-Fi > Proxy manual > %s porta %d" % (ip, args.porta))
    print("  (no hotspot do Windows o endereço costuma ser 192.168.137.1; no do Android, 192.168.43.1 ou parecido)")
    print("Deixe esta janela aberta. Para parar: Ctrl+C.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("Parado. Ligações: %(ligacoes)d, bloqueadas pelo filtro: %(bloqueados)d." % _CONTAGEM)
    return 0


if __name__ == "__main__":
    sys.exit(main())
