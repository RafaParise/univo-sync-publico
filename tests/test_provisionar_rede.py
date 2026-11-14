"""
Testa o provisionar_rede.py sem aparelho: regras, VIPs, passos e a conferência contra uma API FALSA.
Nada aqui abre rede, serial ou SSH.
Rodar:  python -m unittest discover -s tests -v
"""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

import provisionar_rede as pr  # noqa: E402

ENV_TESTE = {"ADMIN_SENHA": "SenhaDeTeste#2026", "MAC_RYZEN": "00:11:22:33:44:55",
             "MAC_A12": "AA:BB:CC:DD:EE:FF"}


class APIFalsa:
    """Guarda o que seria lido e gravado; ajustar/gravar/apagar só anotam."""

    def __init__(self, uplink_atual="wan1", portas=("internal1", "internal3", "internal4", "internal5",
                                                       "internal6", "internal7")):
        self.dados = {
            "system/virtual-switch/internal": [{"port": [{"name": p} for p in portas]}],
            "system/interface/internal": [{"ip": "10.0.20.1 255.255.255.0"}],
            "system/interface/internal3": [{"mode": "dhcp", "ip": "192.168.18.2 255.255.255.0"}],
            "firewall/policy": [dict(r) for r in pr.montar_regras(uplink_atual)],
            "firewall/vip": [{"name": "ARENA_REPASSE_VIP", "extintf": uplink_atual},
                             {"name": "ARENA_REPASSE_VIP_PC", "extintf": uplink_atual}],
        }
        self.escritas = []

    def ler(self, caminho):
        return self.dados.get(caminho, [])

    def ajustar(self, caminho, dados):
        self.escritas.append(("ajustar", caminho, dados))

    def gravar(self, caminho, chave, dados):
        self.escritas.append(("gravar", caminho, chave))

    def apagar(self, caminho, chave):
        self.escritas.append(("apagar", caminho, chave))


def passo(nome_parcial, uplink="internal3"):        # a maioria dos testes de passo é da opção B (porta 3)
    for nome, _, f in pr.montar_passos(ENV_TESTE, uplink):
        if nome_parcial in nome:
            return f
    raise AssertionError(f"passo '{nome_parcial}' não existe")


class TestDesenho(unittest.TestCase):
    def test_padrao_e_a_wan1(self):
        # Desde 12/11/2026 (~18h50) a ONT Huawei está na WAN1; a porta 3 (internal3) ficou como opção B.
        self.assertEqual(pr.UPLINK_PADRAO, "wan1")
        self.assertIn("internal3", pr.UPLINKS)

    def test_padrao_deixa_a_porta_3_na_lan1(self):
        self.assertEqual(pr.portas_fora_do_switch(pr.UPLINK_PADRAO), ["internal2"])
        saidas = {r["dstintf"][0]["name"] for r in pr.REGRAS if r["name"].endswith("_PARA_INTERNET")}
        self.assertEqual(saidas, {"wan1"})

    def test_regras_sem_wan1_no_uplink_novo(self):
        for r in pr.montar_regras("internal3"):
            intfs = {x["name"] for x in r["srcintf"] + r["dstintf"]}
            self.assertNotIn("wan1", intfs, r["name"])
        saidas = {r["name"]: r["dstintf"][0]["name"] for r in pr.montar_regras("internal3")}
        for nome in ("PC_PARA_INTERNET", "A12_PARA_INTERNET", "PC_DMZ_PARA_INTERNET"):
            self.assertEqual(saidas[nome], "internal3")

    def test_regras_internas_nao_mudam(self):
        novas = {r["name"]: r for r in pr.montar_regras("internal3")}
        velhas = {r["name"]: r for r in pr.montar_regras("wan1")}
        for nome in ("PC_PARA_A12_ADB", "ARENA_CONTROLES_PARA_PC", "CONTROLES_PARA_REPASSE_ARENA"):
            self.assertEqual(novas[nome], velhas[nome])
        self.assertEqual(novas["ARENA_CONTROLES_PARA_PC"]["traffic-shaper"], "ARENA_INPUT_SHAPER")

    def test_nat_nas_saidas(self):
        for r in pr.montar_regras("internal3"):
            if r["name"].endswith("_PARA_INTERNET"):
                self.assertEqual(r.get("nat"), "enable", r["name"])

    def test_vips_no_uplink(self):
        cli = "\n".join(pr.cli_regras("internal3"))
        self.assertEqual(cli.count('set extintf "internal3"'), 2)
        self.assertNotIn('"wan1"', cli)
        self.assertIn("set extport 55440", cli)
        self.assertIn("set extport 55441", cli)
        self.assertLess(cli.index("config firewall vip"), cli.index("config firewall policy"))

    def test_uplink_wan1_e_o_desenho_antigo(self):
        cli = "\n".join(pr.cli_regras("wan1"))
        self.assertNotIn("internal3", cli)
        self.assertEqual(pr.portas_fora_do_switch("wan1"), ["internal2"])


class TestPassos(unittest.TestCase):
    def test_tira_a_porta_3_do_switch_e_mantem_a_1(self):
        api = APIFalsa()
        passo("do switch da LAN1")(api)
        (_, caminho, dados), = api.escritas
        portas = [p["name"] for p in dados["port"]]
        self.assertEqual(caminho, "system/virtual-switch/internal")
        self.assertIn("internal1", portas)
        self.assertNotIn("internal3", portas)

    def test_switch_ja_separado_nao_grava(self):
        api = APIFalsa(portas=("internal1", "internal4"))
        passo("do switch da LAN1")(api)
        self.assertEqual(api.escritas, [])

    def test_uplink_em_dhcp_so_com_ping(self):
        api = APIFalsa()
        passo("(DHCP)")(api)
        uplink = [d for _, c, d in api.escritas if c == "system/interface/internal3"]
        self.assertEqual(uplink, [{"mode": "dhcp", "allowaccess": "ping", "defaultgw": "enable"}])

    def test_distancias(self):
        api = APIFalsa()
        passo("distâncias")(api)
        dist = {c.rsplit("/", 1)[1]: d.get("distance") for _, c, d in api.escritas}
        self.assertEqual((dist["internal3"], dist["wan1"], dist["wan2"]), (10, 15, 20))

    def test_distancias_no_padrao_wan1(self):
        api = APIFalsa()
        passo("distâncias", uplink="wan1")(api)
        dist = {c.rsplit("/", 1)[1]: d.get("distance") for _, c, d in api.escritas}
        self.assertEqual((dist["wan1"], dist["wan2"]), (10, 20))
        self.assertNotIn("internal3", dist)

    def test_padrao_wan1_deixa_a_porta_3_no_switch(self):
        api = APIFalsa(portas=("internal1", "internal2", "internal3", "internal4"))
        passo("do switch da LAN1", uplink="wan1")(api)
        (_, caminho, dados), = api.escritas                  # só a porta 2 sai
        portas = [p["name"] for p in dados["port"]]
        self.assertEqual(caminho, "system/virtual-switch/internal")
        self.assertIn("internal3", portas)
        self.assertNotIn("internal2", portas)


class TestConferencia(unittest.TestCase):
    def test_aparelho_antigo_pede_restore(self):
        api = APIFalsa(uplink_atual="wan1")
        faltas = pr.divergencias(api, "internal3")
        self.assertTrue(pr.precisa_restore(api, "internal3"))
        self.assertTrue(any("PC_PARA_INTERNET" in f for f in faltas))
        self.assertTrue(any(f.startswith("VIP ARENA_REPASSE_VIP") for f in faltas))
        self.assertEqual(api.escritas, [])                      # conferir só lê

    def test_aparelho_de_hoje_bate_com_o_padrao(self):
        # Situação conferida em 12/11/2026: regras e VIPs na WAN1 (provisionar_rede.py --conferir --uplink wan1).
        api = APIFalsa(uplink_atual="wan1")
        self.assertEqual(pr.divergencias(api, pr.UPLINK_PADRAO), [])
        self.assertFalse(pr.precisa_restore(api, pr.UPLINK_PADRAO))

    def test_aparelho_em_dia_nao_pede_restore(self):
        api = APIFalsa(uplink_atual="internal3")
        self.assertEqual(pr.divergencias(api, "internal3"), [])

    def test_conferir_nao_grava(self):
        api = APIFalsa()
        with redirect_stdout(io.StringIO()):
            pr.conferir(api, "internal3", print)
        self.assertEqual(api.escritas, [])


class TestPrincipal(unittest.TestCase):
    def rodar(self, *args):
        saida = io.StringIO()
        with mock.patch.object(pr, "ler_env", return_value=dict(ENV_TESTE)), \
                mock.patch.object(pr, "FortiAPI", side_effect=AssertionError("conectou!")), \
                redirect_stdout(saida):
            rc = pr.main(list(args))
        return rc, saida.getvalue()

    def test_sem_argumento_nao_conecta(self):
        rc, saida = self.rodar()
        self.assertEqual(rc, 0)
        self.assertIn("Uplink (internet): wan1", saida)
        self.assertIn("Nada foi enviado", saida)

    def test_mostrar_cli_nao_conecta(self):
        rc, saida = self.rodar("--mostrar-cli")
        self.assertEqual(rc, 0)
        self.assertIn('set extintf "wan1"', saida)
        self.assertNotIn("internal3", saida)

    def test_opcao_b_pela_linha_de_comando(self):
        rc, saida = self.rodar("--uplink", "internal3", "--mostrar-cli")
        self.assertEqual(rc, 0)
        self.assertIn('set extintf "internal3"', saida)

    def test_aplicar_e_conferir_juntos_recusado(self):
        with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                pr.main(["--aplicar", "--conferir"])


if __name__ == "__main__":
    unittest.main()
