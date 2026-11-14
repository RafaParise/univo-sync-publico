"""Testes do projetos_infra.py sem rede e sem as pastas reais."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import projetos_infra as pi  # noqa: E402


class TestProjetosInfra(unittest.TestCase):
    def test_diagnostico(self):
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            (raiz / "a").mkdir()
            (raiz / "nova").mkdir()
            (raiz / "jogo").mkdir()
            pi.RAIZ_PROJETOS = raiz
            registro = [{"id": "a", "pasta": str(raiz / "a")}, {"id": "b", "pasta": str(raiz / "sumiu")}]
            infra = {"projetos": {"a": {}, "x": {}}}
            niveis = {n for n, _ in pi.diagnostico(registro, {"jogo": "não é projeto"}, infra, ["a", "nova", "jogo"])}
            self.assertEqual(niveis, {"NOVO", "QUEBRADO", "SEM PAPEL", "ÓRFÃO"})

    def test_caminhos_velhos(self):
        with tempfile.TemporaryDirectory() as d:
            md = Path(d) / "CLAUDE.md"
            md.write_text("Projeto em `C:\\Projetos\\nao-existe-mais-xyz` e C:\\Windows.", encoding="utf-8")
            achados = pi.caminhos_velhos([md])
            self.assertEqual(len(achados), 1)
            self.assertIn("nao-existe-mais-xyz", achados[0][1])

    def test_sites_e_dns(self):
        infra = {"servicos_do_hub": ["status"], "projetos": {"arena": {"site": True, "nome": "arena"}, "k": {}}}
        self.assertEqual(pi.sites(infra), ["arena", "status"])
        atuais = [{"hostname": "fortigate", "ip": "10.0.20.1"}, {"hostname": "arena", "ip": "10.0.20.100"}]
        novas = pi.mesclar_dns(atuais, ["arena", "status"], "10.0.20.50")
        self.assertEqual([(e["id"], e["hostname"], e["ip"]) for e in novas],
                         [(1, "fortigate", "10.0.20.1"), (2, "arena", "10.0.20.50"), (3, "status", "10.0.20.50")])


if __name__ == "__main__":
    unittest.main()
