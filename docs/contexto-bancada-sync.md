# CONTEXTO MESTRE DO PROJETO: BANCADA-SYNC (Edux-Core)
**Usuário:** Rafael Parise Passos (Professor Técnico SEDUC-SP / Engenheiro de Infraestrutura)
**Objetivo do Projeto:** Criar um laboratório autônomo de borda (Edge Computing) e uma central de automação (ChatOps) voltada para o ensino técnico e gestão de burocracias escolares.

## 1. TOPOLOGIA FÍSICA (HARDWARE)
A infraestrutura roda fisicamente na minha bancada, mas é projetada para ser acessada 100% remotamente (via Tailscale/parise-core) sem depender do PC principal ligado 24/7.
- **Núcleo de Rede (Firewall):** FortiGate 60D.
- **Nó de Borda Autônomo (Edge Server):** Smartphone Samsung Galaxy A12 rodando `Termux` (Linux/Android). Conectado à porta DMZ via Hub Ugreen 6-em-1 (com porta RJ45 Gigabit, HDMI e entrada de energia Power Delivery 100W para rodar 24/7 sem gastar bateria).
- **Nó de Processamento Pesado:** PC Desktop (Ryzen 5600G, ASUS B550M). Fica na porta LAN1. Usado para emulação pesada (Projeto ARENA), OBS Studio (x264) e injeção do script inicial via cabo Serial (USB-C para Mini-USB).
- **Distribuição (Netplay):** Switch TP-Link TL-SG105 (Gigabit, QoS 802.1p nativo) conectado na porta LAN2 para plugar os celulares dos alunos via cabo em campeonatos locais.

## 2. TOPOLOGIA LÓGICA (REDE E ZERO-TRUST NO FORTIGATE)
O FortiGate gerencia o roteamento e a segurança com isolamento estrito:
- **WAN1 (DHCP):** Recebe internet do roteador da operadora (ONT Huawei EG8145X6-10, 192.168.18.1); desde 12/11/2026 o FortiGate pega 192.168.18.40. A porta 3 como uplink ficou só como opção B: ver `docs/TOPOLOGIA-2026-11-12.md`.
- **internal1 (LAN1 - 10.0.20.0/24):** Rede do PC Ryzen. Tem acesso à internet e gerencia os outros nós.
- **dmz (10.0.10.0/24):** Rede do Galaxy A12. O firewall bloqueia telemetria da Samsung (`*.samsung.net`) e restringe acessos. Porta ADB (5555) isolada com regra Zero-Trust.
- **internal2 (LAN2 - 10.0.30.0/24):** Rede do Switch ARENA. Possui regras de Traffic Shaper (QoS) e DSCP para priorizar latência dos controles WebSocket.

## 3. MÓDULOS DE SOFTWARE E ARQUITETURA
O projeto se divide em três pilares principais de software. Atue sempre respeitando esta divisão de responsabilidades:

**A) Provisionamento Out-of-Band (PC ➔ FortiGate):**
Script Python executado 1 única vez no PC usando a biblioteca `pyserial`. Ele injeta as configurações via porta COM (USB-C/Mini-USB) ignorando quedas de rede. 

**B) Sentinela Termux (A12 ➔ FortiGate):**
Script Python rodando em background no Galaxy A12 (`sentinela_a12.py`). Monitora a temperatura do processador ARM (Kill-Switch) e vigia conexões ADB na porta 5555. Se detectar intrusos ou superaquecimento, ele aciona a API REST do FortiGate (`10.0.10.1/api/v2/cmdb/`) e bloqueia a porta no nível do hardware.

**C) ChatOps e Automação SEDUC-SP (A12 ➔ parise-core ➔ Web):**
O Galaxy A12 roda um Bot interativo conectado a um servidor de chat federado com criptografia de ponta a ponta (o protocolo Matrix; nada a ver com o nome antigo da IA). 
- O bot escuta comandos na minha sala de chat privada (ex: `!status_lab`, `!arena_restart`).
- O bot atua como um "Farol", rodando rotinas automatizadas (via APIs ou Playwright futuro no backend) para checar pendências nos diários digitais da SED e prazos do AVA-EFAPE, me enviando alertas proativos no celular de onde eu estiver.

## 4. DIRETRIZES DE ENGENHARIA PARA O CLAUDE
- **Destruidor da Curva de Aprendizado:** Vá direto ao ponto. Elimine introduções longas. Entregue soluções modulares baseadas na regra de Pareto (80/20).
- **Sem Jargões Abstratos:** Ao gerar relatórios ou logs, aja como um engenheiro sênior. Foco em diagnóstico por eliminação e eficiência de hardware.
- **Código:** Utilize Python ou Node.js (TypeScript) prioritariamente. Mantenha os scripts limpos, comentados com o objetivo da função, e focados em alta estabilidade (tratamento de erros de rede e queda de APIs).