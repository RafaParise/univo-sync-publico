"""Instala, atualiza ou confere o sentinela do A12 (Termux), pelo cabo USB.

O sentinela (scripts\\sentinela_a12.py) mede a saude do proprio celular (temperatura, bateria, memoria, tempo ligado,
ping ao gateway) e guarda uma amostra por minuto em /sdcard/parise-sync/telemetria/amostras.jsonl, que o
scripts\\telemetria.py do PC le pelo cabo e o Qwen do A12 le direto. Com a conf do FortiGate no celular
(~/.parise-sentinela.env), ele tambem desliga a regra do ADB por calor ou acesso estranho; sem a conf (o A12 ainda
fora da DMZ, 12/11/2026), roda so a telemetria. A senha da API NAO vai para o celular por este script.

Uso (no PC, com o celular no cabo e a depuracao USB ligada):
    python scripts\\instalar_sentinela_a12.py instalar   copia o sentinela, a API do FortiGate, o comando "sentinela"
                                                        e o script de ligar; liga e mostra a primeira amostra
    python scripts\\instalar_sentinela_a12.py estado     se esta ligado e as ultimas amostras
    python scripts\\instalar_sentinela_a12.py desligar

Fala com o Termux pelo scripts\\termux.ps1 do projeto Android Embeeded (SSH pelo cabo, so 127.0.0.1), como o
repasse_a12.py."""
import argparse
import secrets
import subprocess
import sys
from pathlib import Path

from repasse_a12 import BOOT, KIT, TERMUX, comando, termux

AQUI = Path(__file__).resolve().parent
PROGRAMAS = (AQUI / "sentinela_a12.py", AQUI / "fortigate_api.py", AQUI / "ligar_pc.py",
             AQUI / "proxy_compartilhado.py")      # o proxy do hotspot (comando "compartilhar"), 13/11/2026
COMANDO = KIT / "bin" / "sentinela"
LIGAR_PC = AQUI / "ligar-pc"          # o comando do Wake-on-LAN (13/11/2026)
COMPARTILHAR = AQUI / "compartilhar"   # o comando do proxy do hotspot (13/11/2026)


def instalar():
    for arquivo in (*PROGRAMAS, COMANDO, LIGAR_PC, COMPARTILHAR, BOOT, TERMUX):
        if not arquivo.is_file():
            print("Falta %s" % arquivo)
            return 1
    ok, texto = comando("mkdir -p ~/parise-sync ~/bin ~/.termux/boot /sdcard/parise-sync/telemetria")
    if not ok:
        print("Nao alcancei o Termux pelo cabo:\n" + texto)
        return 2
    copias = [(p, "~/parise-sync/") for p in PROGRAMAS] + [(COMANDO, "~/bin/"), (LIGAR_PC, "~/bin/"), (COMPARTILHAR, "~/bin/"),
                                                            (BOOT, "~/.termux/boot/")]
    for origem, destino in copias:
        ok, texto = termux("-Copiar", str(origem), "-Para", destino)
        print("copiado %s -> %s: %s" % (origem.name, destino, "ok" if ok else texto))
        if not ok:
            return 1
    ok, texto = comando("chmod +x ~/bin/sentinela ~/bin/ligar-pc ~/bin/compartilhar ~/.termux/boot/iniciar-a12; "
                        "~/bin/ligar-pc servir-desligar >/dev/null; ~/bin/ligar-pc servir-ligar; "
                        "~/bin/sentinela desligar >/dev/null; "
                        "~/bin/sentinela ligar && sleep 4 && ~/bin/sentinela estado && ~/bin/sentinela registro | tail -n 4")
    print(texto)
    return 0 if ok and "ligado" in texto and "amostras:" in texto else 1


def estado():
    ok, texto = comando("~/bin/sentinela estado; ~/bin/sentinela amostras 5; ~/bin/sentinela registro | tail -n 5")
    print(texto)
    return 0 if ok else 1


def desligar():
    ok, texto = comando("~/bin/sentinela desligar")
    print(texto)
    return 0 if ok else 1


def conf():
    """Monta ~/.parise-sentinela.env no A12 a partir do .env do PC e manda pela ENTRADA PADRAO do termux.ps1 (nunca
    como argumento; nada aparece na tela). Com ela o sentinela fala com o FortiGate (conta parise_core_api, que so aceita
    login vindo de 10.0.10.50) e o ligar-pc sabe o MAC do PC e a chave do endereco. Pedido do Rafael, 13/11/2026."""
    from provisionar_fortigate import ENV, gravar_env, ler_env
    env = ler_env(ENV)
    faltam = [k for k in ("FORTIGATE_CERT_SHA256", "FORTIGATE_API_USUARIO", "FORTIGATE_API_SENHA", "MAC_RYZEN")
              if not env.get(k)]
    if faltam:
        print("Faltam no .env do PC: %s" % ", ".join(faltam))
        return 1
    if not env.get("LIGAR_PC_CHAVE"):
        gravar_env(ENV, "LIGAR_PC_CHAVE", secrets.token_urlsafe(18))
        env = ler_env(ENV)
    linhas = ["FORTIGATE_IP=10.0.10.1", "FORTIGATE_CERT_SHA256=" + env["FORTIGATE_CERT_SHA256"],
              "FORTIGATE_API_USUARIO=" + env["FORTIGATE_API_USUARIO"], "FORTIGATE_API_SENHA=" + env["FORTIGATE_API_SENHA"],
              "PC_MAC=" + env["MAC_RYZEN"], "PC_IP=10.0.20.100", "LIGAR_PC_CHAVE=" + env["LIGAR_PC_CHAVE"]]
    r = subprocess.run(["pwsh", "-NoProfile", "-File", str(TERMUX), "-Comando",
                        # entre parenteses: o termux.ps1 poe "tr -d '\r' | " na frente, e um ";" solto separava o cat
                        # do cano (a conf chegava vazia, 13/11/2026)
                        "(umask 077; cat > ~/.parise-sentinela.env) && chmod 600 ~/.parise-sentinela.env && "
                        "test -s ~/.parise-sentinela.env && echo conf-ok",
                        "-LerEntrada"], input=chr(10).join(linhas) + chr(10), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    saida = (r.stdout + r.stderr).strip()
    if "conf-ok" not in saida:
        print("A conf nao chegou ao A12:", saida[-600:])
        return 1
    print("conf gravada no A12 (~/.parise-sentinela.env, so o Termux le)")
    ok, texto = comando("~/bin/sentinela desligar >/dev/null; ~/bin/sentinela ligar; ~/bin/ligar-pc servir-desligar "
                        ">/dev/null; ~/bin/ligar-pc servir-ligar; ~/bin/ligar-pc estado")
    print(texto)
    return 0 if ok else 1


def main():
    p = argparse.ArgumentParser(description="O sentinela do A12 (Termux), pelo cabo.")
    p.add_argument("acao", choices=("instalar", "estado", "desligar", "conf"))
    a = p.parse_args()
    return {"instalar": instalar, "estado": estado, "desligar": desligar, "conf": conf}[a.acao]()


if __name__ == "__main__":
    sys.exit(main())
