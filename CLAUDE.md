# parise-sync (Bancada-Sync)

Laboratório de rede da bancada do Rafael. Contexto completo em `docs/contexto-bancada-sync.md`. Estado e próximo passo em `memoria/ESTADO.md` (ler ao começar e atualizar ao fechar um bloco).

Regras:
- O número de série e o MAC do FortiGate ficam só em `equipamento.local.md` (fora do git). Não colocar em commit nem em outro arquivo.
- Nenhuma chave de API ou senha no repositório. A chave do FortiGate é gerada no próprio aparelho e fica em `.env`.
- Só mandar comando ao FortiGate por uma porta COM de cabo de console de verdade. A COM da Samsung (VID 04E8) é o celular.
- O repositório no GitHub (RafaParise/parise-sync) é **privado**.
- Repasse do ARENA (11/11/2026): dois hospedeiros, o A12 na DMZ (`repasse.bancada.lan`, VIP wan1:55440) e o PC
  (`repasse-pc.bancada.lan`, VIP wan1:55441 -> 55440 na LAN1; na DMZ ele pega 10.0.10.60). Sem nenhum dos dois, o
  ARENA usa os repasses públicos do RetroArch. Detalhe nos comentários de `scripts/provisionar_rede.py`.
- Rede em uso (13/11/2026): ONT Huawei (192.168.18.1) na **WAN1** do FortiGate (DHCP 192.168.18.40); a porta 3
  é só LAN1. `provisionar_rede.py` usa `wan1` por padrão (`--uplink internal3` = opção B, não usada). O PC sai
  pelo cabo (placa "Cabo FortiGate 60D", antes "Ethernet 2", métrica 10); o Wi-Fi dele na Huawei (métrica 50) é a reserva automática. CGNAT confirmado
  (13/11: a ONT tem 100.66.x). DNS do FortiGate na Cloudflare; modelador NÃO (CPU do 60D): `docs/DESEMPENHO-E-ACESSO-REMOTO.md`. Detalhe, duplo NAT e o que falta: `docs/TOPOLOGIA-2026-11-12.md`.
- Telemetria sutil (11/11/2026): `scripts/telemetria.py` de 5 em 5 min (tarefa `Telemetria-Bancada`), resumo em
  `memoria/telemetria/RESUMO.md` para as IAs; só saúde dos equipamentos do Rafael, nunca MAC, nome ou tráfego de
  celular de aluno (`docs/telemetria.md`).
- Painel ao vivo (14/11/2026): `scripts\estado_casa.py` (atalho "Infraestrutura da casa", a cada 3 s). A12 some da
  DMZ com o enlace de pé = "rota presa": `scripts\religar_dmz.py` (a telemetria já conserta sozinha). Eventos do
  FortiGate (sem MAC/DHCP) em `memoria/telemetria/EVENTOS-FORTIGATE.md` (`syslog_eventos.py`). Latência por TCP no
  Python do Windows: connect bloqueante (com prazo o select soma ~10 ms).
- Repasse do ARENA ativo-ativo (14/11/2026): A12 (Termux, DMZ e Wi-Fi) e PC (`scripts\repasse_pc.py`, tarefa
  `Repasse-ARENA-PC`); o ARENA aceita `repasse.bancada.lan, repasse-pc.bancada.lan`. Placa do cabo = "Cabo FortiGate
  60D" (era "Ethernet 2"). Hardware/sensores do painel: `scripts\hardware_casa.py` (60D sem sensores; temperatura
  do PC só com LibreHardwareMonitor+PawnIO, não instalado: decisão do Rafael).
