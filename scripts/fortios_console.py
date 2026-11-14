"""
fortios_console.py
Conversa com a linha de comando do FortiOS pela porta serial (pyserial).
Usado pelo provisionar_fortigate.py. Regra: erro do FortiOS vira exceção,
nunca passa em silêncio.
"""
import re
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # os testes com porta simulada não precisam do pyserial
    serial = None
    list_ports = None

BAUD = 9600

# Chips de cabo de console e dispositivos que nunca podem receber comandos
VID_CONSOLE = {0x0403: "FTDI", 0x1A86: "CH340/CH341", 0x10C4: "CP210x", 0x067B: "Prolific PL2303"}
VID_PROIBIDO = {0x04E8: "Samsung (celular)"}

# Prompt da CLI no fim do texto: "FGT60D # ", "FG60D-BANCADA (dmz) # "
PROMPT = re.compile(r"[\r\n][^\r\n]{1,80} [#$] ?$")
PROMPT_RAIZ = re.compile(r"[\r\n][^\r\n()]{1,80} [#$] ?$")  # sem "(contexto)"
CONFIRMA = re.compile(r"\(y/n\)\s*$", re.I)
LOGIN = re.compile(r"login:\s*$", re.I)
SENHA = re.compile(r"password:\s*$", re.I)
NOVA_SENHA = re.compile(r"new password:\s*$", re.I)
CONFIRMA_SENHA = re.compile(r"confirm password:\s*$", re.I)
LOGIN_FALHOU = re.compile(r"login incorrect|login fail|access denied", re.I)

# Mensagens com que o FortiOS recusa um comando
ERROS = re.compile(
    r"command fail|unknown action|parse error|entry not found|node_check_object fail"
    r"|return code -\d+|entry is used|must be set|not found in datasource",
    re.I,
)


class FalhaFortiOS(Exception):
    """O FortiOS recusou um comando (ou não respondeu)."""

    def __init__(self, comando, saida):
        super().__init__(f"FortiOS recusou '{comando}':\n{saida.strip()[-600:]}")
        self.comando = comando
        self.saida = saida


class FalhaLogin(Exception):
    """Usuário/senha recusados ou o aparelho não respondeu."""


def achar_porta(aviso=print):
    """Devolve a COM de um cabo de console real; ignora o celular (Samsung)."""
    if list_ports is None:
        raise RuntimeError("pyserial não instalado: python -m pip install pyserial")
    achadas = []
    for p in list_ports.comports():
        if p.vid in VID_PROIBIDO:
            aviso(f"  [ignorada] {p.device}: {VID_PROIBIDO[p.vid]}")
        elif p.vid in VID_CONSOLE:
            achadas.append((p.device, VID_CONSOLE[p.vid]))
    if not achadas:
        return None
    if len(achadas) > 1:
        aviso(f"  Mais de um cabo de console; usando {achadas[0][0]}. Use --porta para escolher.")
    aviso(f"  Cabo de console: {achadas[0][0]} ({achadas[0][1]})")
    return achadas[0][0]


class Console:
    """Sessão na CLI do FortiOS por uma porta serial já aberta."""

    def __init__(self, ser, eco=None, pausa=1.0):
        self.ser = ser
        self.eco = eco          # recebe cada pedaço lido (para mostrar na tela)
        self.pausa = pausa      # intervalo entre ENTERs ao acordar o console
        self.transcricao = []   # tudo que foi lido, para o log

    @classmethod
    def abrir(cls, porta, **kw):
        """Abre a porta a 9600 8-N-1 com timeout de 2 s."""
        if serial is None:
            raise RuntimeError("pyserial não instalado: python -m pip install pyserial")
        ser = serial.Serial(porta, BAUD, bytesize=8, parity="N", stopbits=1, timeout=2)
        return cls(ser, **kw)

    def fechar(self):
        self.ser.close()

    # ---------- baixo nível ----------
    def enviar(self, texto):
        """Digita o texto e ENTER (o console do FortiOS usa CR)."""
        self.ser.write((texto + "\r").encode())

    def ler_ate(self, padroes, limite):
        """Lê até o fim do texto casar com um dos padrões. Devolve (texto, índice) ou (texto, None)."""
        buf = ""
        fim = time.monotonic() + limite
        while time.monotonic() < fim:
            dado = self.ser.read(self.ser.in_waiting or 1)
            if not dado:
                time.sleep(0.01)
                continue
            txt = dado.decode(errors="replace")
            buf += txt
            if self.eco:
                self.eco(txt)
            for i, p in enumerate(padroes):
                if p.search(buf):
                    self.transcricao.append(buf)
                    return buf, i
        self.transcricao.append(buf)
        return buf, None

    # ---------- login ----------
    def acordar(self, tentativas=60):
        """Manda ENTER até aparecer 'login:' ou um prompt. Devolve 'login' ou 'prompt'."""
        for _ in range(tentativas):
            self.enviar("")
            _, i = self.ler_ate([LOGIN, PROMPT], max(self.pausa, 0.05))
            if i == 0:
                return "login"
            if i == 1:
                return "prompt"
        raise FalhaLogin("O console não respondeu (cabo, porta COM ou aparelho desligado).")

    def login(self, usuario, senhas, nova_senha=None):
        """Tenta as senhas em ordem. Se o FortiOS exigir troca de senha, usa nova_senha."""
        if self.acordar() == "prompt":
            return "ja_logado"
        vistas = []
        for senha in senhas:
            if senha in vistas:
                continue
            vistas.append(senha)
            self.enviar(usuario)
            _, i = self.ler_ate([SENHA], 10)
            if i is None:
                raise FalhaLogin("Não apareceu o pedido de senha.")
            self.enviar(senha)
            buf, i = self.ler_ate([PROMPT, NOVA_SENHA, LOGIN_FALHOU, LOGIN], 20)
            if i == 0:
                return "ok"
            if i == 1:
                if not nova_senha:
                    raise FalhaLogin("O FortiOS exige trocar a senha e não há ADMIN_SENHA no .env.")
                self.enviar(nova_senha)
                self.ler_ate([CONFIRMA_SENHA], 10)
                self.enviar(nova_senha)
                _, i = self.ler_ate([PROMPT, LOGIN_FALHOU], 20)
                if i == 0:
                    return "senha_trocada"
                raise FalhaLogin("A troca obrigatória de senha falhou.")
            if not LOGIN.search(buf):          # senha recusada: espera o 'login:' de novo
                self.ler_ate([LOGIN], 15)
        raise FalhaLogin("Nenhuma senha funcionou (veja o roteiro do usuário maintainer no fortigate_reset.py).")

    # ---------- comandos ----------
    def comando(self, cmd, limite=20, confirmar=False):
        """Manda um comando e devolve a saída. Erro do FortiOS vira FalhaFortiOS."""
        self.ser.reset_input_buffer()
        self.enviar(cmd)
        buf, i = self.ler_ate([PROMPT, CONFIRMA], limite)
        if i == 1:
            self.enviar("y" if confirmar else "n")
            mais, i = self.ler_ate([PROMPT], limite)
            buf += mais
            if not confirmar:
                raise FalhaFortiOS(cmd, buf + "\n(pediu confirmação e o script respondeu 'n')")
        if i is None:
            raise FalhaFortiOS(cmd, buf + "\n(sem resposta dentro do prazo)")
        saida = buf.split("\n", 1)[1] if "\n" in buf else ""  # tira o eco do comando
        if ERROS.search(saida):
            raise FalhaFortiOS(cmd, buf)
        return saida

    def sair_para_raiz(self):
        """Depois de um erro, sai dos blocos 'config' sem salvar o bloco atual."""
        for _ in range(8):
            self.ser.reset_input_buffer()
            self.enviar("abort")
            buf, i = self.ler_ate([PROMPT], 10)
            if i == 0 and PROMPT_RAIZ.search(buf):
                return
        raise FalhaFortiOS("abort", "não consegui voltar ao prompt principal")

    def versao(self):
        """Lê a versão do FortiOS. Devolve ((maior, menor, patch), saída completa)."""
        saida = self.comando("get system status")
        m = re.search(r"v(\d+)\.(\d+)\.(\d+)", saida)
        if not m:
            raise FalhaFortiOS("get system status", "versão não encontrada:\n" + saida)
        return tuple(int(x) for x in m.groups()), saida

    def reiniciar(self, espera=360):
        """execute reboot, confirma e espera o 'login:' do boot seguinte."""
        self.ser.reset_input_buffer()
        self.enviar("execute reboot")
        _, i = self.ler_ate([CONFIRMA], 15)
        if i is None:
            raise FalhaFortiOS("execute reboot", "não pediu confirmação")
        self.enviar("y")
        _, i = self.ler_ate([LOGIN], espera)
        if i is None:
            raise FalhaLogin("O aparelho não voltou do reboot no prazo.")
