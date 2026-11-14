# Telemetria sutil da bancada (11/11/2026)

Pedido do Rafael: "um sistema de coleta de telemetrias muito sutil nessa infraestrutura de rede e equipamentos
(FortiGate, hubs ligados ao PC, celular e roteador), para apenas alimentar as IAs (parise-core no Windows e no
Android, e o Claude), para que todas trabalhem juntas e coletem só os dados essenciais para identificar e resolver
problemas e otimizar com amostras".

## O desenho

```
a cada 5 min (tarefa "Telemetria-Bancada", do usuário, sem administrador)
   scripts\telemetria.py coletar
      ├─ rede:      ping ao FortiGate, ao A12 (DMZ), ao roteador da casa, a 1.1.1.1 e 8.8.8.8
      ├─ FortiGate: API de monitoramento (system/resource, system/interface, system/dhcp)
      ├─ PC:        memória livre, tempo ligado, estado dos adaptadores
      └─ A12:       pelo cabo (adb): bateria, temperatura, memória, tempo ligado, endereço;
                    e as amostras locais do sentinela (/sdcard/parise-sync/telemetria/amostras.jsonl)
   → data\telemetria\AAAA-MM-DD.jsonl   (bruto, fora do git)
   → memoria\telemetria\RESUMO.md       (o que as IAs leem: alertas + medidas das últimas 24 h)
```

No A12, o `scripts\sentinela_a12.py` (Termux) escreve uma linha por minuto com a saúde do próprio aparelho:
temperatura, bateria, memória, tempo ligado, sinal do Wi-Fi e ping ao gateway. O arquivo fica em
`/sdcard/parise-sync/telemetria/` (o PC o lê pelo cabo) ou, sem acesso ao `/sdcard`, em `~/telemetria/` (o Qwen do
A12 lê ali). Nunca passa de 2.000 linhas.

**Instalado em 12/11/2026** pelo cabo, com `python scripts\instalar_sentinela_a12.py instalar` (copia o sentinela, a
`fortigate_api.py`, o comando `sentinela` do kit do celular e o script de boot do Termux; `estado` e `desligar`
também). No A12 o comando é `sentinela ligar | desligar | estado | registro | amostras | uma-vez`, e o
`~/.termux/boot/iniciar-a12` o sobe no boot e confere de hora em hora, como faz com o repasse. Enquanto o A12 não
está na DMZ ele roda em **modo só telemetria** (sem `~/.parise-sentinela.env`): mede e guarda, e não fala com o
FortiGate; a senha da API só vai para o celular quando ele puder alcançar o aparelho. O Android 12 nega ao Termux o
`/proc/uptime`, o `/proc/net/route` e o `/proc/net/tcp`: o tempo ligado vem do relógio de boot, o gateway é o
FortiGate da conf ou o `.1` da rede do Wi-Fi, e o vigia de ADB fica desligado (como já estava documentado).

## Quem lê

| IA | Como |
|---|---|
| Claude Code | `memoria\telemetria\RESUMO.md` está no `comecar` do projeto (`projetos.py` do parise-core) |
| Hermes (parise-core-windows) | o mesmo arquivo, pelo índice do `projetos.py` |
| Qwen (parise-core-android) | as amostras locais do sentinela no próprio A12 |

Um alerta no RESUMO é uma hipótese com número. A IA propõe causa e conserto; o que mexe no FortiGate só o Claude
Code aplica (regra do projeto).

## Limites (o que fica fora, de propósito)

A LAN2 tem celulares de alunos menores de idade. Por isso:

- **nada de MAC, nome, endereço ou tráfego** de aparelho que não seja do Rafael: do DHCP guarda-se só a
  **contagem** de endereços por rede (a lista do FortiGate traz MAC e nome, e é descartada na hora);
- as regras do repasse continuam com `logtraffic disable`;
- o `.env` é lido só para entrar na API; senha, chave e número de série nunca entram na amostra;
- **nada sai deste computador**: não há envio para serviço nenhum. O `data\` está no `.gitignore`.

## Comandos

```
python scripts\telemetria.py coletar           colhe e reescreve o RESUMO.md
python scripts\telemetria.py resumo            só reescreve o resumo
python scripts\telemetria.py mostrar           a última amostra de cada fonte
python scripts\telemetria.py instalar-tarefa   registra a tarefa de 5 em 5 minutos
python scripts\telemetria.py remover-tarefa
```

Limiares dos alertas (`LIMITES` no script): LAN acima de 50 ms, internet acima de 150 ms, perda de 20% ou mais,
FortiGate acima de 80% de CPU ou 85% de memória, PC com menos de 1.024 MB livres (o restore do FortiGate já foi
cortado por falta de memória em 10/11), A12 acima de 45 °C ou abaixo de 15% de bateria.

## O que a API do FortiOS 5.4 responde (conferido em 11/11/2026)

`system/resource` (CPU e memória), `system/interface` (enlace, velocidade, bytes e erros; o switch `internal` não
aparece), `system/dhcp` (por interface), `system/available-interfaces`, `system/firmware`, `system/time`.
Não existem no 5.4: `system/resource/usage`, `system/status`, `system/performance/status`, `system/sensor-info`.
