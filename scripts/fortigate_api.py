"""
fortigate_api.py
Cliente mínimo da API REST do FortiOS 5.4 (login por sessão, como a interface web).
Certificado: o FortiGate usa um autoassinado; na 1ª conexão guardamos a impressão
SHA-256 dele e, dali em diante, recusamos se mudar (não é "verify=False" cego).
"""
import base64
import hashlib
import http.client
import json
import ssl
import urllib.parse


class ErroAPI(Exception):
    """O FortiGate recusou a operação ou não respondeu."""


def q(nome):
    return urllib.parse.quote(str(nome), safe="")


class FortiAPI:
    def __init__(self, host, impressao=None, timeout=30):
        self.host = host
        self.impressao = impressao      # SHA-256 esperado do certificado (None = 1ª vez)
        self.impressao_vista = None
        self.timeout = timeout
        self.cookies = {}
        self.csrf = None
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE   # conferido à mão pela impressão abaixo
        self.ctx.set_ciphers("DEFAULT:@SECLEVEL=1")

    # ---------- HTTP ----------
    def _req(self, metodo, caminho, corpo=None, form=False):
        con = http.client.HTTPSConnection(self.host, timeout=self.timeout, context=self.ctx)
        try:
            con.connect()
            fp = hashlib.sha256(con.sock.getpeercert(binary_form=True)).hexdigest()
            if self.impressao and fp != self.impressao:
                raise ErroAPI(f"O certificado do FortiGate em {self.host} mudou. Pare e confira o aparelho.")
            self.impressao_vista = fp
            cab = {}
            if self.cookies:
                cab["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            if self.csrf:
                cab["X-CSRFTOKEN"] = self.csrf
            dados = None
            if corpo is not None:
                if form:
                    dados = urllib.parse.urlencode(corpo)
                    cab["Content-Type"] = "application/x-www-form-urlencoded"
                else:
                    dados = json.dumps(corpo)
                    cab["Content-Type"] = "application/json"
            con.request(metodo, caminho, body=dados, headers=cab)
            r = con.getresponse()
            texto = r.read().decode(errors="replace")
            for k, v in r.getheaders():
                if k.lower() == "set-cookie" and "=" in v:
                    nome, valor = v.split(";", 1)[0].split("=", 1)
                    self.cookies[nome.strip()] = valor.strip()
                    if nome.strip() == "ccsrftoken":
                        self.csrf = valor.strip().strip('"')
            return r.status, texto
        except (OSError, http.client.HTTPException) as e:
            raise ErroAPI(f"Sem resposta de {self.host}: {e}") from e
        finally:
            con.close()

    def _json(self, metodo, caminho, corpo=None):
        st, txt = self._req(metodo, "/api/v2/" + caminho, corpo)
        try:
            d = json.loads(txt)
        except ValueError:
            d = {"resposta": txt[:200]}
        return st, d

    # ---------- sessão ----------
    def login(self, usuario, senha):
        self.cookies, self.csrf = {}, None
        _, txt = self._req("POST", "/logincheck", {"username": usuario, "secretkey": senha, "ajax": "1"}, form=True)
        if not txt.strip().startswith("1"):
            raise ErroAPI("login recusado")
        return True

    def logout(self):
        try:
            self._req("POST", "/logout")
        except ErroAPI:
            pass

    # ---------- configuração ----------
    def ler(self, caminho):
        st, d = self._json("GET", "cmdb/" + caminho)
        if st != 200:
            raise ErroAPI(f"GET {caminho}: HTTP {st} {d}")
        return d.get("results")

    def monitor(self, caminho):
        st, d = self._json("GET", "monitor/" + caminho)
        if st != 200:
            raise ErroAPI(f"GET monitor/{caminho}: HTTP {st} {d}")
        return d.get("results")

    def existe(self, caminho):
        st, _ = self._json("GET", "cmdb/" + caminho)
        return st == 200

    def _conferir(self, oque, st, d):
        if st != 200 or d.get("status", "success") != "success":
            erro = {k: d.get(k) for k in ("http_status", "error", "cli_error", "resposta") if d.get(k)}
            raise ErroAPI(f"{oque}: HTTP {st} {erro}")
        return d

    def ajustar(self, caminho, dados):
        """PUT num objeto único (ex.: system/global) ou já existente."""
        st, d = self._json("PUT", "cmdb/" + caminho, dados)
        return self._conferir(f"PUT {caminho}", st, d)

    def gravar(self, tabela, chave, dados):
        """Cria ou atualiza uma entrada de tabela (PUT se existe, senão POST)."""
        if self.existe(f"{tabela}/{q(chave)}"):
            return self.ajustar(f"{tabela}/{q(chave)}", dados)
        st, d = self._json("POST", "cmdb/" + tabela, dados)
        return self._conferir(f"POST {tabela} ({chave})", st, d)

    def backup(self):
        """Texto completo da configuração (mesma sintaxe do CLI)."""
        st, txt = self._req("GET", "/api/v2/monitor/system/config/backup?scope=global")
        if st != 200 or not txt.startswith("#config-version"):
            raise ErroAPI(f"backup: HTTP {st}")
        return txt

    def restaurar(self, texto):
        """Envia a configuração completa. O FortiGate aplica e reinicia sozinho."""
        corpo = {"source": "upload", "scope": "global",
                 "file_content": base64.b64encode(texto.encode()).decode()}
        try:
            return self._json("POST", "monitor/system/config/restore", corpo)
        except ErroAPI:
            return None, {"status": "conexão caiu (normal: o aparelho reinicia)"}

    def apagar(self, tabela, chave):
        if not self.existe(f"{tabela}/{q(chave)}"):
            return None
        st, d = self._json("DELETE", f"cmdb/{tabela}/{q(chave)}")
        return self._conferir(f"DELETE {tabela}/{chave}", st, d)
