# Desempenho da rede e acesso remoto ao PC (13/11/2026)

Pedido do Rafael: o melhor desempenho possível para o PC e a infraestrutura, sem piorar o Wi-Fi da casa (TV Philco,
Redmi 9i Sport, o celular dele e o A12), o PC como DMZ junto com o celular, o Tailscale para usar o PC de longe pelos
dados móveis, e a antena Wi-Fi do PC ajudando o Wi-Fi da casa. Regra seguida: **só muda o que a medida justifica, e
nada que tire desempenho**.

## A casa, como ela é (conferido)

```
internet (CGNAT da operadora) ── ONT Huawei 192.168.18.1 ──┬── Wi-Fi da casa: TV, Redmi, celulares, A12 (2,4 GHz)
                                                            └── WAN1 do FortiGate 60D ── LAN1: PC (cabo, 10.0.20.100)
```

- **A TV e os celulares não passam pelo FortiGate.** Eles estão no Wi-Fi da ONT. O FortiGate só carrega o PC (e,
  quando o físico estiver pronto, o A12 na DMZ e os controles na LAN2) [Certo: topologia de 13/11].
- **CGNAT confirmado** (a ONT tem 100.66.29.193; a internet vê outro endereço): nada de fora entra, nem com porta
  aberta, nem com DMZ [Certo].
- **Sem IPv6** da operadora no PC (nenhum endereço global) [Certo: `diagnostico_desempenho.py`].

## Medido e mudado

| O quê | Antes | Depois | Como |
|---|---|---|---|
| DNS do FortiGate (todo site novo do PC) | FortiGuard, nos EUA: **112 a 116 ms** | Cloudflare 1.1.1.1 (reserva Google 8.8.8.8): **12 ms** | `otimizar_fortigate.py --aplicar dns` (pela API, sem reiniciar); voltar: `--desfazer dns` |

Medidas: `scripts\medir_dns.py` (duas rodadas iguais). O nome inventado de `example.com` continua lento por qualquer
caminho porque o servidor dele fica nos EUA; com nomes de servidor próximo, o FortiGate ficou igual à Cloudflare
direta (12,3 contra 12,5 ms). Backup da configuração inteira antes da primeira mudança: `logs\backup-antes-otimizacao.conf`
(fora do git).

## 14/11/2026 (madrugada): mais três achados, medidos

| O quê | Antes | Depois | Como |
|---|---|---|---|
| A "rota presa" da DMZ: o PC não alcançava o A12 com o enlace de pé | **5 h fora** (13/11 21:14 até 14/11 02:49, depois do restore do Wake-on-LAN, que reinicia o FortiGate) | <1 ms; a telemetria conserta sozinha (no máximo 1 vez a cada 30 min) e o `provisionar_rede.py` confere depois de cada restore | `scripts{B}religar_dmz.py` (derruba e religa só a `dmz`, ~3 s) |
| Syslog do FortiGate | o registro de CADA sessão ia ao PC, e o firewall do Windows jogava tudo fora | só os eventos (enlace, reinício, administração), guardados sem MAC e sem DHCP | `otimizar_fortigate.py --aplicar syslog` e `scripts{B}syslog_eventos.py --instalar` |
| Relógio do FortiGate | fuso "04" (Pacífico, EUA) com horário de verão: registros **5 h atrasados** | fuso "18" (Brasília), sem horário de verão (o Brasil acabou com ele em 2019; o 5.4.10 é de 2018) | `otimizar_fortigate.py --aplicar relogio` |

**O FortiGate 60D não tem rádio**: ele não "transmite sinal". O Wi-Fi da casa é o da ONT Huawei. No caminho com fio
não há o que ganhar: **PC → FortiGate 0,70 ms, PC → internet 8,9 ms** (conexão TCP; o `pktmon` mostra a resposta em
menos de 1 ms). Cuidado ao medir: com tempo-limite no socket, o Python do Windows soma ~10 ms a cada conexão (espera
pelo `select()`); as medidas acima são com a conexão bloqueante. As 11 regras estão com aceleração e sem UTM; MTU
1500 e enlaces 1000/100 full sem erros; `provisionar_rede.py --conferir` bate com o desenho.

**Painel ao vivo** (atalho "Infraestrutura da casa"): atualiza a cada 3 s com uma sessão só no FortiGate (antes,
uma foto em 8,6 s, porque esperava 2 s por porta fechada, uma de cada vez): CPU, memória, sessões, enlace e vazão de
cada porta, latência real da internet, o A12 e o Tailscale (a cada 15 s), e avisa a rota presa.

**Hardware e sensores no painel (14/11, ~03h20):** o que cada aparelho deixa ler está em `scripts\hardware_casa.py`.
O FortiGate 60D não tem sensor de temperatura nem de energia (o FortiOS 5.4 dele nem tem `execute sensor list`).
O Windows deste PC também não expõe temperatura nem consumo (sem zona térmica nem medidor de energia nos contadores);
o caminho grátis é o LibreHardwareMonitor 0.9.6, que usa o driver PawnIO (de kernel, instalado à parte) e entrega
tudo em `http://127.0.0.1:8085/data.json`, que o painel já lê se existir. Instalar driver de kernel fica para o
Rafael decidir. O A12 dá temperaturas pelo serviço térmico do Android (o `/sys` é barrado ao adb) e a corrente da
bateria pelo `dumpsys battery`.

**Teste de internet confiável (tecla T):** 4 fluxos por 8 s (um só fluxo não enche a fibra), latência parada e com
carga (o bufferbloat), e a conferência pela WAN1 do FortiGate no mesmo intervalo: se o FortiGate vê muito mais do que
o teste mediu, outra coisa estava usando a internet; se vê quase nada, o teste falhou (aconteceu: a Cloudflare limitou
com 429, e a conferência mostrou só 4 Mbit/s entrando). Medido às 03h12: **610 Mbit/s de download, 465 de envio,
latência 8,2 ms parada e +2 ms com carga.**

**Candidato, sem medida que justifique ainda:** a regra 5 (`A12_PARA_INTERNET`) registra todo o tráfego (`log all`),
inclusive quando o A12 é a saída da VPN. Com a CPU do 60D em 0% parado, não mexi. Medir com o A12 de saída da VPN
sob carga; se a CPU subir, passar para `utm`.

## Medido e NÃO mudado (com o motivo)

- **Modelador de tráfego no FortiGate: não serve no 60D.** A ideia moderna contra o "bufferbloat" é segurar o PC
  um pouco abaixo do limite da linha, para a fila da ONT nunca transbordar. Medido com o A12 no Wi-Fi da casa
  (`scripts\medir_bufferbloat.py`): com o PC baixando a 468 Mbit/s, o A12 perdia **31%** dos pings (a mediana quase
  não mudava); enviando a 445 Mbit/s, 10%. Com o modelador (420/400), o envio do PC **caiu para 111 Mbit/s** e a CPU
  do FortiGate foi a **99%**: o tráfego modelado sai do acelerador de hardware. Regressão grande; desfeito na hora.
  O que funciona sem custo: limitar só o programa que baixa muito quando a casa estiver usando (Steam: Configurações
  → Downloads → Limitar a banda; rclone: `--bwlimit`).
- **Placa de rede do PC (Realtek 2.5GbE):** já está bem: sem "Ethernet verde", o Windows não a desliga, os
  descarregamentos ligados. Fica como está. O TCP do Windows está no padrão moderno (ajuste de janela normal, HyStart,
  PRR, Fast Open) [Certo: `netsh int tcp show global`].
- **Controlador de Wi-Fi do FortiGate** (o 60D não tem rádio): ganho desprezível (memória em 16%) e não conferi se
  o 5.4 reinicia para desligar. Não mexi.

## "O PC como DMZ, junto com o celular": por que não ajuda

- No FortiGate, a **DMZ é só outra porta**, com outras regras. O PC na DMZ anda na mesma velocidade que na LAN1: as
  duas passam pelo mesmo acelerador [Provável: o 60D acelera as duas da mesma forma; conferido que a regra 1 está
  com offload]. A DMZ com o A12 (10.0.10.50) e o PC (10.0.10.60) está configurada desde 11/11, e **o A12 está nela
  desde 13/11** (pelo hub USB, 100 Mbit/s): validado, com reserva no DHCP e o repasse do ARENA respondendo. Para
  isso foi preciso consertar o filtro de DNS da DMZ e a rota presa no FortiGate (ver `memoria/ESTADO.md`).
- "DMZ" no sentido de abrir o computador inteiro para a internet: com CGNAT **não chega nada de fora**, e, se
  chegasse, deixaria o PC exposto. O acesso de longe vai pelo Tailscale (abaixo), que liga para fora e atravessa o
  CGNAT.

## "Identificar quando o PC desliga": não precisa

A casa não passa pelo FortiGate, então não há o que reajustar quando o PC desliga: com ele desligado, a internet da
ONT fica toda para a casa, sozinha. O que o PC pode fazer contra a casa é encher a linha (a perda de 31% acima); o
remédio é o limite no programa, enquanto o PC está ligado. Para saber se o PC está ligado de longe: o app do Tailscale
mostra "rafaparise" online ou offline.

## Antena Wi-Fi do PC "ajudando" o Wi-Fi da casa: não dá, e atrapalharia

- O Windows não faz repetidor da mesma rede (nada de malha, nada de WDS), e a AX210 não aceita "rede hospedada"
  [Certo: `netsh wlan show drivers`]. O que existe é o Hotspot Móvel: **outra rede**, com outro nome, por trás do PC.
- Os aparelhos da casa usam o **2,4 GHz** (o A12 só tem essa banda [Certo: canal 8, 2447 MHz, Wi-Fi 4]; o Redmi 9i
  Sport também é só 2,4 GHz [Provável: ficha técnica, não conferido no aparelho]). Um ponto de acesso a mais no
  2,4 GHz disputa o mesmo ar com a ONT: piora, não melhora.
- O ar está limpo: a varredura pelo A12 achou a rede da casa no canal 8 (−53 dBm) e só duas do vizinho no canal 3,
  sem sobreposição. Não há canal melhor para trocar.
- A "rede de jogo" (o celular-controle ligado direto no PC) segue como ideia, para quando houver pedido.

## Usar o PC pelo celular, de casa ou pelos dados móveis

**Já está pronto e testado de verdade (13/11):** com o Wi-Fi do A12 desligado (só 4G), o RDP do PC respondeu pelo
Tailscale; a ligação começou pelo servidor de apoio de São Paulo e passou sozinha a **direta** (ping de 52 a 105 ms
pelo 4G). Em casa, direta pelo Wi-Fi (4 a 9 ms).

O que já está ligado no PC: Tailscale 1.104.5 em modo sem login no Windows (sobe antes de alguém entrar), oferecendo
a saída para a internet (exit node); Área de Trabalho Remota ligada, **aceitando só a rede do Tailscale
(100.64.0.0/10) e a sub-rede local**, com a placa de cabo como rede "Pública" (a regra do RDP só vale nas
privadas); o PC nunca suspende nem hiberna na tomada.

No celular:
1. Instale o **Tailscale** e entre com a mesma conta do PC.
2. Instale o **Windows App** da Microsoft (o antigo "Área de Trabalho Remota") [Provável: nome atual na Play Store].
3. Adicione o PC pelo nome **rafaparise** (ou 100.64.119.39) e entre com o usuário e a **senha** do Windows (o PIN
   não serve para a Área de Trabalho Remota).
4. Para navegar pela internet de casa (rede pública, por exemplo): no app do Tailscale, **Exit node → rafaparise**.
   Deixe desligado no dia a dia: pelo 4G, passar por casa só soma tempo.

## Próximos passos possíveis (não feitos)

- **Ligar o PC de longe (Wake-on-LAN):** a placa já aceita ligar desligada ("Shutdown Wake-On-Lan" e "Magic
  Packet" ligados) [Certo]. Falta quem mande o pacote de dentro da LAN1 com o PC desligado: o A12 na DMZ (quando o
  físico estiver pronto), com uma regra DMZ → LAN1 só para o UDP 9 e o ARP fixo do PC no FortiGate. Conferir antes
  se a BIOS deixa ligar pela rede.
- **Limitar o envio do PC no próprio Windows** (sem custo para o FortiGate), se a perda no Wi-Fi da casa incomodar:
  `New-NetQosPolicy -Name PC_ENVIO -Default -ThrottleRateActionBitsPerSecond 380000000` [Provável: não testado].
- **IPv6 da operadora:** se um dia vier, abre caminho direto de fora (o Tailscale prefere) sem depender do CGNAT.

## Com o PC desligado (pedido de 13/11/2026)

A infraestrutura que fica sempre ligada é o **FortiGate** e o **A12 na DMZ** (na tomada). O que continua:

| Recurso | Com o PC desligado | Como |
|---|---|---|
| VPN de casa (internet de casa, criptografada, em qualquer rede) | sim, pelo A12 | Tailscale: o A12 como **saída de reserva** ("Run as exit node", aprovado no painel). Mais lenta que o PC: no Android a saída é em software [Certo: docs do Tailscale, "may be too slow for most cases"] e o adaptador do hub é de 100 Mbit/s |
| Ligar o PC de longe | sim | favorito `http://samsung-a12-de-rafa-parise:8000/ligar-pc?chave=...` (só pelo Tailscale); o A12 manda o pacote mágico (regra 11 e ARP fixo no FortiGate) |
| Saber se o PC está ligado | sim | `/estado-pc` no mesmo endereço |
| Repasse do ARENA (partida entre casas pelo código de 6 números) | sim | no A12 (55440) |
| Sentinela e telemetria do A12 | sim | no A12 |
| Webcam do celular, segunda tela, OBS, gravar jogos, Área de Trabalho Remota, ARENA do PC | **não** | são o celular servindo ao PC: ligue o PC pelo favorito antes |

**Não feito, de propósito:** repassar a rede da SEDUC "livre para todos" pelo hotspot. Seria contornar o filtro da
rede da escola para alunos menores de idade, e o Android nem manda o tráfego do hotspot pela VPN [Provável: o VpnService
cobre só os apps do próprio aparelho]. O que vale: cada aparelho **do Rafael** com o Tailscale e a saída de casa.

**Atalho no modelo dos do Estúdio:** "Infraestrutura da casa" na Área de Trabalho → `scripts\estado-casa.cmd` →
`scripts\estado_casa.py` (só lê: FortiGate, A12, Tailscale, saídas disponíveis, o que funciona sem o PC).

## Compartilhar a internet de casa no hotspot (atualizado em 13/11/2026)

O Rafael é administrador da rede da escola, com autorização, e acompanha o uso: o pedido foi refeito e está feito.
**Limite técnico:** o hotspot do Android não manda pela VPN o tráfego de quem se conecta [Provável: o VpnService cobre
só os apps do aparelho]. Por isso vai um **proxy** no aparelho que compartilha (`scripts\proxy_compartilhado.py`): ele
é um app do aparelho, então passa pela VPN até a saída de casa.

- **Celular (Termux):** comando `compartilhar` (instalado pelo `instalar_sentinela_a12.py instalar` no celular que
  estiver no `adb`). Antes: Tailscale > Exit Node > a saída de casa, com **Allow LAN access** ligado, e o hotspot
  com senha.
- **Notebook (Windows):** `scripts\compartilhar-internet.cmd` escolhe a saída (o PC se ligado, senão o A12), liga o
  acesso à rede local e abre o proxy; o Hotspot móvel do Windows se liga antes, à mão.
- **Quem entra no hotspot:** Wi-Fi > a rede > Proxy manual > o endereço que o proxy mostra, porta 8888. Vale para o
  navegador e os apps que respeitam o proxy do sistema; jogo e app que ignoram o proxy saem direto pela rede local.
- **DNS família só quando o Rafael pedir** (13/11/2026): o padrão é o DNS comum; `--familia` liga o DNS família da
  Cloudflare (1.1.1.3, malware e conteúdo adulto bloqueados). O proxy não guarda os endereços visitados (só contagens) e só atende rede local e Tailscale.
- **Criptografia:** WPA2/3 do hotspot até o aparelho, WireGuard (Tailscale) até a casa, HTTPS até o site.
- **Testado (13/11):** 6 testes sem internet (HTTP, CONNECT, recusa de lixo, DNS) e com internet: example.com e
  google.com com 200, site adulto bloqueado no modo turma. O DNS família por HTTPS foi trocado pelo DNS comum ao
  1.1.1.3: o Python do Windows não achava a raiz do certificado (e o pedido já vai dentro da VPN).
