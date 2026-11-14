# -*- coding: utf-8 -*-
"""
otimizar_fortigate.py
Ajustes de desempenho do FortiGate 60D (FortiOS 5.4.10), um por um, SÓ os que a medição justificou (13/11/2026).
Cada ajuste vai pela API (sem restore, sem reiniciar) e guarda o valor antigo em logs/otimizacao-antes.json, para o
--desfazer voltar exatamente ao que era.

Ajustes e o porquê (medidos com scripts\\medir_dns.py e scripts\\diagnostico_desempenho.py):
  dns         O FortiGate perguntava os nomes à FortiGuard, nos EUA: 112 a 116 ms por nome novo. A Cloudflare
              (1.1.1.1) respondeu em 7 a 11 ms, e o Google (8.8.8.8) em 8 a 12 ms (reserva). Cada site novo que o
              PC abre ganha uns 100 ms. O filtro de DNS da DMZ (lista local) continua igual.
  modelador   NÃO USAR (medido 13/11/2026). A ideia: segurar o PC abaixo do limite da linha para a ONT não
              descartar pacotes de quem está no Wi-Fi (com o PC a 468 Mbit/s, o A12 perdia 31%). Mas o tráfego
              modelado sai do acelerador do 60D e vai para a CPU: o envio do PC caiu de 396 para 111 Mbit/s, com a
              CPU a 99%. Regressão grande; desfeito na hora. Fica aqui só para medir de novo num aparelho mais forte.

  syslog      O FortiGate mandava ao PC (10.0.20.100:514) o registro de CADA sessão (nível "information": tráfego
              de passagem, local, multicast), e o firewall do Windows jogava tudo fora (não havia regra para a 514
              nem programa escutando): trabalho perdido no processador do 60D a cada conexão. Medido em 14/11/2026
              pela API (filtro do syslogd) e pelo firewall do PC. Agora vão só os eventos (enlace, reinício,
              administração), que o scripts\\syslog_eventos.py guarda, sem MAC nem nome de aparelho.

Ficou de fora de propósito: desligar o controlador de Wi-Fi (o 60D não tem rádio). Ganho desprezível (memória em 16%)
e não conferi se o 5.4 reinicia o aparelho para isso. Nada de mudança sem medida que a justifique.

Uso:  python scripts\\otimizar_fortigate.py --conferir          (só lê: mostra o que mudaria)
      python scripts\\otimizar_fortigate.py --aplicar dns
      python scripts\\otimizar_fortigate.py --desfazer dns
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fortigate_api import FortiAPI  # noqa: E402
from provisionar_fortigate import ENV, ler_env  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
ANTES = RAIZ / "logs" / "otimizacao-antes.json"

AJUSTES = {
    "dns": ("system/dns", {"primary": "1.1.1.1", "secondary": "8.8.8.8"}),
    # 14/11/2026: o fuso estava "04" (Pacifico, EUA) com horario de verao: os registros saiam 5 h atrasados. "18" e'
    # Brasilia (conferido nas opcoes do proprio FortiOS); dst desligado porque o Brasil acabou com o horario de verao em
    # 2019 e o FortiOS 5.4.10 (2018) ainda aplicaria a regra antiga em novembro. O relogio em UTC ja estava certo (NTP).
    "relogio": ("system/global", {"timezone": "18", "dst": "disable"}),
    # 14/11/2026: so os EVENTOS vao para o syslog do PC (scripts/syslog_eventos.py), sem o registro de cada sessao.
    "syslog": ("log.syslogd/filter", {"forward-traffic": "disable", "local-traffic": "disable",
                                      "multicast-traffic": "disable", "sniffer-traffic": "disable"}),
    # Preenchido por modelador(): os limites do PC na regra 1 (PC_PARA_INTERNET).
    "modelador": ("firewall/policy/1", {"traffic-shaper": "PC_ENVIO", "traffic-shaper-reverse": "PC_DOWNLOAD"}),
}
# Os objetos que um ajuste precisa antes (criados no --aplicar, apagados no --desfazer).
OBJETOS = {}
BACKUP = RAIZ / "logs" / "backup-antes-otimizacao.conf"


def modelador(download_mbits, envio_mbits):
    """O PC fica um pouco abaixo do limite da linha, para a fila da ONT nunca transbordar (13/11/2026: com o PC a
    468 Mbit/s, o A12 no Wi-Fi da casa perdia 31% dos pacotes; enviando a 445, 10%). Compartilhado (per-policy
    disable) e sem garantia: com o PC parado ou desligado, nada fica reservado, e a casa nem passa pelo FortiGate."""
    def um(nome, mbits):
        return {"name": nome, "maximum-bandwidth": int(mbits * 1000), "guaranteed-bandwidth": 0,
                "bandwidth-unit": "kbps", "priority": "high", "per-policy": "disable"}
    OBJETOS["modelador"] = [("firewall.shaper/traffic-shaper", "PC_DOWNLOAD", um("PC_DOWNLOAD", download_mbits)),
                            ("firewall.shaper/traffic-shaper", "PC_ENVIO", um("PC_ENVIO", envio_mbits))]


def entrar():
    env = ler_env(ENV)
    api = FortiAPI(env.get("FORTIGATE_IP", "10.0.20.1"), env.get("FORTIGATE_CERT_SHA256") or None, timeout=20)
    api.login("admin", env["ADMIN_SENHA"])
    return api


def atual(api, caminho, chaves):
    dados = api.ler(caminho)
    dados = dados[0] if isinstance(dados, list) else dados
    return {k: dados.get(k) for k in chaves}


def guardado():
    try:
        return json.loads(ANTES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ajustes de desempenho do FortiGate, medidos e reversíveis.")
    modo = ap.add_mutually_exclusive_group(required=True)
    modo.add_argument("--conferir", action="store_true")
    modo.add_argument("--aplicar", nargs="+", choices=sorted(AJUSTES))
    modo.add_argument("--desfazer", nargs="+", choices=sorted(AJUSTES))
    ap.add_argument("--download", type=float, default=420, help="limite do PC ao baixar, em Mbit/s (modelador)")
    ap.add_argument("--envio", type=float, default=400, help="limite do PC ao enviar, em Mbit/s (modelador)")
    args = ap.parse_args(argv)
    modelador(args.download, args.envio)
    api = entrar()
    try:
        if args.conferir:
            for nome, (caminho, novo) in AJUSTES.items():
                agora = atual(api, caminho, novo)
                print("%-9s %s -> %s%s" % (nome, agora, novo, "  (já está)" if agora == novo else ""))
            return 0
        antes = guardado()
        if args.aplicar:
            for nome in args.aplicar:
                caminho, novo = AJUSTES[nome]
                agora = atual(api, caminho, novo)
                if agora == novo:
                    print("%s: já está." % nome)
                    continue
                antes.setdefault(nome, agora)          # guarda só o original (aplicar duas vezes não estraga)
                ANTES.parent.mkdir(exist_ok=True)
                ANTES.write_text(json.dumps(antes, indent=1), encoding="utf-8")
                if not BACKUP.exists():                # a configuracao inteira, antes da primeira mudanca
                    BACKUP.write_text(api.backup(), encoding="utf-8")
                for tabela, chave, dados in OBJETOS.get(nome, []):
                    api.gravar(tabela, chave, dados)
                    print("  objeto %s/%s gravado" % (tabela, chave))
                api.ajustar(caminho, novo)
                depois = atual(api, caminho, novo)
                print("%s: %s -> %s %s" % (nome, agora, depois, "ok" if depois == novo else "NÃO PEGOU"))
        else:
            for nome in args.desfazer:
                caminho, _novo = AJUSTES[nome]
                if nome not in antes:
                    print("%s: não há valor antigo guardado." % nome)
                    continue
                api.ajustar(caminho, antes[nome])
                print("%s: voltou a %s" % (nome, atual(api, caminho, antes[nome])))
                for tabela, chave, _dados in OBJETOS.get(nome, []):
                    api.apagar(tabela, chave)
                    print("  objeto %s/%s apagado" % (tabela, chave))
                antes.pop(nome, None)
                ANTES.write_text(json.dumps(antes, indent=1), encoding="utf-8")
        return 0
    finally:
        try:
            api.logout()
        except Exception:          # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
