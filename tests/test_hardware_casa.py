"""Testes do hardware_casa.py e do teste_internet.py sem celular, sem rede e sem FortiGate."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import hardware_casa as hc  # noqa: E402
import teste_internet as ti  # noqa: E402

DUMPSYS = """Current Battery Service state:
  USB powered: true
  Max charging current: 0
  status: 2
  level: 39
  voltage: 3789
  temperature: 286
  current now: 123
@@Current temperatures from HAL:
	Temperature{mValue=30.5, mType=0, mName=AP, mStatus=0}
	Temperature{mValue=28.6, mType=2, mName=BAT, mStatus=0}
	Temperature{mValue=0.0, mType=2, mName=SUBBAT, mStatus=0}
Current cooling devices from HAL:
@@MemTotal:        3881020 kB
MemFree:          200000 kB
MemAvailable:    1468006 kB
"""


class TestCelular(unittest.TestCase):
    def test_leitura_rapida(self):
        with mock.patch.object(hc.threading, "Thread"):            # sem a linha de leitura de verdade
            celular = hc.Celular()
        celular._shell = lambda _comando, espera=15: DUMPSYS
        celular._ler_rapido()
        r = celular.rapido
        self.assertEqual((r["nivel"], r["corrente_ma"], r["volts"], r["carregando"]), ("39", "123", 3.789, True))
        self.assertEqual(r["temps"], {"AP": 30.5, "BAT": 28.6})     # o sensor que marca 0 nao aparece
        texto = "\n".join(celular.linhas())
        self.assertIn("+123 mA (0,47 W entrando na bateria)", texto)
        self.assertIn("processador 30,5 °C", texto)


class TestTesteDeInternet(unittest.TestCase):
    def test_linhas(self):
        r = {"quando": "03:12:10", "download": 610.2, "envio": 465.0,
             "parada": {"mediana": 8.2, "variacao": 1.8}, "baixando": {"mediana": 10.0},
             "enviando": {"mediana": 8.0}, "forti_baixando": 612.0, "forti_enviando": 470.0}
        texto = "\n".join(ti.linhas(r))
        self.assertIn("download    610 Mbit/s", texto)
        self.assertIn("+2 ms: ótima para jogar", texto)
        self.assertIn("o FortiGate viu na WAN1: 612", texto)

    def test_recusa_vira_frase(self):
        self.assertIn("Cloudflare recusou", ti.linhas({"erro": "a Cloudflare recusou (HTTP 429)"})[0])


if __name__ == "__main__":
    unittest.main()
