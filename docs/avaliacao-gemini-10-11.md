# Avaliação da conversa do Gemini (10/11/2026)

Pedido do Rafael: "faça todas as implementações ... que o gemini me disse que era possível". A conversa
(`share.gemini.google/VM7NGc9PJLgK`, "FortiGate 60D: Projetos e Laboratório de Redes") foi lida inteira. Cada proposta
recebeu uma decisão com o motivo. A ideia é usar esta lista também como exemplo de tomada de decisão em aula: uma IA
dizer que algo "é possível" não basta. É preciso conferir se o aparelho aceita, se é seguro, se custa dinheiro e se
fere uma regra do projeto.

**Antes de tudo, a segurança.** A conversa é pública. Conferi: a "chave de API" que aparece (`ARENA_API_ROOT_2026`), as
senhas e os MACs são exemplos inventados pelo Gemini, e não há número de série. Nada real vazou. Mesmo assim, uma
conversa pública não deve ter dado do equipamento: os dados de verdade ficam só no `.env` e no `equipamento.local.md`.

## Já estava feito (e foi aplicado no FortiGate em 10/11, à noite)

| Proposta do Gemini | Onde está |
|---|---|
| Rede separada para os controles (internal2, DHCP, reservas P1 e P2) | `provisionar_rede.py`: LAN2 10.0.30.0/24, reservas .10 e .11 |
| QoS para o controle do ARENA | shapers e DSCP no FortiGate. **Corrigido:** o Gemini usou a porta 8080; o celular como controle do ARENA usa a **8780** |
| DNS local (`arena.local`, `parise-core.local`) | DNS do FortiGate em `bancada.lan` (`arena`, `a12`, `fortigate`) |
| Bloquear a telemetria `*.samsung.net` | filtro de DNS na DMZ |
| ADB (5555) e gerência do A12 só a partir do PC | regras `PC_PARA_A12_ADB` e `PC_PARA_A12_GERENCIA` |
| IP fixo e DHCP por interface | LAN1 .20, DMZ .10 (um IP só, o do A12), LAN2 .30 |
| WAN2 como reserva da WAN1 (distância 10/20) | aplicado. Sem a "verificação de link", a troca só acontece com o cabo fora [Provável] |
| Bloquear 10.0.0.0/8 saindo pela WAN | as regras só liberam o que precisa; o resto já é negado |
| Syslog para o PC | aplicado (porta 514) |
| Sentinela no A12 que liga e desliga a regra do ADB pela API | `scripts/sentinela_a12.py` (testado do PC; falta rodar no A12) |
| Bot de chat (`!status_lab`) | `scripts/bot_chat_a12.py` (falta o servidor de chat e a conta) |
| Medir a latência do controle | o ARENA mede o ping na partida; os registros do FortiGate vão para o syslog do PC |

## Feito agora

- **Repasse do ARENA pela internet** (VIP wan1:55440 → A12, regras 6 e 7). Não estava na conversa, mas é a mesma ideia: o
  PC vira "só mais um jogador".
- **Marcar os pacotes do controle com prioridade (DSCP EF) no próprio ARENA** (item 2 do Gemini, a parte do código):
  **decidido não fazer**, e é um bom exemplo de "possível" que não ajuda. Os toques vão do celular para o PC, e quem
  marcaria esses pacotes é o navegador do celular, que não deixa a página escolher. O PC só manda respostas pequenas.
  No Windows, a marcação feita pelo programa é ignorada sem uma política de grupo de administrador [Provável]. O
  FortiGate já reconhece o controle pela porta (8780) nos dois sentidos e dá a prioridade lá: é o lugar certo.

## Não vou fazer, e o porquê

| Proposta | Decisão |
|---|---|
| Transmitir o jogo (OBS) pela WAN2 com rota por política | **Não.** No ARENA, gravação e transmissão ficam desligadas de propósito: os alunos são menores de idade |
| Bot que entra na SED/Gov.br com a sua senha, lê o diário e resolve o captcha | **Não.** É login de terceiro e dado de aluno: fere a LGPD e os termos da SED. Também não existe API oficial (o próprio Gemini disse) |
| App na Play Store com assinatura e nuvem paga | **Não.** Custa dinheiro (conta de desenvolvedor, servidor) e entra no mesmo problema de dado de aluno |
| Resgate da senha pelo usuário `maintainer` (serial + `bcpb`) e reset de fábrica | **Não sem a sua ordem.** Apaga tudo e o aparelho é da escola. Hoje não precisa: a senha está no `.env` |
| Chave de API com perfil `super_admin` no script | **Não.** O FortiOS 5.4 nem tem chave de API. A conta `parise_core_api` é só de firewall e só entra vindo do A12 |
| "Kill-switch" pelos fios da porta USB MGMT | **Não dá.** Essa porta só fala com o programa da Fortinet: não corta a rede de ninguém |
| Isolar o netplay com Virtual Wire Pair | **Não.** O próprio Gemini se contradiz depois: o par de portas fica sem IP. A rede separada (LAN2) resolve |
| "Emular atraso" (jitter) pela linha de comando | **Não.** O comando mostrado não atrasa nada |
| Zero-trust: o A12 lê as conexões e bloqueia quem tocar na 5555 | **Não por enquanto.** Pode bloquear o próprio PC, e sem root o Android não mostra as conexões dos outros apps [Provável]. A regra do FortiGate já faz isso |
| Desligar o ADB acima de 45 °C | **Depois.** Ler a temperatura sem root funciona em alguns aparelhos [Palpite]; o limite de 45 °C é palpite do Gemini. Medir no A12 antes |
| Captive portal, rotas por porta, sniffer, Blue Team x Red Team, OSPF/BGP com VyOS | **Bons para aula, não para a bancada ligada.** Viram atividade prática separada, num laboratório fechado, nunca na rede da escola |
| VLAN 802.1Q, FortiAP, monitor no HDMI do A12 | **Faltam aparelhos** (switch com VLAN, AP da Fortinet, hub com HDMI). Nada comprado sem você pedir |
| Tailscale ligando as três redes | **Ainda não.** Exige conta (grátis, mas sua) e deixaria a tela de administração do FortiGate alcançável de fora. Está na decisão pendente da pilha docker |
| Scripts "unificados" de provisionamento (3 versões) | **Não usados.** Nenhum foi testado pelo Gemini. O `provisionar_rede.py` é o testado no aparelho de verdade |

## Compras citadas pelo Gemini

Cabo USB-C para Mini-USB, cabos Cat6, switch, adaptador USB-C para rede e hub com HDMI. Nada é necessário para o que
está ligado hoje, a não ser o **hub do A12** (para ele ficar na DMZ pelo cabo e na tomada). O Gemini não conferiu preço
nem estoque.
