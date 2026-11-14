"""Testes do syslog_eventos.py: o que entra e, principalmente, o que NUNCA entra (MAC, DHCP, LAN2, série)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import syslog_eventos as se  # noqa: E402

ENLACE = ('<189>date=2026-11-14 time=02:46:21 devname="FG60D-BANCADA" devid="FGT60D0000000000" logid="0100020015" '
          'type="event" subtype="system" level="notice" vd="root" logdesc="Interface status changed" '
          'action="interface-stat-change" status="DOWN" msg="Link monitor: Interface dmz was turned down"')
DHCP = ('<190>date=2026-11-14 time=02:50:00 devid="FGT60D0000000000" type="event" subtype="dhcp" level="information" '
        'logdesc="DHCP Ack log" mac="02:00:00:00:00:01" ip=10.0.30.12 hostname="celular-do-aluno"')
TRAFEGO = '<189>date=2026-11-14 time=02:51:00 type="traffic" subtype="forward" srcip=10.0.30.12 dstip=1.1.1.1'


class TestSyslogEventos(unittest.TestCase):
    def test_enlace_entra_sem_serie_nem_nome(self):
        evento = se.filtrar(se.ler_registro(ENLACE))
        self.assertEqual(evento["logdesc"], "Interface status changed")
        self.assertEqual(evento["status"], "DOWN")
        self.assertIn("dmz", evento["msg"])
        self.assertNotIn("devid", evento)
        self.assertNotIn("devname", evento)

    def test_dhcp_e_trafego_nunca_entram(self):
        self.assertIsNone(se.filtrar(se.ler_registro(DHCP)))
        self.assertIsNone(se.filtrar(se.ler_registro(TRAFEGO)))

    def test_mac_e_lan2_no_texto_viram_oculto(self):
        linha = ('type="event" subtype="system" logdesc="x" '
                 'msg="aparelho 02:00:00:00:00:02 em 10.0.30.40 e o PC 10.0.20.100"')
        msg = se.filtrar(se.ler_registro(linha))["msg"]
        self.assertNotIn("02:00:00", msg)
        self.assertNotIn("10.0.30.40", msg)
        self.assertIn("10.0.20.100", msg)
        self.assertEqual(msg.count("[oculto]"), 2)


if __name__ == "__main__":
    unittest.main()
