# Estado: parise-sync

**Atualizado em:** 14/11/2026

## 14/11/2026, ~03h20: hardware no painel, teste de internet, nomes de rede e o repasse no PC
- **Painel com hardware e sensores** (`scripts\hardware_casa.py`): PC (Ryzen 5 5600G, 6 núcleos/12 lógicos, carga,
  RAM, disco, vídeo, tempo ligado); A12 pelo adb sem fio (processador, RAM, armazenamento, bateria com mA e W,
  temperaturas do serviço térmico: processador, bateria, rádio, placa); FortiGate pelo SSH (60D, FortiSOC2, 1839 MB,
  flash 3,8 GB, tempo ligado). **Sem sensor:** o 60D não tem temperatura nem energia; o Windows deste PC não expõe
  temperatura nem consumo (sem zona térmica nem medidor): vêm do LibreHardwareMonitor 0.9.6 com o driver PawnIO, que
  é driver de kernel. **NÃO instalei: decisão do Rafael.** Se quiser: instalar o PawnIO e o LHM, ligar "Remote Web
  Server" (porta 8085) e o painel passa a mostrar sozinho.
- **Teste de internet** (tecla T no painel; `scripts\teste_internet.py`): 4 fluxos por 8 s na Cloudflare, latência
  parada e com carga, conferência pela WAN1 do FortiGate. Medido às 03h12: 610/465 Mbit/s, 8,2 ms, +2 ms com carga.
  A Cloudflare limita testes seguidos (429, ~1 h de espera): o painel diz isso em vez de "0 Mbit/s".
- **Nomes de rede:** placa "Ethernet 2" virou **"Cabo FortiGate 60D"** e o perfil "Rede 5" virou **"FortiGate 60D -
  LAN1 bancada"** (métrica 10 mantida; nomes antigos em `logs/nomes-de-rede-antes.json`). Desfazer:
  `Rename-NetAdapter 'Cabo FortiGate 60D' 'Ethernet 2'` e o ProfileName no registro (NetworkList\Profiles).
- **Repasse do ARENA no PC** (`scripts\repasse_pc.py instalar`): tarefa `Repasse-ARENA-PC` (pythonw, logon) e regra
  do firewall TCP 55440. Ativo-ativo com o A12 (que já atende pela DMZ e pelo Wi-Fi da casa; não precisa esperar a
  DMZ). O ARENA aceita os dois endereços desde `cef9ae1`/`20d7d59`: `repasse.bancada.lan, repasse-pc.bancada.lan`
  (Amigos -> Partidas entre casas). Falta o Rafael pôr esse endereço no ARENA do PC (dado do usuário: não mexi) e o APK
  novo levar isso ao A12 na próxima versão.

## 14/11/2026, ~03h: painel ao vivo, rota presa da DMZ, syslog de eventos e o relógio do FortiGate
- **Painel "Infraestrutura da casa" ao vivo** (pedido do Rafael: atualizar a cada 3 s enquanto aberto): uma sessão
  só no FortiGate, conferências em paralelo; vazão por porta, latência real. Uma foto: 0,4 s (antes 8,6 s).
- **A12 fora da DMZ por 5 h** (13/11 21:14 até 14/11 02:49), de novo a "rota presa", depois do restore do WOL.
  `scripts\religar_dmz.py` resolveu; a telemetria passa a consertar sozinha (1 vez a cada 30 min no máximo) e o
  `provisionar_rede.py` confere depois de cada restore. A disponibilidade de 42% do A12 na telemetria era isso.
- **Syslog:** o FortiGate mandava cada sessão ao PC (jogada fora); agora só eventos (`otimizar_fortigate.py
  --aplicar syslog`), guardados pelo `syslog_eventos.py` (tarefa `Syslog-FortiGate` no logon, regra do firewall só
  para 10.0.20.1), sem MAC, DHCP nem série: `memoria/telemetria/EVENTOS-FORTIGATE.md`. Desfazer: `--remover` e
  `otimizar_fortigate.py --desfazer syslog`.
- **Relógio:** fuso estava Pacífico (EUA) com horário de verão; agora Brasília sem horário de verão (`--aplicar
  relogio`).
- **Medido e não mudado:** PC -> FortiGate 0,70 ms, internet 8,9 ms (a placa do PC fica como está). O 60D não tem
  rádio. Rust: o plano do ARENA não adotou Rust (medido); aqui valeram as mesmas ideias (não repetir trabalho,
  esperar parado, medir antes). Detalhe: `docs/DESEMPENHO-E-ACESSO-REMOTO.md`.
- **PRÓXIMO PASSO:** quando o switch chegar, ligar na porta 2 (LAN2) e conferir pelo painel; medir a regra 5 com o
  A12 de saída da VPN; ver nos eventos se a dmz cai sozinha (causa da rota presa).

## 14/11/2026 (madrugada): janela preta da telemetria e o vigia da noite do A12
- **Janela preta piscando a cada 5 min:** era a tarefa `Telemetria-Bancada` (pythonw, sem console): cada `ping`, `route`,
  `netsh` e `adb` abria uma janela do Terminal por cima de tudo. Agora todos vão com `CREATE_NO_WINDOW` (`SEM_JANELA`).
  Também: o `netsh` sai em UTF-8 ("ConexÃ£o" virava lixo no RESUMO.md).
- **Vigia da noite** (`scripts/vigia_a12_noite.py`, pedido do Rafael): a telemetria mostrava o A12 da DMZ disponível só
  42% do tempo. O vigia, de minuto em minuto até as 07:30, reconecta a depuração sem fio, liga "ficar acordado enquanto
  carrega", acende a tela que apagar (o bloqueio continua) e anota DMZ, Wi-Fi e as portas do ARENA (8777) e do repasse
  (55440) em `memoria/telemetria/VIGIA-A12.md`; no fim devolve os ajustes do celular. Desfazer na hora:
  `python scripts\vigia_a12_noite.py --devolver`.


## Repasse do ARENA na bancada (10/11/2026)
- Pedido do Rafael: partidas do ARENA entre casas diferentes pela infra que fica sempre ligada; o PC é só mais um jogador.
- **No A12 (Termux), instalado e ligado:** `~/arena-repasse/repasse_proprio.py` (vem do ARENA), comando `repasse`
  (ligar/desligar/estado/registro/testar) e linha no `~/.termux/boot/iniciar-a12` (sobe sozinho). Instalar ou atualizar
  pelo cabo: `python scripts\repasse_a12.py instalar` (usa o `termux.ps1` do Android Embeeded). Testado em 10/11 na
  rede de casa: dois RetroArch do PC jogaram pelo repasse do A12 (ping 45 ms).
- **No FortiGate, escrito e NÃO aplicado** (falta a WAN1 e o hub do A12 na DMZ): serviço `ARENA_REPASSE` (TCP 55440),
  VIP `ARENA_REPASSE_VIP` (wan1:55440 -> 10.0.10.50:55440, via restore, antes das regras) e regra 6
  `INTERNET_PARA_REPASSE_ARENA` (wan1 -> dmz, sem registro de tráfego: são alunos). Aplicar com
  `python scripts\provisionar_rede.py --aplicar` quando o A12 estiver na DMZ (o restore reinicia o FortiGate).
- **10/11, 18:22:** `provisionar_rede.py --aplicar` rodou com o VIP e a regra 6 e enviou o restore (`logs/ultimo-restore.conf`), mas foi interrompido pelo sistema (falta de memória do PC, por causa do emulador do Android aberto ao mesmo tempo). Depois disso a placa com fio do PC ficou **sem sinal** e o FortiGate não respondeu em 8 minutos: conferir os LEDs e o cabo, e rodar `--aplicar` de novo (ele confere o que já está lá).
- **Corrigido depois (não aplicado ainda):** `ARENA_WEBSOCKET` era 8080; o celular como controle do ARENA usa **8780**. A regra 3 (PC -> A12) ganhou `ARENA_REPASSE`, e a nova regra 7 `CONTROLES_PARA_REPASSE_ARENA` deixa os celulares do switch (LAN2) jogarem pelo repasse do A12 (endereço interno `a12.bancada.lan:55440`).
- **APLICADO em 10/11, à noite** (depois que o FortiGate voltou; o PC sem o emulador aberto): `provisionar_rede.py
  --aplicar` passou inteiro, o restore reiniciou o aparelho e ele voltou em 10.0.20.1. Conferido pela API: 7 regras
  (com `INTERNET_PARA_REPASSE_ARENA` e `CONTROLES_PARA_REPASSE_ARENA`), VIP `ARENA_REPASSE_VIP` wan1:55440 ->
  10.0.10.50:55440, serviços `ARENA_WEBSOCKET` 8780 e `ARENA_REPASSE` 55440. Lição: o travamento das 18:22 foi o
  restore cortado no meio (o PC sem memória); com o PC livre, o mesmo restore passou.
- **Conversa nova do Gemini (10/11, `share.gemini.google/VM7NGc9PJLgK`), avaliada item por item:**
  `docs/avaliacao-gemini-10-11.md`.
- **Falta, físico/Rafael:** (1) conferir se a operadora usa CGNAT (endereço da WAN do roteador diferente do "meu IP" =
  CGNAT: sem IP público, ninguém de fora chega); (2) encaminhar a porta 55440 TCP no roteador da operadora para a WAN1
  do FortiGate (ou roteador em modo ponte); (3) teste de fora: celular no 4G com o ARENA, Amigos -> Partidas entre
  casas -> Testar. Decisões explicadas: `C:\Projetos\arena-console\docs\REPASSE-PROPRIO.md`.

## Pronto no FortiGate 60D (FortiOS 5.4.10), conferido
- Admin com senha (`ADMIN_SENHA`); hostname FG60D-BANCADA.
- **LAN1** "internal" (portas 1 e 3 a 7): 10.0.20.1/24. O PC Ryzen recebe 10.0.20.100 (reservado pelo MAC).
- **LAN2** internal2 (porta 2): 10.0.30.1/24, DHCP de .10 a .150, ARENA com QoS e DSCP.
- **DMZ**: 10.0.10.1/24, DHCP com um único IP (10.0.10.50) para o A12.
- WAN1 e WAN2 por DHCP; DNS local `bancada.lan` (fortigate, arena, a12); filtro de DNS `*.samsung.net` na DMZ; syslog para o PC.
- 5 regras: PC_PARA_INTERNET, PC_PARA_A12_ADB, PC_PARA_A12_GERENCIA, ARENA_CONTROLES_PARA_PC, A12_PARA_INTERNET.
- Conta `parise_core_api` (só firewall, só aceita login vindo de 10.0.10.50); usuário e senha estão no `.env`.
- `python scripts\provisionar_rede.py --aplicar` pode ser repetido à vontade: tudo já aplicado é só conferido.

## Feito em 09/11, à noite
- Descrições nas interfaces, WAN2 como reserva (distância 20) e reservas `MAC_CONTROLE_1`/`MAC_CONTROLE_2` (10.0.30.10 e .11) no `provisionar_rede.py`, já aplicados.
- `scripts/sentinela_a12.py` (parte B). Liga/desliga da regra 2 testado no aparelho, a partir do PC. **Instalado no A12 em 12/11 (modo só telemetria; ver o fim deste arquivo).**
- Revisão da pilha nova `parise-infra` (docker-compose: Tailscale, Caddy, AdGuard, parise-core, ARENA, Filebrowser, Kuma). Correções feitas: `.gitignore` voltou a proteger `*.local.md` e `logs/`; o Filebrowser só enxerga `data/files`; token comparado em tempo constante; `modules.json` gravado com trava e de forma atômica.
- `scripts/bot_chat_a12.py` (parte C): comandos !status_lab, !adb_on, !adb_off, !farol_sed (ainda só avisa que não existe) e !ajuda. Só obedece ao `CHAT_DONO`. Falta: conta e sala no servidor Matrix (o protocolo de chat), token e instalar no A12.
- **Todos os projetos ligados à infra:** `scripts/projetos_infra.py`:
  - `verificar` aponta pastas sem registro, registro sem pasta e caminhos velhos nos CLAUDE.md;
  - `dns` cria `<nome>.bancada.lan` -> HUB_IP no FortiGate;
  - `registrar` cadastra no parise-core.

  A lista de projetos vem do REGISTRO do `parise-core-windows`; o papel de cada um na rede fica em `config/projetos-infra.json`. Domínio único: `bancada.lan`. Os caminhos das pastas renomeadas e do ARENA foram corrigidos no REGISTRO e nos CLAUDE.md.
- **Nome antigo dos agentes removido (09/11):** tudo virou parise-core (`-windows`, `-android`) no parise-sync, nos dois agentes, no Android Embeeded, na vitrine, no kit, nas skills e no CLAUDE.md global. Ficaram de fora: o ARENA (lá a palavra é matriz gráfica dos emuladores), os arquivos Java (usam `android.graphics.Matrix`) e o nome técnico do protocolo de chat do bot (biblioteca `matrix-nio`).
- **Nome novo em toda parte (09/11, noite):**
  - GitHub: `parise-core-android` e `parise-core-windows` renomeados (o endereço antigo redireciona); descrições e texto da release da vitrine trocados; os 5 repositórios enviados.
  - Hermes: reinstalado (`instalar.ps1 -Aplicar`); skill antiga guardada na TEMP; comentários e bloqueio antigo tirados do `config.yaml` (cópia `.bak-parise-core-*`); cache de skills refeito.
  - Celular: troca aplicada no próprio Termux (o comando agora é `parise-core`; `ia`, memória, Qwen e boot), com backup em `~/.cache/backup-antes-parise-core.tgz`; kit reenviado; pasta `Pictures/Icones-parise-core`; APK de ícones recompilado ("Icones parise-core"; não estava instalado e continua sem instalar).
- Pendente do Rafael: registrar ou deixar fora a pasta `Criador De Apps Pedagógicos` (ARENA-alunos); preencher `HUB_IP` quando escolher a máquina da pilha.
- **Decisão pendente do Rafael:** onde roda a pilha docker. O `bootstrap.sh` é para Linux, o A12 não roda Docker e o Windows não serve para o Tailscale em modo host. Também falta escolher entre o DNS do FortiGate (`bancada.lan`) e o AdGuard (`parise.lan`).

## Lições (FortiOS 5.4 no 60D)
- A API REST não cria regras de firewall (405) nem admins (403). As regras vão por restore da configuração; os admins, pelo CLI via SSH.
- Depois de um tempo ligado, o CLI travou (SSH mudo e restore falhando) e voltou com o reboot pela tomada.
- O curl do PowerShell estraga a senha com caracteres especiais. Usar o Python (`fortigate_api.py`).
- O CLI travou de novo poucas horas depois do reboot. Com ele travado, o PUT em `system/global` passa do tempo, mas renomear e gravar objetos, contas e DNS pela REST funciona. Para renomear pela REST, faça PUT com o novo `name`: as regras que usam o objeto se atualizam sozinhas. [Palpite] As sessões SSH abertas pelos scripts podem ser o gatilho do travamento.

## Falta (físico)
1. ~~Ligar a **WAN1** ao roteador da casa.~~ Feito em 12/11/2026 (ONT Huawei na WAN1, 192.168.18.40).
2. **Hub do A12** na DMZ. Preencher o `MAC_A12` no `.env` e rodar `--aplicar` de novo.
3. Switch da ARENA na **porta 2**.

## Depois
- Parte B: o sentinela do A12, com login de sessão (`FORTIGATE_API_USUARIO` e `FORTIGATE_API_SENHA`), porque o 5.4 não tem token de API. Problemas do rascunho no fim de `docs/decisoes-provisionamento.md`.
- Plano B por cabo console: o `config/fortigate-bancada.conf` ainda usa `internal1` e o modo de portas do 6.x.
- Este PC: (até 12/11 a placa com fio tinha métrica 500; desde 13/11 ela é a principal, ver o fim deste arquivo.)

## 11/11/2026 (noite): o PC como segundo hospedeiro do repasse e a telemetria sutil
- **Pedido:** "tanto o A12 possa ir na DMZ quanto o próprio PC, que ambos trabalhem juntos; funcionar com o celular,
  com celular e PC, ou sem nenhum dos dois". **Escrito em `scripts/provisionar_rede.py` e NÃO aplicado ainda**
  (o `--aplicar` faz o restore que reinicia o FortiGate; a rodada final do ARENA estava rodando no PC, e um restore
  cortado por falta de memória já derrubou o aparelho em 10/11). O modo que só mostra passou: 10 regras, 2 VIPs.
  - DHCP da DMZ: faixa .50 a .60; o `MAC_RYZEN` reservado em 10.0.10.60 (o PC no hub da DMZ) além do .100 na LAN1.
  - Objetos: `PC_RYZEN_DMZ` e o grupo `REPASSE_ARENA_HOSPEDEIROS` (A12, PC na LAN1, PC na DMZ).
  - VIPs: `ARENA_REPASSE_VIP` wan1:55440 -> A12; `ARENA_REPASSE_VIP_PC` wan1:55441 -> PC 10.0.20.100:55440 (o 5.4
    leva uma porta externa a um só endereço; o PC na DMZ não tem VIP, mas tem internet e vê o A12 no mesmo hub).
  - Regras novas: 8 `PC_DMZ_PARA_INTERNET`, 9 `INTERNET_PARA_REPASSE_PC`, 10 `CONTROLES_PARA_REPASSE_PC`; a 7 passa a
    usar o grupo. DNS: `repasse.bancada.lan` (A12) e `repasse-pc.bancada.lan` (PC).
  - Sem nenhum hospedeiro ligado, nada quebra: o ARENA cai nos repasses públicos do RetroArch.
  - **PRÓXIMO PASSO:** `python scripts\provisionar_rede.py --aplicar` com o PC folgado (sem emulador nem rodada), e
    conferir pela API as 10 regras e os 2 VIPs.
- **Telemetria sutil** (`scripts/telemetria.py`, `docs/telemetria.md`): tarefa `Telemetria-Bancada` de 5 em 5 min,
  bruto em `data/telemetria/`, resumo em `memoria/telemetria/RESUMO.md` (lido pelo Hermes, pelo Qwen e pelo Claude);
  o sentinela do A12 ganhou a amostra local (`amostrar`), mas o sentinela ainda não está instalado no A12 (parte B).
  Só saúde de equipamento; nada de aparelho de aluno. Primeira amostra em 11/11 às 18:57: FortiGate respondendo,
  WAN1/DMZ/LAN2 sem enlace (físico pendente), PC com 5,3 GB livres, A12 no cabo com 67% de bateria.
- **Porta USB MGMT do 60D:** ligada por cabo de dados em 11/11, o Windows mostrou "Dispositivo USB desconhecido (falha
  na redefinição de porta)": confirma o `docs/equipamento-fortigate-60d.md` (só FortiExplorer). O console é o RJ-45.
- **APLICADO em 11/11, 19h10** (PC folgado): `provisionar_rede.py --aplicar` passou inteiro, o restore reiniciou o
  aparelho e ele voltou em 10.0.20.1. Conferido pela API: 10 regras, os 2 VIPs (55440 -> A12, 55441 -> PC 55440), o
  grupo `REPASSE_ARENA_HOSPEDEIROS` com os 3 membros, o DHCP da DMZ de .50 a .60 com o .60 reservado ao PC, e o DNS
  com `repasse` e `repasse-pc`. O "próximo passo" acima está feito; falta só o físico (WAN1, hub do A12, switch).

## 12/11/2026, 6h30: o sentinela do A12 instalado (parte B, modo só telemetria)

- `scripts\instalar_sentinela_a12.py instalar` (pelo cabo, como o `repasse_a12.py`): copia o sentinela e a
  `fortigate_api.py` para `~/parise-sync/`, o comando `sentinela` (`celular-kit/bin/sentinela` da casa-mãe) para
  `~/bin/` e o `iniciar-a12` para `~/.termux/boot/` (agora sobe o sentinela no boot e confere de hora em hora). Ligado:
  uma amostra por minuto em `/sdcard/parise-sync/telemetria/amostras.jsonl`; a primeira completa às 06:25 (27,9 °C,
  100% de bateria, 4 ms ao roteador da casa, Wi-Fi a -52 dBm, 17,7 h ligado, 1,6 GB livres), e o `telemetria.py
  coletar` do PC a levou ao `RESUMO.md`.
- **Sem `~/.parise-sentinela.env` o sentinela roda em modo só telemetria** (não fala com o FortiGate). A senha da API
  só vai para o celular quando ele estiver na DMZ (hub na porta DMZ, `MAC_A12` no `.env`, `--aplicar`); aí o jeito é
  mandar a conf pela entrada padrão do `termux.ps1 -LerEntrada` (nunca por argumento) e `sentinela desligar && ligar`.
- Achados do Android 12 no Termux: `/proc/uptime`, `/proc/net/route` e `/proc/net/tcp` negados; `ip` não existe;
  `termux-wifi-connectioninfo` dá o IP e o RSSI (BSSID e MAC vêm mascarados). O sentinela usa `CLOCK_BOOTTIME`, o
  FortiGate da conf ou o `.1` da rede do Wi-Fi, e o Termux:API.
- Alerta de hoje no RESUMO: "FortiGate: CPU chegou a 85%" (um pico; mediana 0%). Hipótese: o restore/boot de ontem
  ou a própria API de monitoramento a cada 5 min; acompanhar nas próximas 24 h antes de mexer.
- **PRÓXIMO PASSO:** continua físico (WAN1, hub do A12 na DMZ, switch na porta 2). Depois: a conf do FortiGate no A12
  e `sentinela uma-vez` para ver a regra do ADB respondendo.

## 12/11/2026, noite: topologia nova (ONT Huawei na porta 3), PREPARADA e NÃO aplicada

- O Rafael ligou a ONT Huawei EG8145X6-10 (192.168.18.1, DHCP 192.168.18.0/24) na **porta 3** do FortiGate. A porta 3
  é do switch `internal` (LAN1): ficou um segmento só com dois DHCP (Huawei e FortiGate). Até decidir: tirar o cabo
  da porta 3. O mini-USB de trás não é console de CLI (só FortiExplorer); o console é o RJ-45 da frente.
- **Opção A (recomendada):** cabo da ONT na WAN1, que já está configurada e conferida; nada a aplicar; pôr
  `FORTIGATE_UPLINK=wan1` no `.env`.
- **Opção B (escrita):** `scripts/provisionar_rede.py` com `--uplink internal3` (o padrão): tira a porta 3 do
  switch, DHCP nela só com ping (distância 10), WAN1 com distância 15 e sem regra, regras 1/5/6/8/9 e os 2 VIPs na
  `internal3`. Novos: `--mostrar-cli` (sem conectar), `--conferir` (só lê) e a conferência da interface de cada
  regra/VIP. Testes offline em `tests/test_provisionar_rede.py`.
- Tudo (desenho, duplo NAT, Huawei/Epuser, CGNAT, ordem dos passos com o desfazer, riscos):
  `docs/TOPOLOGIA-2026-11-12.md`.
- **PRÓXIMO PASSO (Rafael):** escolher A ou B. B precisa de autorização para `--conferir` e `--aplicar`. Depois, na
  Huawei: reserva de DHCP do FortiGate e mapeamento TCP 55440/55441 (ou DMZ); conferir CGNAT; teste pelo 4G.

## 12/11/2026, ~18h50: ONT Huawei na WAN1 (opção A) — conferido
- O Rafael passou o cabo da ONT Huawei EG8145X6-10 da porta 3 para a WAN1. O FortiGate pegou 192.168.18.40 por DHCP,
  com rota padrão; `provisionar_rede.py --conferir --uplink wan1`: regras e VIPs batem com o desenho. Nada foi aplicado.
- Teste com rota temporária (apagada): PC → 10.0.20.1 → 192.168.18.1 → 172.29.0.7 (operadora) → HTTPS ok em 0,2 s.
- `.env`: FORTIGATE_UPLINK=wan1. A porta 3 continua no switch da LAN1 (sem cabo da ONT: sem DHCP duplo).
- O PC ainda sai pelo Wi-Fi da Huawei (métrica 30) antes do cabo (métrica 1000): o tráfego dele não passa pelo
  FortiGate. Mudar a métrica é decisão do Rafael.
- Falta conferir: CGNAT (o salto 172.29.x é rede interna da operadora; comparar o IP WAN da Huawei com o IP público)
  e se o Epuser deixa encaminhar a 55440/55441 para 192.168.18.40 (ou DMZ). Ver docs/TOPOLOGIA-2026-11-12.md.

## 13/11/2026: a WAN1 é o padrão; o PC sai pelo cabo do FortiGate (conferido pelo Rafael)
- ONT Huawei EG8145X6-10 (192.168.18.1) na WAN1 do FortiGate 60D (FortiOS 5.4.10): DHCP 192.168.18.40, 1000 full,
  sem erros. A porta 3 voltou a ser só LAN1. `.env` com `FORTIGATE_UPLINK=wan1`; `--conferir --uplink wan1`: regras
  e VIPs batem. Regra 1 sem UTM, com offload.
- O PC sai pelo cabo: "Ethernet 2" com métrica 10 e rota padrão com métrica 0; o Wi-Fi (Intel AX210, na Huawei)
  com métrica 50, reserva automática. Medido: cabo 6,6–7,1 ms e 228–411 Mbit/s; Wi-Fi 7,5–7,8 ms e 183–300 Mbit/s.
- `scripts/provisionar_rede.py`: `UPLINK_PADRAO = "wan1"` (a `internal3` continua como opção B, `--uplink
  internal3`). Testes atualizados (43 passam). `docs/TOPOLOGIA-2026-11-12.md` ganhou a seção "Situação em uso".
- **CGNAT suspeito, não confirmado:** o 3º salto é 172.29.0.7 (privado da operadora). Falta: IPv4 da WAN na tela
  da Huawei (100.64–100.127, 10., 172.16–31. ou 192.168. = CGNAT) comparado com o "meu IP" de um site.
- **PRÓXIMO PASSO (Rafael):** conferir o CGNAT na Huawei. Sem CGNAT: reserva de DHCP do 192.168.18.40 e mapeamento
  TCP 55440/55441 (ou DMZ) na Huawei, depois o teste pelo 4G. Com CGNAT: Tailscale ou os repasses públicos do
  RetroArch. Ainda físico: hub do A12 na DMZ e switch da ARENA na porta 2.

## 13/11/2026, ~20h: CGNAT CONFIRMADO (o ARENA conferiu sozinho)
- A ONT Huawei respondeu pelo UPnP (sem senha): o IP da WAN dela é **100.66.29.193** (faixa 100.64.0.0/10, a do
  CGNAT). A internet vê a casa por um IP público compartilhado da operadora (não anotado aqui). Logo: **nada de fora chega** (nem a 55440 do repasse no A12, nem
  a 55441 do PC); encaminhar porta na Huawei ou no FortiGate não resolve.
- Saídas: pedir à operadora um IP público (algumas fazem sem custo; "IP fixo" costuma ser pago) ou usar o caminho que
  o ARENA passa a ter: o retransmissor público do RetroArch (southamerica-east1.relay.retroarch.com:55435), com o
  código da sala trocado entre as pessoas (sem lista pública, sem apelido). O repasse no A12 continua valendo dentro
  de casa e para quando houver IP público.
## 13/11/2026, noite: desempenho medido e acesso remoto pelo celular
- **Aplicado:** DNS do FortiGate de FortiGuard (EUA, 112-116 ms por nome novo) para 1.1.1.1 e 8.8.8.8 (12 ms), pela
  API, sem reiniciar (`scripts\otimizar_fortigate.py`, backup em `logs\backup-antes-otimizacao.conf`).
- **Testado e desfeito:** modelador do PC na regra 1 (420/400 Mbit/s). O envio do PC caiu de 396 para 111 Mbit/s com
  a CPU do 60D a 99%. Motivo de tentar: com o PC a 468 Mbit/s, o A12 no Wi-Fi da casa perdia 31% dos pings
  (`scripts\medir_bufferbloat.py`). Saída sem custo: limite no próprio programa que baixa.
- **Acesso remoto pronto e testado pelo 4G:** Tailscale (exit node oferecido, modo sem login), RDP só pela rede do
  Tailscale e pela sub-rede local, PC sem suspender. Pelo 4G a ligação com o A12 ficou direta.
- **Explicado ao Rafael:** DMZ não dá desempenho (e com CGNAT nada entra); a casa não passa pelo FortiGate (nada a
  ajustar quando o PC desliga); a antena do PC não repete o Wi-Fi da ONT e no 2,4 GHz atrapalharia.
- **A12:** saiu do USB durante a medição (o adb perdeu o aparelho às ~21h); continua no Tailscale. Ligar o cabo de novo.
- Tudo: `docs/DESEMPENHO-E-ACESSO-REMOTO.md`. **PRÓXIMO PASSO:** físico da DMZ (switch + adaptador do A12), depois o
  Wake-on-LAN pelo A12.
- **~21h30: o A12 foi para a DMZ pelo hub (Rafael).** Conferido pela API: porta DMZ com enlace (100 Mbit/s full, o
  adaptador USB 2.0), o A12 pegou **10.0.10.50** (ainda sem reserva: `MAC_A12` vazio no `.env`), rota do FortiGate
  certa (`router/lookup`: 10.0.10.0/24 -> dmz). **Mas o PC não alcança o A12 pela DMZ:** ping e tracert para
  10.0.10.50 morrem (o tracert mostra o 2º salto na ONT); pelo Tailscale ele responde em 5-8 ms, via a ONT. Suspeita:
  o Android com Wi-Fi + cabo + VPN responde pelo caminho errado. **Falta, com o adb** (o Rafael vai ligar a
  depuração; com o hub no lugar do cabo, é a **depuração sem fio**): `ip rule`, `ip route show table all`,
  `dumpsys connectivity` (qual rede é a padrão), e testar com o Wi-Fi do A12 desligado. Depois: `MAC_A12` no `.env` e
  `provisionar_rede.py --aplicar` para a reserva, e o Wake-on-LAN do PC pelo A12.
- **~21h, resolvido: o A12 na DMZ funcionando** (depuração sem fio, `adb connect` pela Wi-Fi da Huawei). Duas causas:
  1. **Filtro de DNS da DMZ quebrado desde 10/11:** o `provisionar_rede.py` gravava o campo do 6.x
     (`domain-filter`), que o 5.4 ignora: a lista `*.samsung.net` nunca ficou ligada, e, sem licença da FortiGuard e
     sem `error-allow`, TODO nome da DMZ ia para a página de bloqueio 208.91.112.55. O Android reprovou o cabo
     ("sem internet") e respondia ao PC pelo Wi-Fi. Corrigido no FortiGate (pela API) e no script
     (`urlfilter-table: 1`, `ftgd-dns options error-allow`).
  2. **Rota conectada velha no FortiGate:** a tabela (API) dizia 10.0.10.0/24 -> dmz, mas as sessões novas do PC
     saíam pela wan1 (a rota presa de quando a porta estava sem cabo). Derrubar e religar a `dmz` pela API resolveu.
     Lição: depois de ligar um cabo numa porta que estava sem enlace, conferir com `tracert` e, se preciso, `status
     down/up` na interface.
- Conferido depois: ping PC -> A12 <1 ms, A12 com o cabo validado e como rede principal (internet 43-68 ms), repasse
  do ARENA (55440) aberto pela DMZ, reserva do DHCP 10.0.10.50 (A12) e .60 (PC) gravada, `MAC_A12` no `.env`.
  O Tailscale PC <-> A12 vai pela ONT (4 ms): a regra 3 não libera o UDP dele, e não vale abrir só por isso.
- **PRÓXIMO PASSO:** Wake-on-LAN do PC pelo A12 (regra DMZ -> LAN1 só UDP 9 e ARP fixo do PC; regra nova = restore,
  que reinicia o FortiGate) e a conf do sentinela no A12 (senha da API pela entrada padrão do termux.ps1).
- **13/11, noite: Wake-on-LAN aplicado no FortiGate** (`provisionar_rede.py --aplicar`, restore e reinício; o PC seguiu
  pelo Wi-Fi de reserva). Conferido depois: 11 regras com a 11 `A12_LIGA_PC_WOL` (dmz -> internal, WOL_UDP9 e PING,
  sem registro), ARP fixo 10.0.20.100 na internal, DNS 1.1.1.1/8.8.8.8 e o filtro da DMZ corrigido (o restore parte do
  backup atual: nada de hoje se perdeu), rota da DMZ direta (<1 ms).
- **Falta no A12** (a depuração sem fio desliga a cada reinício; o Rafael religa): `instalar_sentinela_a12.py
  instalar` e `conf` (senha da API e chave do ligar-pc pela entrada padrão), "Run as exit node" no app do Tailscale
  + o clique de aprovação dele no painel, e a economia de bateria do Tailscale desligada. Os atalhos do Android
  Embeeded já usam a DMZ direta (adb-remoto, 88370bb). Proxy do hotspot pronto (`compartilhar`), DNS família só com
  `--familia`.
