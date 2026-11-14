#!/usr/bin/env python3
"""
projetos_infra.py - liga TODOS os projetos do Rafael à infraestrutura da bancada.

Fonte única da lista de projetos: o REGISTRO do parise-core-windows (bin/projetos.py),
o mesmo que os agentes usam. Aqui fica só o papel de rede (config/projetos-infra.json).

  python scripts/projetos_infra.py verificar   pastas sem registro, registro sem pasta,
                                               caminhos velhos nos CLAUDE.md, papel de cada um
  python scripts/projetos_infra.py dns         <nome>.bancada.lan -> HUB_IP no FortiGate
  python scripts/projetos_infra.py registrar   cadastra cada projeto no parise-core

.env: HUB_IP (máquina da parise-infra), PARISE_TOKEN, PARISE_CORE_URL (opcional),
e os do FortiGate (FORTIGATE_IP, FORTIGATE_CERT_SHA256, ADMIN_SENHA).
"""
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA))
from fortigate_api import ErroAPI, FortiAPI  # noqa: E402
from provisionar_fortigate import ENV, ler_env  # noqa: E402

RAIZ_PROJETOS = Path(os.environ.get("PROJETOS_DIR", r"C:\Projetos"))
REGISTRO_PY = Path(os.environ.get("PROJETOS_REGISTRO", r"C:\Projetos\parise-core-windows\bin\projetos.py"))
INFRA = PASTA.parent / "config" / "projetos-infra.json"
CLAUDE_MDS = [Path.home() / ".claude" / "CLAUDE.md"] + sorted(RAIZ_PROJETOS.glob("*/CLAUDE.md"))
CAMINHO = re.compile(r"C:\\Projetos\\[^`'\"\n,;)*{]+")


def carregar_registro(caminho=REGISTRO_PY):
    spec = importlib.util.spec_from_file_location("registro_projetos", caminho)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.REGISTRO, getattr(mod, "FORA_DO_REGISTRO", {})


def diagnostico(registro, fora, infra, pastas):
    """Lista de (nível, texto). pastas = nomes das pastas em C:\\Projetos."""
    achados = []
    registradas = {Path(r["pasta"]).resolve() for r in registro}
    fora_min = {k.lower() for k in fora}
    for nome in sorted(pastas):
        p = (RAIZ_PROJETOS / nome).resolve()
        if p not in registradas and nome.lower() not in fora_min and not nome.startswith((".", "_")):
            achados.append(("NOVO", f"{nome}: pasta sem registro (acrescente no REGISTRO ou no FORA_DO_REGISTRO)"))
    for r in registro:
        if not Path(r["pasta"]).is_dir():
            achados.append(("QUEBRADO", f"{r['id']}: a pasta {r['pasta']} não existe"))
        if r["id"] not in infra["projetos"]:
            achados.append(("SEM PAPEL", f"{r['id']}: sem papel na infra (config/projetos-infra.json)"))
    ids = {r["id"] for r in registro}
    for pid in infra["projetos"]:
        if pid not in ids:
            achados.append(("ÓRFÃO", f"{pid}: está na infra mas não no REGISTRO"))
    return achados


def caminhos_velhos(arquivos=CLAUDE_MDS):
    """Caminhos C:\\Projetos\\... citados nos CLAUDE.md que não existem mais."""
    achados = []
    for arq in arquivos:
        try:
            texto = arq.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in sorted(set(CAMINHO.findall(texto))):
            caminho = m.rstrip(" .:")
            if not Path(caminho).exists():
                achados.append(("VELHO", f"{arq}: cita {caminho}, que não existe"))
    return achados


def sites(infra):
    """Nomes que vão para o DNS: serviços do hub + projetos com site=true."""
    nomes = list(infra.get("servicos_do_hub", []))
    nomes += [p.get("nome", pid) for pid, p in infra["projetos"].items() if p.get("site")]
    return sorted(set(nomes))


def mesclar_dns(atuais, nomes, ip):
    """Mantém as entradas que não são de site e põe/atualiza as dos sites no IP do hub."""
    fica = [e for e in atuais if e.get("hostname") not in nomes]
    novas = fica + [{"hostname": n, "type": "A", "ip": ip} for n in nomes]
    return [{"id": i + 1, "hostname": e["hostname"], "type": e.get("type", "A"), "ip": e["ip"]}
            for i, e in enumerate(novas)]


def cmd_verificar(registro, fora, infra):
    pastas = [p.name for p in RAIZ_PROJETOS.iterdir() if p.is_dir()]
    achados = diagnostico(registro, fora, infra, pastas) + caminhos_velhos()
    for r in registro:
        papel = infra["projetos"].get(r["id"], {})
        site = f"  -> http://{papel.get('nome', r['id'])}.{infra['dominio']}" if papel.get("site") else ""
        print(f"  {r['id']:<18} {papel.get('tipo', '?'):<11}{' (público)' if r.get('publico') else ''}{site}")
    print()
    for nivel, texto in achados:
        print(f"[{nivel}] {texto}")
    print("Tudo em ordem." if not achados else f"\n{len(achados)} ponto(s) para resolver.")
    return 1 if any(n in ("QUEBRADO", "ÓRFÃO") for n, _ in achados) else 0


def cmd_dns(infra, env):
    ip = env.get("HUB_IP")
    if not ip:
        print("Defina HUB_IP no .env (IP da máquina que roda a parise-infra).")
        return 1
    api = FortiAPI(env.get("FORTIGATE_IP", "10.0.20.1"), impressao=env.get("FORTIGATE_CERT_SHA256"))
    api.login("admin", env["ADMIN_SENHA"])
    try:
        zona = api.ler("system/dns-database/bancada")[0]
        entradas = mesclar_dns(zona.get("dns-entry", []), sites(infra), ip)
        api.ajustar("system/dns-database/bancada", {"dns-entry": entradas})
    finally:
        api.logout()
    for e in entradas:
        print(f"  {e['hostname']}.{infra['dominio']} -> {e['ip']}")
    return 0


def cmd_registrar(registro, infra, env):
    url = env.get("PARISE_CORE_URL") or f"http://parise-core.{infra['dominio']}"
    token = env.get("PARISE_TOKEN", "")
    if not token:
        print("Falta PARISE_TOKEN no .env (o bootstrap.sh gera).")
        return 1
    erros = 0
    for r in registro:
        papel = infra["projetos"].get(r["id"], {})
        corpo = {"name": r["id"], "kind": papel.get("tipo", "outro"),
                 "url": f"http://{papel.get('nome', r['id'])}.{infra['dominio']}" if papel.get("site") else "",
                 "description": papel.get("descricao", r.get("nome", ""))}
        req = urllib.request.Request(f"{url}/api/modules", data=json.dumps(corpo).encode(), method="PUT",
                                     headers={"Content-Type": "application/json", "X-Parise-Token": token})
        try:
            urllib.request.urlopen(req, timeout=10).read()
            print(f"  [ok] {r['id']}")
        except (urllib.error.URLError, OSError) as e:
            print(f"  [falhou] {r['id']}: {e}")
            erros += 1
    return 1 if erros else 0


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    cmd = argv[0] if argv else "verificar"
    registro, fora = carregar_registro()
    infra = json.loads(INFRA.read_text(encoding="utf-8"))
    env = ler_env(ENV)
    try:
        if cmd == "verificar":
            return cmd_verificar(registro, fora, infra)
        if cmd == "dns":
            return cmd_dns(infra, env)
        if cmd == "registrar":
            return cmd_registrar(registro, infra, env)
    except ErroAPI as e:
        print(f"FortiGate: {e}")
        return 3
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
