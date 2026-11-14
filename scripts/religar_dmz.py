# -*- coding: utf-8 -*-
"""
religar_dmz.py - conserta a "rota presa" da DMZ (lição de 13/11/2026, repetida em 14/11/2026).

O sintoma: o PC não alcança o A12 (10.0.10.50) e o tracert mostra o 2º salto na ONT (192.168.18.1), embora o enlace
da DMZ esteja de pé e a tabela do FortiGate (router/lookup) diga "10.0.10.0/24 -> dmz". As sessões novas saem pela
wan1. Em 13/11, derrubar e religar a interface dmz pela API resolveu; em 14/11 voltou com o cabo do A12 de pé a noite
toda (o vigia não viu queda), então a causa não é só cabo solto.

O que faz (uma mudança só, reversível, sem restore e sem reiniciar o FortiGate):
  1. confere se o A12 responde (porta 55440 do repasse ou 8000 do ligar-pc). Respondeu: não faz nada;
  2. confere pela API que o enlace da dmz está de pé e que a tabela aponta a dmz (senão o problema é outro: cabo,
     adaptador do A12, DHCP) e para;
  3. status down na dmz, 3 s, status up, e confere de novo (até 20 s).
O A12 fica sem a DMZ só esses segundos. Registro em logs/religar-dmz.log.

Uso:  python scripts\\religar_dmz.py            (conserta só se precisar)
      python scripts\\religar_dmz.py --conferir (só diz o que faria)
"""
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fortigate_api import FortiAPI  # noqa: E402
from provisionar_fortigate import ENV, ler_env  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
REGISTRO = RAIZ / "logs" / "religar-dmz.log"
A12 = "10.0.10.50"
PORTAS = (55440, 8000)


def a12_responde(espera=1.5):
    for porta in PORTAS:
        try:
            with socket.create_connection((A12, porta), timeout=espera):
                return True
        except OSError:
            continue
    return False


def anotar(texto):
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRO, "a", encoding="utf-8") as saida:
        saida.write("%s %s\n" % (datetime.now().isoformat(timespec="seconds"), texto))
    print(texto)


def ultima_tentativa():
    """Quando o conserto rodou da ultima vez (segundos desde 1970), pelo registro; 0 se nunca."""
    try:
        linhas = [l for l in REGISTRO.read_text(encoding="utf-8").splitlines() if "religando a dmz" in l]
        return datetime.fromisoformat(linhas[-1].split(" ", 1)[0]).timestamp() if linhas else 0.0
    except (OSError, ValueError, IndexError):
        return 0.0


def consertar_se_preciso(intervalo_minimo=1800):
    """Para a telemetria (de 5 em 5 min): conserta sozinha, no maximo uma vez a cada `intervalo_minimo` segundos.
    Devolve o que fez em uma frase, ou "" se o A12 respondia."""
    if a12_responde():
        return ""
    if time.time() - ultima_tentativa() < intervalo_minimo:
        return "A12 sem resposta pela DMZ; conserto ja tentado ha menos de %d min" % (intervalo_minimo // 60)
    return "religar_dmz: codigo %d" % main([])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    so_conferir = "--conferir" in argv
    if a12_responde():
        print("O A12 responde pela DMZ: nada a fazer.")
        return 0
    env = ler_env(ENV)
    api = FortiAPI(env.get("FORTIGATE_IP", "10.0.20.1"), env.get("FORTIGATE_CERT_SHA256") or None, timeout=15)
    api.login("admin", env["ADMIN_SENHA"])
    try:
        dmz = (api.monitor("system/interface") or {}).get("dmz") or {}
        rota = api.monitor("router/lookup?destination=%s" % A12) or {}
        if not dmz.get("link"):
            anotar("A DMZ está SEM enlace: o problema é o cabo, o hub ou o adaptador do A12 (nada mudado).")
            return 1
        if rota.get("interface") != "dmz":
            anotar("A tabela manda %s para %s, não para a dmz: conferir o provisionamento (nada mudado)."
                   % (A12, rota.get("interface")))
            return 1
        if so_conferir:
            print("Enlace de pé e tabela certa, mas o A12 não responde: a rota presa. Sem --conferir, religo a dmz.")
            return 0
        anotar("A12 sem resposta com enlace e tabela certos: religando a dmz.")
        api.ajustar("system/interface/dmz", {"status": "down"})
        time.sleep(3)
        api.ajustar("system/interface/dmz", {"status": "up"})
    finally:
        api.logout()
    for _ in range(10):
        time.sleep(2)
        if a12_responde():
            anotar("Resolvido: o A12 responde pela DMZ de novo.")
            return 0
    anotar("A dmz voltou, mas o A12 ainda não responde: conferir no celular (ip route, a rede padrão do Android).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
