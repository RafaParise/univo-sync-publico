@echo off
rem Compartilhar a internet de casa (pela VPN do Tailscale) com quem esta no hotspot deste notebook (13/11/2026).
rem 1. escolhe a saida de casa no Tailscale: o PC de casa se estiver ligado, senao o A12 (com acesso a rede local, para
rem    quem esta no hotspot alcancar o proxy);  2. abre o proxy (porta 8888).
rem Ligue antes o Hotspot movel do Windows (Configuracoes > Rede e Internet > Hotspot movel).
rem Uso: compartilhar-internet.cmd            (DNS comum, o padrao)
rem      compartilhar-internet.cmd --familia  (com o DNS familia da Cloudflare, so quando pedir)
cd /d "%~dp0.."
set "TS=C:\Program Files\Tailscale\tailscale.exe"
if not exist "%TS%" (
  echo Falta o Tailscale neste computador: instale em tailscale.com/download e entre com a mesma conta.
  pause & exit /b 1
)
"%TS%" ping --c 1 --timeout 3s rafaparise >nul 2>&1 && (set "SAIDA=rafaparise") || (set "SAIDA=samsung-a12-de-rafa-parise")
echo Saida de casa escolhida: %SAIDA%
"%TS%" set --exit-node=%SAIDA% --exit-node-allow-lan-access=true
if errorlevel 1 (
  echo O Tailscale nao aceitou a saida %SAIDA%. Confira se ela esta aprovada no painel do Tailscale.
  pause & exit /b 1
)
python scripts\proxy_compartilhado.py %*
echo Desligando a saida de casa deste computador...
"%TS%" set --exit-node=
pause
