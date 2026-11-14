# -*- coding: utf-8 -*-
"""
repasse_pc.py - o repasse do ARENA também no PC, ao lado do A12 (14/11/2026).

Pedido do Rafael: "crie o servidor no PC para quando o telefone não estiver em DMZ ele poder pegar a carga sozinho
[...] Eles devem trabalhar juntos mas independentes um do outro."

O desenho (ativo-ativo, sem "chefe"):
  - o A12 (Termux, `repasse` do celular-kit) e o PC (esta tarefa) rodam o MESMO programa do ARENA
    (servidor/repasse_proprio.py), cada um com as suas salas, sem depender do outro;
  - o ARENA recebe os dois endereços (Amigos -> Partidas entre casas: "repasse.bancada.lan, repasse-pc.bancada.lan"):
    abre a sala no primeiro que responder e procura a sala nos dois. Se o A12 sair da DMZ, a próxima partida já vai
    para o PC, sem ninguém mexer em nada;
  - o que NÃO dá (limite do protocolo do RetroArch, não deste script): a partida que já está rodando num repasse cai
    se aquele aparelho sair; ela não "pula" para o outro no meio. A próxima partida abre no outro.
O FortiGate já tem tudo desde 11/11: VIP wan1:55440 -> A12 e wan1:55441 -> PC 55440, regras e DNS `repasse` e
`repasse-pc` (scripts/provisionar_rede.py). Com o CGNAT da casa, ninguém de fora chega a nenhum dos dois: vale para a
rede de casa e para quando houver IP público.

Leve: o repasse espera parado (asyncio, perto de 0% de processador) e não abre janela (pythonw, tarefa no logon).

Uso:  python scripts\\repasse_pc.py instalar    (regra do firewall + tarefa "Repasse-ARENA-PC"; precisa de administrador)
      python scripts\\repasse_pc.py estado      (responde? pelo /saude do próprio repasse)
      python scripts\\repasse_pc.py remover
"""
import os
import subprocess
import sys
from pathlib import Path

ARENA = Path(r"C:\Projetos\arena-console")
PROGRAMA = ARENA / "servidor" / "repasse_proprio.py"
TAREFA = "Repasse-ARENA-PC"
REGRA = "parise-sync: repasse do ARENA no PC (TCP 55440)"
PORTA, PORTA_PUBLICA = 55440, 55441          # a 55441 da WAN1 chega aqui na 55440 (VIP ARENA_REPASSE_VIP_PC)
SEM_JANELA = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def _rodar(comando):
    r = subprocess.run(comando, capture_output=True, text=True, errors="replace", **SEM_JANELA)
    print((r.stdout + r.stderr).strip())
    return r.returncode


def pythonw():
    candidato = Path(sys.executable).with_name("pythonw.exe")
    return candidato if candidato.exists() else Path(sys.executable)


def instalar():
    if not PROGRAMA.is_file():
        print("Não achei o programa do ARENA em %s." % PROGRAMA)
        return 1
    python = pythonw()
    _rodar(["powershell", "-NoProfile", "-Command",
            "Remove-NetFirewallRule -DisplayName '%s' -ErrorAction SilentlyContinue; "
            "New-NetFirewallRule -DisplayName '%s' -Direction Inbound -Action Allow -Protocol TCP -LocalPort %d "
            "-Program '%s' | Out-Null; 'regra do firewall: ok'" % (REGRA, REGRA, PORTA, python)])
    comando = '"%s" "%s" --servir --porta %d --porta-publica %d' % (python, PROGRAMA, PORTA, PORTA_PUBLICA)
    codigo = _rodar(["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", TAREFA, "/TR", comando])
    _rodar(["schtasks", "/Run", "/TN", TAREFA])
    return codigo


def estado():
    sys.path.insert(0, str(PROGRAMA.parent))
    import repasse_proprio
    ok = repasse_proprio.saude("127.0.0.1:%d" % PORTA)
    print("Repasse do PC: %s" % ("respondendo" if ok else "NÃO responde"))
    return 0 if ok else 1


def remover():
    _rodar(["schtasks", "/End", "/TN", TAREFA])
    _rodar(["schtasks", "/Delete", "/F", "/TN", TAREFA])
    return _rodar(["powershell", "-NoProfile", "-Command",
                   "Remove-NetFirewallRule -DisplayName '%s'; 'regra do firewall: removida'" % REGRA])


if __name__ == "__main__":
    acao = sys.argv[1] if len(sys.argv) > 1 else "estado"
    sys.exit({"instalar": instalar, "estado": estado, "remover": remover}.get(acao, estado)())
