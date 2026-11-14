# parise-sync (Bancada-Sync)

Laboratório de bancada do Rafael: FortiGate 60D como firewall central, Galaxy A12 com Termux na DMZ, PC Ryzen na LAN1 e switch da ARENA na LAN2.

| Arquivo | O que é |
|---|---|
| `docs/contexto-bancada-sync.md` | Topologia física e lógica e a divisão dos módulos |
| `docs/equipamento-fortigate-60d.md` | Dados do aparelho e qual porta serve para quê |
| `docs/decisoes-provisionamento.md` | O que mudou do plano original e por quê |
| `docs/plano-mestre-provisionamento.md` | Plano original (só referência) |
| `config/fortigate-bancada.conf` | A configuração que vai para o FortiGate |
| `scripts/provisionar_rede.py` | **Configura pela rede** (API REST + restore ou CLI via SSH) |
| `scripts/fortigate_api.py` | Cliente da API do FortiOS 5.4, com o certificado preso |
| `scripts/projetos_infra.py` + `config/projetos-infra.json` | Liga todos os projetos à infra: verifica o registro, cria nomes `<projeto>.bancada.lan` e cadastra no parise-core |
| `scripts/sentinela_a12.py` | Roda no Termux do A12: corta o ADB no FortiGate por calor ou acesso estranho |
| `docker-compose.yml`, `caddy/`, `services/`, `portal/`, `projects/` | Pilha `parise-infra` (Tailscale, Caddy, AdGuard, parise-core, ARENA, arquivos, status). Precisa de um servidor Linux; ver `scripts/bootstrap.sh` |
| `scripts/diagnostico_usb.ps1` | Acha o cabo: portas COM e USB sem driver |
| `scripts/fortigate_reset.py` | Volta o FortiGate ao padrão de fábrica |
| `scripts/provisionar_fortigate.py` | Aplica a configuração pelo console |
| `scripts/fortios_console.py` | Conversa com a linha de comando do FortiOS (usado pelo de cima) |
| `tests/` | Testes com um FortiGate simulado |
| `memoria/ESTADO.md` | Onde o trabalho parou e o próximo passo |

## Ferramentas
- Python 3.14 + pyserial 3.5 (instalados)
- PuTTY 0.85 (instalado), para abrir o console à mão:
  `putty -serial COM3 -sercfg 9600,8,n,1,N` (troque COM3 pela porta do cabo)

## Ordem de uso (caminho principal: pela rede)
1. `.env`: `ADMIN_SENHA` e `MAC_RYZEN` (o `MAC_A12` quando o hub chegar).
2. PC na **porta 1** com cabo de rede.
3. `python scripts\provisionar_rede.py` (só mostra), depois `--aplicar`. Pode repetir.
4. Ligar a ONT Huawei na WAN1 (feito em 12/11/2026; a porta 3 como uplink é a opção B de `docs/TOPOLOGIA-2026-11-12.md`), a porta 2 ao switch da ARENA e a DMZ ao hub do A12.

Plano B, pelo console serial (cabo USB↔RJ-45 na porta CONSOLE): `diagnostico_usb.ps1`, `fortigate_reset.py` e `provisionar_fortigate.py`. O modelo `config/fortigate-bancada.conf` ainda precisa ser adaptado ao FortiOS 5.4 (ver `memoria/ESTADO.md`).

Dependências: `python -m pip install -r requirements.txt`

Testes: `python -m unittest discover -s tests -v`
