# O que mudou do plano mestre para o modelo final

O plano original (`plano-mestre-provisionamento.md`) virou `config/fortigate-bancada.conf`, aplicado por `scripts/provisionar_fortigate.py`. Cada mudança abaixo tem o motivo.

## Como o script aplica
| Antes | Agora | Por quê |
|---|---|---|
| Mandava as linhas sem ler a resposta | Lê a resposta de cada linha e **para** quando o FortiOS recusa | Antes, um erro no meio deixava o aparelho meio configurado sem aviso |
| Senha em branco para sempre | Troca a senha do admin (`ADMIN_SENHA` do `.env`) | Firewall com admin sem senha e WAN ligada é porta aberta |
| Tudo obrigatório | Seções marcadas como `opcional` e `min=versão` | Algumas funções dependem da versão do FortiOS do 60D, que ainda não sabemos |
| Sem log | Log em `logs/`, com senha e chave mascaradas | Para diagnosticar depois |
| Sem teste | `tests/` com FortiGate simulado (12 testes) | Para validar o fluxo antes de ter o cabo |

## Configuração
| Item do plano | Decisão | Por quê |
|---|---|---|
| Objetos por MAC nas regras (`set type mac`) | Objetos por **IP** (10.0.20.100 e 10.0.10.50), com o IP preso ao MAC no DHCP | [Palpite] Objeto de endereço por MAC é recurso de FortiOS mais novo que o do 60D. Por IP funciona em qualquer versão |
| `set api-key "..."` com perfil `super_admin` | O aparelho **gera** a chave (`execute api-user generate-key`) e o script grava no `.env`. Perfil `parise_core_api` só com firewall, aceito só do IP do A12 | [Provável] A chave não pode ser escolhida pelo CLI. E um robô no celular não deve ter poder total |
| `allowaccess http` e `snmp` | Só `https`, `ssh` e `ping` na LAN1; `https` e `ping` na DMZ | HTTP manda a senha sem criptografia |
| Saída para `wan1` e `wan2` na mesma regra | Só `wan1` | A topologia usa uma internet só, e regra com várias interfaces depende da versão |
| `router policy` mandando o PC pela WAN2 | Removido | Com a WAN2 desligada, o PC ficaria sem internet |
| Rotas estáticas por interface DHCP | Removidas | O DHCP da WAN já instala a rota padrão |
| Perfil SSL "AUDITORIA_IA_SNI" e `utm-status` | Removidos | Exigem perfis de segurança e licenças que o 60D usado provavelmente não tem |
| Bloqueio de `*.samsung.net` por regra de firewall | Filtro de DNS local no DNS do FortiGate para a DMZ (opcional) | [Palpite] Endereço com curinga é recurso mais novo. Limite: se o A12 usar "DNS privado" (DoT), ele passa por fora |
| Domínio `.local` | `bancada.lan` (fortigate, arena, parise-core) | `.local` é do mDNS e conflita no Android e no Windows |
| `arena` apontando para o A12 | `arena.bancada.lan` aponta para o PC (10.0.20.100) | A regra dos controles leva o tráfego ao PC, que roda a ARENA |
| Faixa de DHCP da LAN2 de .100 a .150 com reserva no .10 | Faixa de .10 a .150 | A reserva fica dentro da faixa |
| `netflow` | Só no FortiOS 6.2 ou mais novo (opcional) | [Palpite] Não sei se o 6.0 tem esse comando |

## Rascunhos colados em 09/11 (provisionamento por SSH/serial, sentinelas, DNS)
**Aproveitado:** descrições das interfaces; WAN2 como reserva da WAN1 (distância 10/20, que é o que as rotas estáticas queriam); reservas dos controles 1 e 2 da ARENA (10.0.30.10 e .11); sentinela térmico + vigia de ADB, reescritos em `scripts/sentinela_a12.py`.

**Descartado, e por quê:**
| Item | Motivo |
|---|---|
| `internal-switch-mode`, `internal1` | No 5.4 do 60D as portas formam o switch de hardware "internal"; `internal1` não existe como interface |
| Objetos por MAC, FQDN com curinga, perfil SSL + `utm-status` | Não existem no 5.4 ou exigem licença |
| `api-user` com chave fixa `super_admin` | O 5.4 não tem api-user; chave fixa no código com poder total seria uma porta dos fundos |
| `router policy` mandando o PC para a WAN2 | A WAN2 está sem cabo: o PC ficaria sem internet |
| `allowaccess http snmp`, `verify=False`, `except: pass` | Senha sem criptografia, certificado sem conferência, falhas escondidas |
| Envio linha a linha sem ler resposta | Erro no meio deixa o aparelho meio configurado sem aviso |
| DNS `arena.local` / `parise-core.local` | `.local` é do mDNS; ficou `bancada.lan` |
| Bloqueio de intruso criando objeto de endereço | Nenhuma regra usa o objeto, então nada é bloqueado. E a regra 2 já só deixa o PC chegar ao ADB pelo FortiGate: um intruso detectado veio por fora dele (Wi-Fi do celular), onde o firewall não alcança |

**Como o sentinela ficou:** desliga a regra 2 (status `disable`) por temperatura acima de 45 °C e religa abaixo de 42 °C. Com acesso não autorizado ao ADB, desliga a regra, avisa no celular (Termux:API) e só religa com `--liberar`. [Provável] No Android 12 sem root, o Termux não lê `/proc/net/tcp`; nesse caso o vigia de ADB fica desligado e avisa, e só o térmico funciona.

## Fica para a parte B (sentinela do A12)
- O `block_intruder` do plano cria o endereço, mas nenhuma regra usa esse endereço, então nada é bloqueado. Falta um grupo de bloqueio e uma regra de negação.
- A chave vai na URL (`access_token=`) e a verificação de certificado está desligada. O certo é exportar o certificado do FortiGate e conferir contra ele.
- `except: pass` esconde falhas da API.
