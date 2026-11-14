# -*- coding: utf-8 -*-
"""O proxy que compartilha a internet de casa com quem está no hotspot (scripts/proxy_compartilhado.py), sem internet:
um "site" de mentira no 127.0.0.1."""
import http.server
import socket
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import proxy_compartilhado as pc  # noqa: E402


class Regras(unittest.TestCase):
    def test_so_redes_locais_e_tailscale(self):
        for ip in ("192.168.137.5", "192.168.43.20", "10.0.20.100", "100.70.1.2", "127.0.0.1"):
            self.assertTrue(pc.pode(ip), ip)
        for ip in ("8.8.8.8", "203.0.113.7", "lixo"):
            self.assertFalse(pc.pode(ip), ip)

    def test_destino(self):
        self.assertEqual(pc.separar_destino("site.com:443", 443), ("site.com", 443))
        self.assertEqual(pc.separar_destino("site.com", 80), ("site.com", 80))
        self.assertEqual(pc.separar_destino("[::1]:8080", 80), ("::1", 8080))
        self.assertIsNone(pc.separar_destino("site.com:99999", 80))
        self.assertIsNone(pc.separar_destino("site.com:abc", 80))

    def _resposta(self, ident, ips):
        """Uma resposta DNS de verdade (RFC 1035): a pergunta repetida e uma resposta A por IP (nome comprimido)."""
        import struct
        pergunta = pc.pergunta_dns("site.com", ident)[12:]
        corpo = b"".join(b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4) + socket.inet_aton(ip) for ip in ips)
        return struct.pack(">HHHHHH", ident, 0x8180, 1, len(ips), 0, 0) + pergunta + corpo

    def test_resposta_do_dns_familia(self):
        self.assertEqual(pc.ler_resposta_dns(self._resposta(7, ["1.2.3.4", "5.6.7.8"]), 7), ["1.2.3.4", "5.6.7.8"])
        self.assertEqual(pc.ler_resposta_dns(self._resposta(7, ["0.0.0.0"]), 7), [])     # bloqueado pelo filtro
        self.assertEqual(pc.ler_resposta_dns(self._resposta(7, []), 7), [])              # nao existe
        with self.assertRaises(ValueError):
            pc.ler_resposta_dns(self._resposta(8, ["1.2.3.4"]), 7)                        # resposta de outra pergunta


class Site(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        corpo = b"ola do site"
        self.send_response(200)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


class Passagem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=cls.site.serve_forever, daemon=True).start()
        pc.Atendente.familia = False
        cls.proxy = pc.Servidor(("127.0.0.1", 0), pc.Atendente)
        threading.Thread(target=cls.proxy.serve_forever, daemon=True).start()
        cls.porta_site = cls.site.server_address[1]
        cls.porta_proxy = cls.proxy.server_address[1]

    @classmethod
    def tearDownClass(cls):
        for s in (cls.site, cls.proxy):
            s.shutdown()
            s.server_close()

    def _tudo(self, ligacao):
        dados = b""
        while True:
            pedaco = ligacao.recv(65536)
            if not pedaco:
                return dados
            dados += pedaco

    def test_http_pelo_proxy(self):
        with socket.create_connection(("127.0.0.1", self.porta_proxy), timeout=5) as s:
            s.sendall(("GET http://127.0.0.1:%d/x HTTP/1.1\r\nHost: 127.0.0.1\r\nProxy-Connection: close\r\n"
                       "Connection: close\r\n\r\n" % self.porta_site).encode())
            resposta = self._tudo(s)
        self.assertIn(b"200", resposta.split(b"\r\n", 1)[0])
        self.assertTrue(resposta.endswith(b"ola do site"))

    def test_connect_pelo_proxy(self):
        with socket.create_connection(("127.0.0.1", self.porta_proxy), timeout=5) as s:
            s.sendall(("CONNECT 127.0.0.1:%d HTTP/1.1\r\n\r\n" % self.porta_site).encode())
            self.assertIn(b" 200 ", s.recv(4096))
            s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            self.assertTrue(self._tudo(s).endswith(b"ola do site"))

    def test_lixo_e_recusado(self):
        with socket.create_connection(("127.0.0.1", self.porta_proxy), timeout=5) as s:
            s.sendall(b"ISSO NAO E HTTP\r\n\r\n")
            self.assertIn(b"400", self._tudo(s))


if __name__ == "__main__":
    unittest.main()
