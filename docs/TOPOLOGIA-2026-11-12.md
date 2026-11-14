# Topologia de 12/11/2026: internet pela ONT Huawei no FortiGate

## Situação em uso (13/11/2026): opção A, ONT na WAN1

**Feita só com cabo e com a métrica do PC; nenhuma configuração nova foi mandada ao FortiGate nem à Huawei.**
O Rafael conferiu tudo abaixo em 12 e 13/11/2026 [Certo: conferência dele, e `--conferir --uplink wan1`].

- **ONT Huawei EG8145X6-10 (192.168.18.1) na WAN1** do FortiGate 60D (FortiOS 5.4.10). A WAN1, em DHCP, pegou
  **192.168.18.40**, enlace 1000 full, sem erros. `provisionar_rede.py --conferir --uplink wan1`: regras e VIPs
  batem com o desenho. Regra 1 (`PC_PARA_INTERNET`) sem UTM, com offload.
- **A porta 3 voltou a ser só LAN1** (switch `internal`, portas 1 e 3 a 7), sem o cabo da ONT: acabou o DHCP
  duplo. O `.env` tem `FORTIGATE_UPLINK=wan1`, e desde 13/11 **a WAN1 também é o padrão do script**
  (`UPLINK_PADRAO = "wan1"`); a porta 3 continua como opção B (`--uplink internal3`).
- **O PC Ryzen sai pelo cabo do FortiGate:** a interface "Ethernet 2" (porta 1, 10.0.20.100) com métrica 10 e a
  rota padrão com métrica 0. O **Wi-Fi do PC** (Intel AX210, na Huawei, 192.168.18.x) ficou com **métrica 50**,
  como reserva automática da internet: se o FortiGate cair, o Windows passa a usar o Wi-Fi sozinho.
- **Medido (13/11):** cabo 6,6 a 7,1 ms e 228 a 411 Mbit/s; Wi-Fi 7,5 a 7,8 ms e 183 a 300 Mbit/s. O duplo NAT
  (Huawei e FortiGate) não pesou na latência.
- **Desfazer a métrica** (só se o Rafael pedir): `Set-NetIPInterface -InterfaceAlias 'Ethernet 2'
  -AutomaticMetric Enabled` e o mesmo para o Wi-Fi.

### Suspeita de CGNAT (não confirmada)

O 3º salto do traceroute (PC → 10.0.20.1 → 192.168.18.1 → **172.29.0.7**) é endereço privado da operadora
(faixa 172.16.0.0/12, RFC 1918) [Certo quanto à faixa]. Isso **sugere** CGNAT, mas não prova: muitas operadoras
usam endereço privado só na rede interna e ainda entregam IP público à ONT [Provável]. Falta conferir:
1. Na Huawei (Epuser), "Status > WAN Information": o IPv4 da WAN. Se começar com 100.64 a 100.127 (100.64.0.0/10,
   RFC 6598), 10., 172.16-31. ou 192.168., **é CGNAT** [Certo].
2. Comparar esse IPv4 com o "meu IP" de um site aberto no PC. Diferentes = CGNAT; iguais = há IP público (ainda
   pode mudar a cada reconexão).
3. Se for CGNAT: o repasse do ARENA de fora (55440/55441) não chega por encaminhamento nenhum. Saídas grátis: o
   Tailscale (previsto na pilha) ou os repasses públicos do RetroArch (o ARENA já cai neles sozinho). Pedir IP
   público à operadora costuma ser pago: fora da regra do Rafael. IPv6 da operadora é outra saída a estudar
   [Palpite: não conferido se a ONT entrega IPv6].
4. Se **não** for CGNAT: seguir o passo H1 (reserva de DHCP do 192.168.18.40 e mapeamento 55440/55441 na Huawei)
   e o H2 (teste pelo 4G).

## Histórico (12/11, antes da troca do cabo): duas premissas que não se sustentavam

1. **A porta 3 do 60D não é uma porta de WAN hoje: ela faz parte do switch de hardware `internal` (LAN1, portas
   1 e 3 a 7, 10.0.20.0/24).** [Certo: `memoria/ESTADO.md` e o passo "separar a porta 2" do
   `scripts/provisionar_rede.py`, que lê `system/virtual-switch/internal`.] Com o cabo da ONT ali, a rede da
   Huawei (192.168.18.0/24, com DHCP) e a LAN1 do FortiGate (10.0.20.0/24, com DHCP) viraram **um segmento só,
   com dois servidores de DHCP**. Efeitos prováveis enquanto ficar assim [Provável]:
   - aparelhos da casa no Wi-Fi da Huawei podem receber um 10.0.20.x do FortiGate e ficar sem internet (só o PC
     tem regra de saída), e o FortiGate passa a anotar o MAC deles na tabela de DHCP;
   - a placa com fio do PC pode receber um 192.168.18.x da Huawei em vez do 10.0.20.100;
   - a casa fica dentro da LAN1, ao lado do PC, sem o isolamento que o projeto queria.
   Na telemetria das 18:29 ainda aparecia só 1 endereço entregue na `internal` (o PC) [Certo:
   `memoria/telemetria/RESUMO.md`], então pode não ter acontecido ainda. **Até aplicar a opção A ou a B, tire o
   cabo da ONT da porta 3** (reversível, sem comando nenhum). **Feito em 12/11, ~18h50.**
2. **O cabo "USB mini" ligado ao PC não é um console garantido.** No 60D, o mini-USB de trás é o USB MGMT, que a
   Fortinet só documenta com o programa FortiExplorer; em 11/11 o Windows o mostrou como "Dispositivo USB
   desconhecido (falha na redefinição de porta)" [Certo: `docs/equipamento-fortigate-60d.md` e ESTADO de 11/11].
   O console da linha de comando é a porta **CONSOLE RJ-45 da frente**, com um cabo console USB↔RJ-45 (FTDI,
   CH340 ou CP210x), 9600 8-N-1. Sem esse cabo, o caminho de volta é a porta 1 (que esta mudança não toca), e no
   último caso o botão RESET (ver "Riscos").

## A melhor alternativa: ligar a ONT na WAN1 (opção A, a escolhida)

O FortiGate **já está inteiro configurado para a internet na WAN1** (aplicado e conferido em 11/11: WAN1 por
DHCP, 10 regras, VIPs `wan1:55440` e `wan1:55441`). Passar o cabo da ONT da porta 3 para a porta **WAN1** dá a
mesma topologia sem mandar nenhum comando nem reiniciar o aparelho. Desfazer: voltar o cabo.
Só faz sentido a opção B (porta 3) se houver um motivo físico para não usar a WAN1 (porta com defeito, cabo que
não alcança). **Se não houver, faça a A** e pule para "Huawei e duplo NAT".

## Desenho (13/11/2026: opção A em uso)

```
                internet (fibra GPON)
                        |
        ONT Huawei EG8145X6-10  192.168.18.1  (DHCP 192.168.18.0/24, Wi-Fi 2.4/5 GHz da casa)
                        |  cabo
     em uso: porta WAN1 | opção B (não usada): porta 3 (internal3, fora do switch)
                        |
             FortiGate 60D (FortiOS 5.4.10)  WAN1 por DHCP: 192.168.18.40, 1000 full
        ┌───────────────┼──────────────────┬─────────────────────┐
   porta 1 (+3..7)   porta 2            DMZ                 WAN2
   LAN1 10.0.20.1    LAN2 10.0.30.1     10.0.10.1           reserva, sem cabo
   PC 10.0.20.100    switch ARENA       A12 .50, PC .60
        |
   PC Ryzen: sai pelo cabo (Ethernet 2, métrica 10); Wi-Fi AX210 na Huawei com métrica 50 = reserva
   + cabo de console: RJ-45 da frente (o mini-USB de trás é só FortiExplorer)
```

## O que mudaria no FortiGate (opção B, não usada), já escrito no `provisionar_rede.py`

| Item | Antes (WAN1) | Depois (porta 3) |
|---|---|---|
| Switch `internal` | portas 1 e 3 a 7 | portas 1 e 4 a 7 (a 3 sai, como a 2 saiu antes) |
| Interface do uplink | `wan1`, DHCP, só ping | `internal3`, DHCP (`defaultgw enable`), **só ping**, distância 10 |
| Rota padrão | do DHCP da WAN1 | do DHCP da `internal3` (gateway 192.168.18.1, vem da Huawei) |
| WAN1 | internet principal, distância 10 | DHCP sem cabo, distância 15, descrição "sem cabo"; nenhuma regra aponta para ela |
| WAN2 | reserva, distância 20 | igual (também sem regra: a decisão de uma internet só continua) |
| Regras 1, 5, 8 (saída) | `dstintf wan1`, NAT ligado | `dstintf internal3`, NAT ligado |
| Regras 6, 9 (entrada do repasse) | `srcintf wan1` | `srcintf internal3` |
| VIPs `ARENA_REPASSE_VIP` (55440 → A12) e `_PC` (55441 → PC:55440) | `extintf wan1` | `extintf internal3` |
| Regras 2, 3, 4, 7, 10 (internas), QoS da 8780, shapers, DHCP, DNS `bancada.lan` | — | **não mudam** |

O script agora também confere a **interface** de cada regra e de cada VIP (antes só olhava os nomes; trocar a
interface de uma regra existente não disparava o restore). Modos:
- `python scripts\provisionar_rede.py --mostrar-cli` (sem conectar): passos e o bloco de CLI do restore.
- `python scripts\provisionar_rede.py --conferir` (entra e **só lê**, sem trocar senha): o que o `--aplicar` mudaria.
- `python scripts\provisionar_rede.py --aplicar` (reinicia o FortiGate pelo restore, uns 3 minutos).
- O padrão é `wan1` desde 13/11 (antes era `internal3`). `--uplink internal3` (ou `FORTIGATE_UPLINK=internal3`
  no `.env`) leva tudo para a porta 3. O `.env` já tem `FORTIGATE_UPLINK=wan1`.

## Huawei e duplo NAT (vale para A e B)

A casa passa a ter dois NATs: a Huawei (IP público → 192.168.18.x) e o FortiGate (192.168.18.x → 10.0.x.x).
- **Saída** (navegar, jogar on-line, repasses públicos do RetroArch): funciona sem nada a fazer.
- **Entrada no repasse do ARENA (55440 e 55441 TCP):** precisa de encaminhamento **nas duas camadas**. O
  FortiGate já tem (VIPs). Na Huawei falta um destes, para o IP que o FortiGate recebe na rede 192.168.18.0/24 (hoje 192.168.18.40, na WAN1):
  1. **Mapeamento de porta** TCP 55440 → IP do FortiGate:55440 e TCP 55441 → IP do FortiGate:55441 (preferível:
     só essas portas); ou
  2. **DMZ da Huawei** apontando para o IP do FortiGate (tudo que chega sem pedido vai para o FortiGate, que
     descarta o que não tem regra; por isso o uplink fica só com ping, nunca https/ssh).
  Antes, deixe o IP do FortiGate fixo: **reserva de DHCP na Huawei** pelo MAC do uplink (o MAC só se olha na tela
  da Huawei; não anotar em arquivo do projeto).
- **Direto pela porta 55435 (netplay sem repasse) e UPnP:** não atravessam dois NATs; o RetroArch não abre porta
  no FortiGate nem na Huawei. O desenho do ARENA já usa o repasse (55440) para isso. A 55436 UDP (descoberta de
  colegas) é broadcast e só vale dentro da mesma rede. A 8780 (celular como controle) é só da rede local:
  **nunca encaminhar**.
- Dentro de casa, um aparelho no Wi-Fi da Huawei alcança o repasse pelo IP do FortiGate na 192.168.18.x, porta
  55440 [Provável: o VIP fica na interface do uplink e a regra 6 aceita qualquer origem]. Pelo IP público, de
  dentro de casa, depende do "NAT loopback" da Huawei [Palpite].
- DNS: o FortiGate continua servindo `bancada.lan` nas três redes; para fora ele usa o DNS que a Huawei entrega
  pelo DHCP ou o da FortiGuard [Provável]. O AdGuard da pilha docker **não está rodando** (a máquina da pilha
  ainda não foi escolhida), então nada muda nele.

### O que conferir na Huawei com o usuário Epuser [Palpite nos nomes dos menus; varia por operadora]
- Se aparecem e **deixam salvar**: "Forward Rules > Port Mapping Configuration", "Forward Rules > DMZ
  Configuration" e "LAN > DHCP Static IP Configuration". Em muitas operadoras o Epuser vê o menu mas não salva, ou
  nem vê. Se não der: pedir à operadora (sem custo) o mapeamento das portas, ou o modo ponte (bridge) da ONT.
  O modo ponte muda muito: o FortiGate teria de fazer o PPPoE (credenciais da operadora) e o Wi-Fi da casa
  passaria a depender dele. **Não** usar senha de superusuário da Huawei achada na internet: é conta da operadora.
- [Provável] A operadora pode reescrever a configuração da ONT à distância (TR-069) e apagar o mapeamento; se o
  teste de fora parar de funcionar um dia, conferir a regra lá primeiro.
- **CGNAT:** na tela de status da Huawei ("WAN Information"), comparar o IPv4 da WAN com o "meu IP" de um site
  qualquer aberto no PC. Se forem diferentes, ou se o da WAN começar com 100.64 a 100.127 (faixa 100.64.0.0/10 do
  CGNAT, RFC 6598) [Certo] ou com 10./172.16-31./192.168., **não há IP público**: nenhum encaminhamento resolve.
  Saídas grátis: o Tailscale (já previsto na pilha) ou os repasses públicos do RetroArch (o ARENA já cai neles
  sozinho). IP público fixo/dinâmico da operadora costuma ser pago: fora da regra do Rafael.

## Ordem dos passos, cada um com o desfazer

| # | Passo | Quem | Desfazer |
|---|---|---|---|
| 0 | Tirar o cabo da ONT da porta 3 (para o DHCP duplo) — **feito 12/11** | Rafael, físico | recolocar |
| A1 | **Opção A:** cabo da ONT na porta WAN1; `FORTIGATE_UPLINK=wan1` no `.env` — **feito 12/11** | Rafael, físico | voltar o cabo |
| A2 | Conferir: WAN1 com enlace e 192.168.18.40; PC saindo pelo cabo (métrica 10, Wi-Fi 50) — **feito 13/11** | leitura | métrica automática |
| B1 | Backup da configuração pela tela do FortiGate (https://10.0.20.1, painel > Backup) e guardar fora do git | Rafael | — |
| B2 | `provisionar_rede.py --mostrar-cli` (sem conectar) e `--conferir` (entra e só lê) | precisa autorizar o `--conferir` | — |
| B3 | `provisionar_rede.py --aplicar`, com o PC folgado (sem emulador nem rodada: em 10/11 um restore cortado travou o aparelho). Tira a porta 3 do switch, liga o DHCP nela, leva regras e VIPs para `internal3`; o restore reinicia (~3 min) e ele volta em 10.0.20.1 | precisa autorizar | D1 ou D2 abaixo |
| B4 | Cabo da ONT na porta 3; `--conferir` deve mostrar `internal3` com 192.168.18.x e "regras e VIPs já batem" | Rafael, físico + leitura | tirar o cabo |
| H1 | Na Huawei: reserva de DHCP do FortiGate; mapeamento TCP 55440 e 55441 (ou DMZ) para esse IP | Rafael, na tela da Huawei | apagar as regras na Huawei |
| H2 | CGNAT (acima) e teste de fora: celular no 4G, ARENA > Amigos > Partidas entre casas > Testar, com `IP público:55440` (A12) e `:55441` (PC) | Rafael | — |

- **D1 (desfazer o B3 pelo script):** `provisionar_rede.py --aplicar --uplink wan1` (regras e VIPs voltam para a
  WAN1; reinicia). Depois, **D2:** devolver a porta 3 ao switch `internal` pela tela (Rede > Interfaces > internal
  > membros) [Provável]; só funciona depois do D1, porque a `internal3` não pode estar em uso por regra ou VIP.
- **D3 (desfazer tudo de uma vez):** restaurar o backup do B1 pela tela (Sistema > Configuração > Restaurar).

## Riscos

- **Perder o acesso ao FortiGate:** a mudança não mexe na porta 1 nem na LAN1, então o PC continua chegando em
  10.0.20.1 [Provável]. O momento perigoso é o restore. Se o aparelho não voltar em 8 minutos: tirar da tomada por
  10 s e esperar 3 min (já resolveu em 10/11); depois tela ou SSH pela porta 1; depois o console RJ-45 da frente
  (regra do projeto: comando só por COM de cabo console de verdade; nunca a COM da Samsung, VID 04E8); por último o
  RESET (furinho) e `provisionar_rede.py --aplicar` desde a fábrica (192.168.1.99), que é repetível.
- **Internet da casa:** mexer na Huawei pode derrubar o Wi-Fi da família por alguns minutos; fazer num horário
  combinado.
- **Exposição:** com a DMZ da Huawei, a interface de uplink do FortiGate fica de frente para a internet. O script
  deixa nela só `ping`. [Provável] O FortiOS 5.4 está fora do suporte da Fortinet: não ligar VPN SSL nem gerência
  pela WAN.
- **Plano B serial desatualizado:** `config/fortigate-bancada.conf` ainda é do modo 6.x (`internal-switch-mode`,
  `internal1`); não foi mudado aqui e não serve como está para o 5.4.
