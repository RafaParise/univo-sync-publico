#!/usr/bin/env python3
"""
provisionar_fortigate.py
Aplica a configuração da Bancada-Sync no FortiGate 60D pelo console serial.

Modos:
  (sem opção)   mostra a configuração montada com o .env; não conecta em nada
  --verificar   conecta, faz login, lê a versão do FortiOS e diz o que seria
                aplicado ou pulado (não muda a configuração; se o FortiOS exigir
                trocar a senha no primeiro login, ela vira a ADMIN_SENHA)
  --aplicar     aplica de verdade (pede para digitar SIM, a não ser com --sim)

Modelo: config/fortigate-bancada.conf. Valores: .env (veja .env.example).
Log da sessão em logs/, com senha e chave mascaradas.
"""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

PASTA = Path(__file__).resolve().parent
RAIZ = PASTA.parent
sys.path.insert(0, str(PASTA))
import fortios_console as fc  # noqa: E402

MODELO = RAIZ / "config" / "fortigate-bancada.conf"
ENV = RAIZ / ".env"
LOGS = RAIZ / "logs"

CABECALHO = re.compile(r"^###\s*SECAO\s+(\S+)(.*)$")
VAR = re.compile(r"\$\{(\w+)\}")
MAC = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
SENHA_OK = re.compile(r"^[^\s\"'\\]{8,64}$")


# ---------- .env ----------
def ler_env(caminho):
    """Lê CHAVE=valor do .env (linhas com # são comentário)."""
    valores = {}
    if caminho.exists():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                k, v = linha.split("=", 1)
                valores[k.strip()] = v.strip().strip('"').strip("'")
    return valores


def gravar_env(caminho, chave, valor):
    """Grava ou troca CHAVE=valor no .env (que não vai para o git)."""
    linhas = caminho.read_text(encoding="utf-8").splitlines() if caminho.exists() else []
    linhas = [l for l in linhas if not l.startswith(chave + "=")]
    linhas.append(f"{chave}={valor}")
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


# ---------- modelo ----------
def ler_modelo(texto):
    """Divide o modelo em seções: nome, versão mínima, opcional, reboot e linhas."""
    secoes = []
    for linha in texto.splitlines():
        limpa = linha.strip()
        m = CABECALHO.match(limpa)
        if m:
            marcas = m.group(2)
            vmin = re.search(r"min=(\d+)\.(\d+)", marcas)
            secoes.append({
                "nome": m.group(1),
                "min": (int(vmin.group(1)), int(vmin.group(2))) if vmin else (0, 0),
                "opcional": "opcional" in marcas,
                "reboot": "reboot" in marcas,
                "linhas": [],
                "pular": None,
            })
        elif secoes and limpa and not limpa.startswith("#"):
            secoes[-1]["linhas"].append(limpa)
    return secoes


def montar(secoes, env):
    """Troca ${VAR} pelo .env. Seção opcional sem valor é pulada; obrigatória sem valor para tudo."""
    erros = []
    senha = env.get("ADMIN_SENHA", "")
    if not SENHA_OK.match(senha):
        erros.append("ADMIN_SENHA no .env: de 8 a 64 caracteres, sem espaço, aspas ou barra invertida.")
    for s in secoes:
        faltando, invalidos = set(), set()
        for l in s["linhas"]:
            for nome in VAR.findall(l):
                v = env.get(nome, "")
                if not v:
                    faltando.add(nome)
                elif nome.startswith("MAC_") and not MAC.match(v):
                    invalidos.add(f"{nome}={v} (use o formato AA:BB:CC:DD:EE:FF)")
        if invalidos:
            erros.append(f"[{s['nome']}] MAC inválido: " + ", ".join(sorted(invalidos)))
        if faltando:
            if s["opcional"]:
                s["pular"] = "falta no .env: " + ", ".join(sorted(faltando))
            else:
                erros.append(f"[{s['nome']}] falta no .env: " + ", ".join(sorted(faltando)))
        s["linhas"] = [VAR.sub(lambda m: env.get(m.group(1), ""), l) for l in s["linhas"]]
    if erros:
        raise ValueError("\n".join(erros))
    return secoes


def mascarar(texto, segredos):
    for s in segredos:
        if s:
            texto = texto.replace(s, "****")
    return texto


# ---------- execução ----------
def entrar(con, senha, log):
    """Login (troca a senha de fábrica se o FortiOS pedir) e desliga a paginação."""
    r = con.login("admin", ["", senha], nova_senha=senha)
    log(f"[login] {r}")
    for c in ("config system console", "set output standard", "end"):
        con.comando(c)


def ja_em_modo_interface(con):
    saida = con.comando("get system global | grep internal-switch-mode")
    if "internal-switch-mode" not in saida:
        raise fc.FalhaFortiOS("get system global", "este FortiOS não mostra internal-switch-mode; "
                              "confira o modo das portas à mão antes de seguir.\n" + saida)
    return "interface" in saida


def planejar(secoes, versao):
    """Marca o que será pulado por versão. Devolve a lista de (nome, motivo) puladas."""
    puladas = []
    for s in secoes:
        if s["pular"]:
            puladas.append((s["nome"], s["pular"]))
        elif versao[:2] < s["min"]:
            s["pular"] = f"exige FortiOS {s['min'][0]}.{s['min'][1]} ou mais novo"
            puladas.append((s["nome"], s["pular"]))
    return puladas


def aplicar(con, secoes, env, log=print, gerar_chave=True):
    """Aplica as seções em ordem. Devolve um resumo; erro em seção obrigatória levanta FalhaFortiOS."""
    senha = env["ADMIN_SENHA"]
    entrar(con, senha, log)
    versao, _ = con.versao()
    log(f"[versão] FortiOS {'.'.join(map(str, versao))}")
    resumo = {"versao": versao, "feitas": [], "puladas": planejar(secoes, versao),
              "falhas": [], "chave": None}
    for s in secoes:
        if s["pular"]:
            continue
        if s["nome"] == "modo-interface" and ja_em_modo_interface(con):
            resumo["puladas"].append((s["nome"], "o aparelho já está em modo interface"))
            continue
        log(f"[seção] {s['nome']} ({len(s['linhas'])} linhas)")
        try:
            for l in s["linhas"]:
                con.comando(l, confirmar=True)
        except fc.FalhaFortiOS as e:
            con.sair_para_raiz()
            if s["opcional"]:
                log(f"[aviso] seção opcional '{s['nome']}' recusada; seguindo.")
                resumo["falhas"].append((s["nome"], str(e)))
                continue
            raise
        resumo["feitas"].append(s["nome"])
        if s["reboot"]:
            log("[reboot] reiniciando para separar as portas (uns 3 minutos)...")
            con.reiniciar()
            entrar(con, senha, log)
    if gerar_chave and "api-parise-core" in resumo["feitas"]:
        saida = con.comando("execute api-user generate-key claude_parise_core", confirmar=True)
        m = re.search(r"New API key:\s*(\S+)", saida, re.I)
        if m:
            resumo["chave"] = m.group(1)
        else:
            resumo["falhas"].append(("chave-api", "o FortiOS não devolveu a chave:\n" + saida[-300:]))
    return resumo


def imprimir_resumo(resumo, log=print):
    log("\n========== RESUMO ==========")
    log(f"FortiOS: {'.'.join(map(str, resumo['versao']))}")
    log("Aplicadas: " + (", ".join(resumo["feitas"]) or "nenhuma"))
    for nome, motivo in resumo["puladas"]:
        log(f"Pulada:   {nome} ({motivo})")
    for nome, erro in resumo["falhas"]:
        log(f"FALHOU:   {nome}\n{erro}\n")
    if "admin" not in resumo["feitas"]:
        log("ATENÇÃO: a seção 'admin' não rodou. Confira se o admin tem senha antes de ligar a WAN.")


def mostrar(secoes, env):
    for s in secoes:
        marcas = [m for m, ok in (("opcional", s["opcional"]), ("reboot", s["reboot"])) if ok]
        if s["min"] != (0, 0):
            marcas.append(f"min={s['min'][0]}.{s['min'][1]}")
        extra = f"  [{' '.join(marcas)}]" if marcas else ""
        print(f"\n### {s['nome']}{extra}" + (f"  -> PULADA: {s['pular']}" if s["pular"] else ""))
        for l in s["linhas"]:
            print("   " + mascarar(l, [env.get("ADMIN_SENHA")]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Provisiona o FortiGate 60D da bancada pelo console.")
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument("--verificar", action="store_true", help="conecta e mostra o plano, sem aplicar")
    modo.add_argument("--aplicar", action="store_true", help="aplica a configuração")
    ap.add_argument("--porta", help="porta COM (padrão: PORTA_SERIAL do .env ou detecção)")
    ap.add_argument("--sim", action="store_true", help="não pede confirmação antes de aplicar")
    ap.add_argument("--env", default=str(ENV))
    ap.add_argument("--modelo", default=str(MODELO))
    args = ap.parse_args(argv)

    env = ler_env(Path(args.env))
    try:
        secoes = montar(ler_modelo(Path(args.modelo).read_text(encoding="utf-8")), env)
    except ValueError as e:
        print(f"Corrija o .env ({args.env}):\n{e}")
        return 1

    if not (args.verificar or args.aplicar):
        mostrar(secoes, env)
        print("\nNada foi enviado. Use --verificar (conecta e confere) ou --aplicar.")
        return 0

    porta = args.porta or env.get("PORTA_SERIAL") or fc.achar_porta()
    if not porta:
        print("Nenhum cabo de console encontrado. Rode scripts/diagnostico_usb.ps1.")
        return 2
    if args.aplicar and not args.sim:
        if input(f"Aplicar a configuração no FortiGate pela {porta}? Digite SIM: ").strip() != "SIM":
            print("Cancelado.")
            return 0

    con = fc.Console.abrir(porta, eco=lambda t: print(t, end="", flush=True))
    segredos = [env.get("ADMIN_SENHA")]
    codigo = 0
    try:
        if args.verificar:
            entrar(con, env["ADMIN_SENHA"], print)
            versao, _ = con.versao()
            print(f"\nFortiOS {'.'.join(map(str, versao))}")
            print("Portas já separadas (modo interface):", ja_em_modo_interface(con))
            for nome, motivo in planejar(secoes, versao):
                print(f"Seria pulada: {nome} ({motivo})")
        else:
            resumo = aplicar(con, secoes, env)
            if resumo["chave"]:
                gravar_env(Path(args.env), "FORTIGATE_API_KEY", resumo["chave"])
                segredos.append(resumo["chave"])
                print("\nChave da API gravada no .env como FORTIGATE_API_KEY.")
            imprimir_resumo(resumo)
    except (fc.FalhaFortiOS, fc.FalhaLogin) as e:
        print(f"\nPAROU: {e}")
        codigo = 3
    finally:
        LOGS.mkdir(exist_ok=True)
        arq = LOGS / f"fortigate-{datetime.now():%Y%m%d-%H%M%S}.log"
        arq.write_text(mascarar("".join(con.transcricao), segredos), encoding="utf-8")
        print(f"\nLog: {arq}")
        con.fechar()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
