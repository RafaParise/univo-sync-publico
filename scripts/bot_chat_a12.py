#!/usr/bin/env python3
"""
bot_chat_a12.py - bot de ChatOps no Termux do A12 (parte C da Bancada-Sync).

Base: o rascunho do bot de chat (protocolo Matrix). O que mudou:
  - segredos fora do código: usa o mesmo ~/.parise-sentinela.env do sentinela,
    mais CHAT_HOMESERVER, CHAT_USUARIO, CHAT_TOKEN, CHAT_SALA e CHAT_DONO;
  - só obedece ao dono (CHAT_DONO) na sala configurada e ignora o histórico antigo;
  - !status_lab consulta de verdade o FortiGate (conta parise_core_api) e a temperatura do A12;
  - !farol_sed avisa que ainda não existe (o rascunho inventava "nenhuma pendência").
Instalar no Termux: pip install matrix-nio
(para sala criptografada: pkg install libolm && pip install "matrix-nio[e2e]").
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sentinela_a12 as sen  # noqa: E402
from fortigate_api import ErroAPI, FortiAPI  # noqa: E402

AJUDA = ("Comandos: !status_lab (FortiGate e A12), !adb_off (bloqueia o ADB), "
         "!adb_on (libera o ADB), !farol_sed, !ajuda")
CAMPOS_CHAT = ("CHAT_HOMESERVER", "CHAT_USUARIO", "CHAT_TOKEN", "CHAT_SALA", "CHAT_DONO")


def status_lab(conf):
    """Resumo real: regras do FortiGate, estado do ADB e temperatura do A12."""
    linhas = []
    try:
        api = FortiAPI(conf.get("FORTIGATE_IP", "10.0.10.1"), impressao=conf["FORTIGATE_CERT_SHA256"])
        api.login(conf["FORTIGATE_API_USUARIO"], conf["FORTIGATE_API_SENHA"])
        try:
            regras = api.ler("firewall/policy") or []
        finally:
            api.logout()
        adb = next((r.get("status") for r in regras if r.get("policyid") == sen.REGRA_ADB), None)
        linhas.append(f"FortiGate: ok, {len(regras)} regras; ADB "
                      + {"enable": "liberado", "disable": "bloqueado"}.get(adb or "", "sem a regra 2"))
    except (ErroAPI, KeyError) as e:
        linhas.append(f"FortiGate: sem resposta ({e})")
    t = sen.temperatura()
    linhas.append("A12: " + ("temperatura indisponível" if t is None else f"{t:.1f} °C"))
    return "\n".join(linhas)


def responder(texto, conf):
    """Resposta para um comando, ou None se não for comando do bot."""
    cmd = texto.strip().lower()
    if cmd == "!status_lab":
        return status_lab(conf)
    if cmd in ("!adb_on", "!adb_off"):
        try:
            sen.regra_adb(conf, cmd == "!adb_on")
            return "ADB liberado no FortiGate." if cmd == "!adb_on" else "ADB bloqueado no FortiGate."
        except (ErroAPI, KeyError) as e:
            return f"Não consegui mudar a regra do ADB: {e}"
    if cmd == "!farol_sed":
        return "O Farol SED ainda não foi implementado: nada foi consultado no SED ou no AVA-EFAPE."
    if cmd == "!ajuda":
        return AJUDA
    return None


async def rodar(conf):
    from nio import AsyncClient, RoomMessageText
    client = AsyncClient(conf["CHAT_HOMESERVER"], conf["CHAT_USUARIO"])
    client.access_token = conf["CHAT_TOKEN"]
    client.user_id = conf["CHAT_USUARIO"]
    await client.sync(timeout=10000, full_state=True)   # pula o histórico: não reage a comando velho

    async def ao_receber(room, evento):
        if room.room_id != conf["CHAT_SALA"] or evento.sender != conf["CHAT_DONO"]:
            return
        resposta = await asyncio.to_thread(responder, evento.body, conf)
        if resposta:
            await client.room_send(room.room_id, "m.room.message", {"msgtype": "m.text", "body": resposta})

    client.add_event_callback(ao_receber, RoomMessageText)
    sen.log("Bot de chat rodando no A12.")
    try:
        await client.sync_forever(timeout=30000)
    finally:
        await client.close()


def main():
    conf = sen.ler_conf(sen.CONF)
    faltam = [k for k in CAMPOS_CHAT + ("FORTIGATE_CERT_SHA256", "FORTIGATE_API_USUARIO", "FORTIGATE_API_SENHA")
              if not conf.get(k)]
    if faltam:
        print(f"Faltam em {sen.CONF}: {', '.join(faltam)}")
        return 1
    asyncio.run(rodar(conf))
    return 0


if __name__ == "__main__":
    sys.exit(main())
