"""
Testa o provisionamento contra um FortiGate SIMULADO (sem cabo, sem aparelho).
Rodar:  python -m unittest discover -s tests -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

import fortios_console as fc  # noqa: E402
import provisionar_fortigate as pv  # noqa: E402

ENV_TESTE = {
    "ADMIN_SENHA": "SenhaDeTeste#2026",
    "MAC_RYZEN": "00:11:22:33:44:55",
    "MAC_A12": "AA:BB:CC:DD:EE:FF",
}


class FortiFalso:
    """Imita o console do FortiOS o bastante para testar login, comandos, erros e reboot."""

    def __init__(self, versao="v6.0.18", erro_em=None, forca_troca=True):
        self.saida = bytearray()
        self.estado = "login"
        self.senha = ""
        self.forca_troca = forca_troca
        self.versao = versao
        self.erro_em = erro_em
        self.contexto = []
        self.modo = "switch"
        self.modo_salvo = "switch"
        self.pendente = None
        self.historico = []
        self.reboots = 0

    # interface do pyserial usada pelo Console
    @property
    def in_waiting(self):
        return len(self.saida)

    def read(self, n=1):
        pedaco = bytes(self.saida[:n])
        del self.saida[:n]
        return pedaco

    def write(self, dados):
        for linha in dados.decode().split("\r")[:-1]:
            self._linha(linha)
        return len(dados)

    def reset_input_buffer(self):
        self.saida.clear()

    def close(self):
        pass

    # simulação
    def _out(self, txt):
        self.saida += txt.encode()

    def _prompt(self):
        ctx = f" ({self.contexto[-1]})" if self.contexto else ""
        self._out(f"\r\nFGT60D0000000000{ctx} # ")

    def _linha(self, l):
        if self.estado == "login":
            if l == "":
                self._out("\r\nFGT60D0000000000 login: ")
            else:
                self.estado = "senha"
                self._out(l + "\r\nPassword: ")
            return
        if self.estado == "senha":
            if l == self.senha:
                if self.forca_troca and self.senha == "":
                    self.estado = "nova"
                    self._out("\r\nYou are forced to change your password.\r\nNew Password: ")
                    return
                self.estado = "cli"
                self._prompt()
            else:
                self.estado = "login"
                self._out("\r\nLogin incorrect\r\nFGT60D0000000000 login: ")
            return
        if self.estado == "nova":
            self.estado = "confirma"
            self._out("\r\nConfirm Password: ")
            return
        if self.estado == "confirma":
            self.senha = l
            self.estado = "cli"
            self._prompt()
            return
        if self.estado == "yn":
            self.estado = "cli"
            if l.lower().startswith("y") and self.pendente == "reboot":
                self.reboots += 1
                self.contexto = []
                self.modo = self.modo_salvo
                self.estado = "login"
                self._out("\r\nThe system is going down NOW !!\r\n...boot...\r\nFGT60D0000000000 login: ")
                return
            self._prompt()
            return
        # estado cli
        self.historico.append(l)
        self._out(l + "\r\n")
        if self.erro_em and self.erro_em in l:
            self._out("command parse error before 'x'\r\nCommand fail. Return code -61")
        elif l == "get system status":
            self._out(f"Version: FortiGate-60D {self.versao},build0000 (GA)")
        elif l.startswith("get system global | grep internal-switch-mode"):
            self._out(f"internal-switch-mode: {self.modo}")
        elif l in ("purge", "execute reboot"):
            self.estado = "yn"
            self.pendente = "reboot" if l == "execute reboot" else "purge"
            self._out("Do you want to continue? (y/n)")
            return
        elif l.startswith("execute api-user generate-key"):
            self._out("New API key: ChaveFalsa123\r\nNOTE: guarde a chave")
        elif l == "set internal-switch-mode interface":
            self.modo_salvo = "interface"
        elif l.startswith("config "):
            self.contexto.append(l.split()[-1])
        elif l.startswith("edit "):
            self.contexto.append(l.split(None, 1)[1].strip('"'))
        elif l in ("next", "end", "abort"):
            if self.contexto:
                self.contexto.pop()
            else:
                self._out("Unknown action 0")
        self._prompt()


def preparar(**kw):
    falso = FortiFalso(**kw)
    con = fc.Console(falso, pausa=0.01)
    texto = pv.MODELO.read_text(encoding="utf-8")
    secoes = pv.montar(pv.ler_modelo(texto), dict(ENV_TESTE))
    return falso, con, secoes


def silencio(*_):
    pass


class TestModelo(unittest.TestCase):
    def test_modelo_tem_secoes_esperadas(self):
        nomes = [s["nome"] for s in pv.ler_modelo(pv.MODELO.read_text(encoding="utf-8"))]
        for n in ("admin", "modo-interface", "interfaces", "dhcp", "politicas", "api-parise-core"):
            self.assertIn(n, nomes)
        self.assertLess(nomes.index("modo-interface"), nomes.index("interfaces"))
        self.assertLess(nomes.index("qos"), nomes.index("politicas"))

    def test_falta_mac_obrigatorio_para(self):
        env = dict(ENV_TESTE)
        del env["MAC_A12"]
        with self.assertRaises(ValueError):
            pv.montar(pv.ler_modelo(pv.MODELO.read_text(encoding="utf-8")), env)

    def test_mac_invalido_para(self):
        env = dict(ENV_TESTE, MAC_RYZEN="02-00-00-00-00-AA")
        with self.assertRaises(ValueError):
            pv.montar(pv.ler_modelo(pv.MODELO.read_text(encoding="utf-8")), env)

    def test_senha_fraca_para(self):
        env = dict(ENV_TESTE, ADMIN_SENHA="123")
        with self.assertRaises(ValueError):
            pv.montar(pv.ler_modelo(pv.MODELO.read_text(encoding="utf-8")), env)

    def test_opcional_sem_valor_e_pulada(self):
        secoes = pv.montar(pv.ler_modelo(pv.MODELO.read_text(encoding="utf-8")), dict(ENV_TESTE))
        controle = next(s for s in secoes if s["nome"] == "reserva-controle-arena")
        self.assertIn("MAC_CONTROLE_1", controle["pular"])

    def test_env_grava_e_troca(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / ".env"
            arq.write_text("A=1\nFORTIGATE_API_KEY=velha\n", encoding="utf-8")
            pv.gravar_env(arq, "FORTIGATE_API_KEY", "nova")
            self.assertEqual(pv.ler_env(arq), {"A": "1", "FORTIGATE_API_KEY": "nova"})


class TestFluxoSimulado(unittest.TestCase):
    def test_fluxo_completo(self):
        falso, con, secoes = preparar()
        resumo = pv.aplicar(con, secoes, ENV_TESTE, log=silencio)
        self.assertEqual(falso.reboots, 1)                     # separou as portas uma vez
        self.assertEqual(falso.modo, "interface")
        self.assertEqual(falso.senha, ENV_TESTE["ADMIN_SENHA"])  # troca obrigatória feita
        self.assertEqual(resumo["chave"], "ChaveFalsa123")
        self.assertIn("politicas", resumo["feitas"])
        self.assertIn("api-parise-core", resumo["feitas"])
        puladas = dict(resumo["puladas"])
        self.assertIn("netflow", puladas)                     # 6.0 < 6.2
        self.assertIn("reserva-controle-arena", puladas)      # sem MAC no .env
        self.assertEqual(falso.contexto, [])                  # terminou no prompt principal

    def test_segunda_rodada_nao_reinicia(self):
        falso, con, secoes = preparar()
        pv.aplicar(con, secoes, ENV_TESTE, log=silencio)
        _, _, secoes2 = preparar()
        resumo = pv.aplicar(con, secoes2, ENV_TESTE, log=silencio)
        self.assertEqual(falso.reboots, 1)
        self.assertIn("modo-interface", dict(resumo["puladas"]))

    def test_erro_em_secao_obrigatoria_para_tudo(self):
        falso, con, secoes = preparar(erro_em="set ip 10.0.30.1")
        with self.assertRaises(fc.FalhaFortiOS):
            pv.aplicar(con, secoes, ENV_TESTE, log=silencio)
        self.assertNotIn('edit "PC_RYZEN"', falso.historico)  # não chegou nos objetos
        self.assertEqual(falso.contexto, [])                  # saiu dos blocos com abort

    def test_erro_em_secao_opcional_segue(self):
        falso, con, secoes = preparar(erro_em="set fwgrp")
        resumo = pv.aplicar(con, secoes, ENV_TESTE, log=silencio)
        self.assertIn("api-parise-core", dict(resumo["falhas"]))
        self.assertIsNone(resumo["chave"])
        self.assertIn("politicas", resumo["feitas"])

    def test_versao_nova_aplica_netflow(self):
        _, con, secoes = preparar(versao="v6.2.16")
        resumo = pv.aplicar(con, secoes, ENV_TESTE, log=silencio)
        self.assertIn("netflow", resumo["feitas"])

    def test_mascara_segredos(self):
        self.assertEqual(pv.mascarar("set password X1 e Y2", ["X1", "Y2", None]),
                         "set password **** e ****")


if __name__ == "__main__":
    unittest.main()
