"""Testes do sentinela do A12 que não precisam do celular. Rodar: python -m unittest discover -s tests -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import sentinela_a12 as s  # noqa: E402

# Cabeçalho + 4 linhas: ADB do PC (10.0.20.100), ADB de intruso (10.0.30.7),
# ADB em escuta (estado 0A) e SSH do Termux (porta 8022)
TCP = """  sl  local_address rem_address   st tx_queue rx_queue
   0: 320A000A:15B3 6414000A:C350 01 00000000:00000000
   1: 320A000A:15B3 071E000A:C351 01 00000000:00000000
   2: 00000000:15B3 00000000:0000 0A 00000000:00000000
   3: 320A000A:1F56 6414000A:C352 01 00000000:00000000
"""
TCP6 = """  sl  local_address                         remote_address                        st
   0: 0000000000000000FFFF0000320A000A:15B3 0000000000000000FFFF00006414000A:D000 01
"""


class TestSentinela(unittest.TestCase):
    def test_hex_para_ip(self):
        self.assertEqual(s.hex_para_ip("6414000A"), "10.0.20.100")
        self.assertEqual(s.hex_para_ip("0000000000000000FFFF00006414000A"), "10.0.20.100")

    def test_so_conexoes_estabelecidas_na_5555(self):
        self.assertEqual(s.ips_na_porta(TCP), {"10.0.20.100", "10.0.30.7"})

    def test_ipv6_mapeado(self):
        self.assertEqual(s.ips_na_porta(TCP6), {"10.0.20.100"})

    def test_gateway_provavel(self):
        """Sem /proc/net/route (o Android 12 nega ao Termux): o FortiGate da conf, senão o .1 da rede do Wi-Fi."""
        from unittest import mock
        with mock.patch.object(s.Path, "read_text", side_effect=PermissionError):
            self.assertEqual(s.gateway_provavel({"FORTIGATE_IP": "10.0.10.1"}, "10.0.10.50"), "10.0.10.1")
            self.assertEqual(s.gateway_provavel({}, "192.168.18.4"), "192.168.18.1")
            self.assertIsNone(s.gateway_provavel({}, None))

    def test_conf_sem_campos_so_telemetria(self):
        """Sem a conf do FortiGate (o A12 fora da DMZ), o vigia roda so medindo; religar a regra, nao."""
        from unittest import mock
        with mock.patch.object(s, "amostrar") as amostrar, mock.patch.object(s, "regra_adb") as regra:
            self.assertEqual(s.main(["--conf", "nao-existe.env", "--uma-vez"]), 0)
            self.assertEqual(amostrar.call_count, 1)
            regra.assert_not_called()
        self.assertEqual(s.main(["--conf", "nao-existe.env", "--liberar"]), 1)


class TestBot(unittest.TestCase):
    def test_comandos_sem_rede(self):
        import bot_chat_a12 as b
        self.assertIsNone(b.responder("bom dia", {}))
        self.assertIn("não foi implementado", b.responder("!farol_sed", {}))
        self.assertIn("!status_lab", b.responder("!AJUDA", {}))

    def test_status_sem_conf_nao_quebra(self):
        import bot_chat_a12 as b
        self.assertIn("FortiGate: sem resposta", b.status_lab({}))


if __name__ == "__main__":
    unittest.main()
