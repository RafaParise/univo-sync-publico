# FortiGate 60D da bancada

Dados tirados das fotos da etiqueta e do painel (09/11/2026).
Número de série e MAC ficam só no arquivo local `equipamento.local.md`, que o `.gitignore` não deixa ir para o GitHub.

| Item | Valor |
|---|---|
| Modelo | FG-60D (FORTIGATE-60D) |
| HWD (revisão) | C1AB28-03AA-0000 |
| PN | P14482-03-01 |
| Etiqueta extra | EX2952-01 |
| Fabricação | 2013-11-05 |
| Alimentação | 12 Vdc, 2,5 A |

## Portas

**Frente:** LEDs PWR / STATUS / HA, LEDs de link e velocidade das portas, e a porta **CONSOLE RJ-45**.

**Traseira (da esquerda para a direita):** RESET (furinho), DC+12V, **USB MGMT** (mini-USB), **USB** (tipo A), WAN2, WAN1, DMZ, 7, 6, 5, 4, 3, 2, 1.

## Qual porta serve para quê

| Porta | Serve para | Serve como serial COM para o pyserial? |
|---|---|---|
| CONSOLE RJ-45 (frente) | Console da linha de comando, 9600 8-N-1 | **Sim**, com um cabo console USB↔RJ-45 (chip FTDI, CH340 ou CP210x) |
| USB MGMT (mini-USB, trás) | Gerência pelo programa FortiExplorer | Não é garantido; a Fortinet mostra esse uso só pelo FortiExplorer |
| USB tipo A (trás) | O FortiGate é o "host" (pendrive, modem 3G/4G) | **Não.** Ligar o PC aqui é ligar dois hosts; não funciona |

[Provável] O "Dispositivo USB Desconhecido (erro 43)" que o Windows mostrou em 09/11 era o cabo USB-C do PC ligado na porta USB tipo A do FortiGate.

## Fontes
- Fortinet, "Technical Tip: Using the USB MGMT Console port" (o 60D aparece como "Success" com o FortiExplorer; a redefinição de senha do admin não funcionou por essa porta nos testes): https://community.fortinet.com/t5/FortiGate/Technical-Tip-Using-the-USB-MGMT-Console-port/ta-p/190230
- Fórum Fortinet, "Fortigate 60D: No console port, how to connect" (os primeiros 60D não tinham RJ-45; o cabo USB-A↔USB-A não funcionou): https://community.fortinet.com/t5/Support-Forum/Fortigate-60D-No-console-port-How-to-connect/m-p/88031
- Fortinet, "Connecting to the CLI" (FortiOS 6.0): https://docs.fortinet.com/document/fortigate/6.0.0/handbook/144460
