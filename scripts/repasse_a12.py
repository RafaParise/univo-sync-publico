"""Instala, atualiza ou confere o repasse do ARENA no Galaxy A12 (Termux), pelo cabo USB.

O repasse e' o servidor que deixa dois alunos em casas diferentes jogarem juntos pelo ARENA, por um codigo de 6 numeros
e sem a lista publica da internet (codigo: C:\\Projetos\\arena-console\\servidor\\repasse_proprio.py). O A12 fica
sempre ligado na bancada, entao ele e' a "casa" das salas; o PC e' so mais um jogador.

Uso (no PC, com o celular no cabo e a depuracao USB ligada):
    python scripts\\repasse_a12.py instalar     copia o programa do ARENA, o comando "repasse" e o script de ligar; liga
    python scripts\\repasse_a12.py estado       se esta ligado e se responde
    python scripts\\repasse_a12.py desligar

Fala com o Termux pelo scripts\\termux.ps1 do projeto Android Embeeded (SSH pelo cabo, so 127.0.0.1)."""
import argparse
import subprocess
import sys
from pathlib import Path

ARENA = Path(r"C:\Projetos\arena-console")
PROGRAMA = ARENA / "servidor" / "repasse_proprio.py"
KIT = Path(r"C:\Android Embeeded\scripts\celular-kit")
COMANDO = KIT / "bin" / "repasse"
BOOT = KIT / "boot" / "iniciar-a12"
TERMUX = Path(r"C:\Android Embeeded\scripts\termux.ps1")


def termux(*argumentos):
    """Roda o termux.ps1 com os argumentos; devolve (saida 0?, texto)."""
    r = subprocess.run(["pwsh", "-NoProfile", "-File", str(TERMUX), *argumentos], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def comando(texto):
    return termux("-Comando", texto)


def instalar():
    for arquivo in (PROGRAMA, COMANDO, BOOT, TERMUX):
        if not arquivo.is_file():
            print("Falta %s" % arquivo)
            return 1
    ok, texto = comando("mkdir -p ~/arena-repasse ~/bin ~/.termux/boot")
    if not ok:
        print("Nao alcancei o Termux pelo cabo:\n" + texto)
        return 2
    for origem, destino in ((PROGRAMA, "~/arena-repasse/"), (COMANDO, "~/bin/"), (BOOT, "~/.termux/boot/")):
        ok, texto = termux("-Copiar", str(origem), "-Para", destino)
        print("copiado %s -> %s: %s" % (origem.name, destino, "ok" if ok else texto))
        if not ok:
            return 1
    ok, texto = comando("chmod +x ~/bin/repasse ~/.termux/boot/iniciar-a12; ~/bin/repasse desligar >/dev/null; "
                        "~/bin/repasse ligar && sleep 1 && ~/bin/repasse testar")
    print(texto)
    return 0 if ok and "respondeu" in texto and "nao respondeu" not in texto else 1


def estado():
    ok, texto = comando("~/bin/repasse estado; ~/bin/repasse testar; ~/bin/repasse registro | tail -n 5")
    print(texto)
    return 0 if ok else 1


def desligar():
    ok, texto = comando("~/bin/repasse desligar")
    print(texto)
    return 0 if ok else 1


def main():
    p = argparse.ArgumentParser(description="O repasse do ARENA no A12 (Termux), pelo cabo.")
    p.add_argument("acao", choices=("instalar", "estado", "desligar"))
    a = p.parse_args()
    return {"instalar": instalar, "estado": estado, "desligar": desligar}[a.acao]()


if __name__ == "__main__":
    sys.exit(main())
