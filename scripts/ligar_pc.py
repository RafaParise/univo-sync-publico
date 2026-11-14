#!/usr/bin/env python3
"""
ligar_pc.py - roda no Termux do A12 (DMZ, 10.0.10.50): liga o PC do Rafael pela rede (Wake-on-LAN), 13/11/2026.

Por que no A12: com o PC desligado, alguém de dentro de casa tem que mandar o "pacote mágico" à placa de rede dele, e o
A12 fica sempre ligado. O FortiGate deixa passar só isto (regra 11 A12_LIGA_PC_WOL: UDP 9 e ping, do A12 ao PC) e
guarda o endereço físico do PC (ARP fixo), para entregar o pacote mesmo com o PC desligado
(scripts/provisionar_rede.py).

De longe (dados móveis): o celular do Rafael, no Tailscale, abre no navegador
    http://samsung-a12-de-rafa-parise:8000/ligar-pc?chave=...
O endereço só atende a rede do Tailscale (100.64.0.0/10) e o PC; sem a chave certa, recusa. Nada de senha no código:
o MAC do PC e a chave vêm de ~/.parise-sentinela.env (PC_MAC, PC_IP, LIGAR_PC_CHAVE).

  python ligar_pc.py agora      manda o pacote mágico (3 vezes)
  python ligar_pc.py estado     o PC responde ao ping?
  python ligar_pc.py servir     o endereço da porta 8000 (o comando ligar-pc sobe e desce)
Só a biblioteca padrão.
"""
import hmac
import ipaddress
import socket
import subprocess
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONF = Path.home() / ".parise-sentinela.env"
PORTA = 8000
PORTA_WOL = 9
QUEM_PODE = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("10.0.20.100/32"),
             ipaddress.ip_network("127.0.0.0/8"))


def ler_conf(caminho=CONF):
    conf = {}
    try:
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                chave, valor = linha.split("=", 1)
                conf[chave.strip()] = valor.strip().strip('"')
    except OSError:
        pass
    return conf


def pacote_magico(mac):
    """6 bytes 0xFF e o MAC 16 vezes (o formato do Wake-on-LAN)."""
    limpo = "".join(c for c in str(mac) if c.isalnum())
    if len(limpo) != 12:
        raise ValueError("PC_MAC inválido na conf")
    return b"\xff" * 6 + bytes.fromhex(limpo) * 16


def enviar(mac, ip, vezes=3):
    pacote = pacote_magico(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for _ in range(vezes):
            s.sendto(pacote, (ip, PORTA_WOL))
            time.sleep(0.2)


def pc_ligado(ip, espera=2, ip_tailscale=None):
    """O PC responde? Primeiro a Area de Trabalho Remota dele pelo Tailscale (porta 3389: o firewall do Windows ja a
    libera so para a rede do Tailscale; o ping na rede de cabo ele recusa, 13/11/2026), depois o ping."""
    alvo = ip_tailscale or ler_conf().get("PC_TAILSCALE_IP", "100.64.119.39")
    try:
        with socket.create_connection((alvo, 3389), timeout=espera):
            return True
    except OSError:
        pass
    try:
        return subprocess.run(["ping", "-c", "1", "-W", str(espera), ip], capture_output=True,
                              timeout=espera + 3).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def pode(endereco):
    try:
        ip = ipaddress.ip_address(endereco)
    except ValueError:
        return False
    return any(ip in rede for rede in QUEM_PODE)


class Pagina(BaseHTTPRequestHandler):
    def log_message(self, formato, *args):     # sem registro de quem pediu: só o resultado vai para o print
        pass

    def responder(self, codigo, texto):
        corpo = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                 "<body style='font:20px sans-serif;padding:24px'>%s</body>" % texto).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        if not pode(self.client_address[0]):
            return self.responder(403, "Só pela rede do Tailscale.")
        conf = ler_conf()
        partes = urllib.parse.urlparse(self.path)
        chave = (urllib.parse.parse_qs(partes.query).get("chave") or [""])[0]
        esperado = conf.get("LIGAR_PC_CHAVE", "")
        if not esperado or not hmac.compare_digest(chave.encode(), esperado.encode()):
            return self.responder(403, "Chave errada.")
        ip = conf.get("PC_IP", "10.0.20.100")
        if partes.path == "/ligar-pc":
            if pc_ligado(ip):
                return self.responder(200, "✅ O PC já está ligado.")
            enviar(conf.get("PC_MAC", ""), ip)
            print("%s pacote mágico enviado ao PC" % time.strftime("%F %T"), flush=True)
            return self.responder(200, "⏳ Pacote enviado. O PC liga em uns 30 a 60 segundos; depois abra o Windows "
                                       "App. <a href='/estado-pc?chave=%s'>Conferir</a>" % urllib.parse.quote(chave))
        if partes.path == "/estado-pc":
            return self.responder(200, "✅ O PC está ligado." if pc_ligado(ip) else "⛔ O PC está desligado.")
        return self.responder(404, "Endereços: /ligar-pc e /estado-pc")


def main(argv=None):
    acao = (argv or sys.argv[1:] or ["estado"])[0]
    conf = ler_conf()
    ip = conf.get("PC_IP", "10.0.20.100")
    if acao == "agora":
        enviar(conf.get("PC_MAC", ""), ip)
        print("pacote mágico enviado ao PC (%s)" % ip)
        return 0
    if acao == "estado":
        print("o PC está ligado" if pc_ligado(ip) else "o PC está desligado")
        return 0
    if acao == "servir":
        if not conf.get("LIGAR_PC_CHAVE"):
            print("sem LIGAR_PC_CHAVE em %s: nada a servir" % CONF)
            return 1
        print("%s servindo na porta %d (só Tailscale e o PC)" % (time.strftime("%F %T"), PORTA), flush=True)
        ThreadingHTTPServer(("0.0.0.0", PORTA), Pagina).serve_forever()
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
