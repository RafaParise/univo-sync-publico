# -*- coding: utf-8 -*-
"""
syslog_eventos.py - recebe os EVENTOS do FortiGate (syslog, UDP 514) e guarda só o que ajuda a achar defeito.

Por que existe (14/11/2026): o PC não alcançou o A12 da DMZ por 5 h (13/11 21h até 14/11 02h49, a "rota presa") e não
havia como saber quando nem por quê: o FortiGate já mandava o syslog para o PC, mas nada escutava (o Windows jogava
tudo fora). Agora ficam guardados os eventos de sistema: enlace que caiu ou voltou, reinício, mudança de configuração,
entrada de administrador. O registro de tráfego (cada sessão) não vem mais: o otimizar_fortigate.py --aplicar syslog
o desligou no FortiGate.

Privacidade (regra do projeto, docs/telemetria.md): só saúde dos equipamentos do Rafael. Ficam de fora: DHCP inteiro
(é onde aparecem os celulares de quem se liga na LAN2), número de série e nome do aparelho, e todo MAC e endereço da
LAN2 (10.0.30.x) que aparecer no texto vira "[oculto]". Só se aceita pacote vindo do FortiGate (10.0.20.1).

Leve: espera parado (recvfrom sem prazo, perto de 0% de processador) e não abre janela nenhuma.
Guarda em data/telemetria/fortigate-eventos-AAAA-MM-DD.jsonl (fora do git) e os últimos 40 em
memoria/telemetria/EVENTOS-FORTIGATE.md, que as IAs leem junto com o RESUMO.md.

Uso:  pythonw scripts\\syslog_eventos.py                 (a tarefa "Syslog-FortiGate" chama assim, no logon)
      python  scripts\\syslog_eventos.py --instalar      (regra do firewall do Windows + tarefa; precisa de administrador)
      python  scripts\\syslog_eventos.py --remover       (desfaz os dois)
"""
import json
import os
import re
import shlex
import socket
import subprocess
import sys
from collections import deque
from datetime import datetime
from pathlib import Path

PASTA = Path(__file__).resolve().parent
RAIZ = PASTA.parent
DADOS = RAIZ / "data" / "telemetria"
RESUMO = RAIZ / "memoria" / "telemetria" / "EVENTOS-FORTIGATE.md"
FORTIGATE = "10.0.20.1"
PORTA = 514
TAREFA = "Syslog-FortiGate"
REGRA = "parise-sync: syslog do FortiGate (UDP 514, so de 10.0.20.1)"
SEM_JANELA = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

# Só estes campos do FortiOS ficam (o resto, como devid = número de série e devname, nunca é guardado).
CAMPOS = ("date", "time", "type", "subtype", "level", "logid", "logdesc", "action", "status", "msg", "reason",
          "intf", "interface", "ui", "user", "cfgpath", "cfgobj", "cfgattr")
SUBTIPOS_FORA = ("dhcp", "wireless", "endpoint", "user")
OCULTAR = [re.compile(r"\b[0-9a-f]{2}(?:[:-][0-9a-f]{2}){5}\b", re.I),       # MAC
           re.compile(r"\b10\.0\.30\.\d{1,3}\b")]                             # LAN2 (os controles dos alunos)


def ler_registro(texto):
    """Os pares chave=valor de uma linha do FortiOS ('<189>date=... logdesc="Interface status changed" ...')."""
    texto = re.sub(r"^<\d+>", "", texto.strip())
    try:
        partes = shlex.split(texto, posix=True)
    except ValueError:
        partes = texto.split()
    pares = {}
    for parte in partes:
        if "=" in parte:
            chave, valor = parte.split("=", 1)
            pares[chave] = valor
    return pares


def filtrar(pares):
    """O evento limpo (só os CAMPOS, sem MAC nem LAN2), ou None se não é para guardar."""
    if pares.get("type") != "event" or pares.get("subtype") in SUBTIPOS_FORA:
        return None
    limpo = {}
    for chave in CAMPOS:
        if chave in pares:
            valor = pares[chave]
            for padrao in OCULTAR:
                valor = padrao.sub("[oculto]", valor)
            limpo[chave] = valor[:300]
    return limpo


def guardar(evento, ultimos):
    DADOS.mkdir(parents=True, exist_ok=True)
    dia = datetime.now().strftime("%Y-%m-%d")
    with open(DADOS / ("fortigate-eventos-%s.jsonl" % dia), "a", encoding="utf-8") as saida:
        saida.write(json.dumps(dict(evento, recebido=datetime.now().isoformat(timespec="seconds")),
                               ensure_ascii=False) + "\n")
    ultimos.append(evento)
    RESUMO.parent.mkdir(parents=True, exist_ok=True)
    linhas = ["# Eventos do FortiGate (scripts/syslog_eventos.py)", "",
              "Os últimos %d, do mais novo ao mais velho. Só eventos de sistema; sem MAC, sem DHCP." % len(ultimos), ""]
    for e in reversed(ultimos):
        linhas.append("- %s %s [%s] %s%s" % (e.get("date", ""), e.get("time", ""), e.get("level", ""),
                                             e.get("logdesc", ""), (": " + e["msg"]) if e.get("msg") else ""))
    temporario = RESUMO.with_suffix(".tmp")
    temporario.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    os.replace(temporario, RESUMO)


def escutar():
    ponto = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        ponto.bind(("0.0.0.0", PORTA))
    except OSError as falha:            # outra cópia já escuta (ou a porta está ocupada): sai quieto
        print("syslog_eventos: não abri a porta %d (%s)" % (PORTA, falha))
        return 1
    ultimos = deque(maxlen=40)
    while True:
        dados, (origem, _porta) = ponto.recvfrom(8192)
        if origem != FORTIGATE:
            continue
        try:
            evento = filtrar(ler_registro(dados.decode("utf-8", "replace")))
            if evento:
                guardar(evento, ultimos)
        except Exception as falha:  # noqa: BLE001 - um pacote ruim nunca derruba o receptor
            print("syslog_eventos: pacote ignorado (%s)" % falha)


def _rodar(comando):
    r = subprocess.run(comando, capture_output=True, text=True, errors="replace", **SEM_JANELA)
    print((r.stdout + r.stderr).strip())
    return r.returncode


def instalar():
    python = Path(sys.executable).with_name("pythonw.exe")
    if not python.exists():
        python = Path(sys.executable)
    _rodar(["powershell", "-NoProfile", "-Command",
            "Remove-NetFirewallRule -DisplayName '%s' -ErrorAction SilentlyContinue; "
            "New-NetFirewallRule -DisplayName '%s' -Direction Inbound -Action Allow -Protocol UDP -LocalPort %d "
            "-RemoteAddress %s -Program '%s' | Out-Null; 'regra do firewall: ok'" % (REGRA, REGRA, PORTA, FORTIGATE,
                                                                                    python)])
    comando = '"%s" "%s"' % (python, PASTA / "syslog_eventos.py")
    codigo = _rodar(["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", TAREFA, "/TR", comando])
    _rodar(["schtasks", "/Run", "/TN", TAREFA])
    return codigo


def remover():
    _rodar(["schtasks", "/End", "/TN", TAREFA])
    _rodar(["schtasks", "/Delete", "/F", "/TN", TAREFA])
    return _rodar(["powershell", "-NoProfile", "-Command",
                   "Remove-NetFirewallRule -DisplayName '%s'; 'regra do firewall: removida'" % REGRA])


if __name__ == "__main__":
    if "--instalar" in sys.argv:
        sys.exit(instalar())
    if "--remover" in sys.argv:
        sys.exit(remover())
    sys.exit(escutar())
