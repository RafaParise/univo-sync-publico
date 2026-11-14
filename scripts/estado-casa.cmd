@echo off
rem Infraestrutura da casa: painel ao vivo (atualiza a cada 3 s) do FortiGate, da internet, do A12 e do Tailscale.
rem So le. Fechar a janela (ou Ctrl+C) encerra.
title Infraestrutura da casa
mode con cols=130 lines=50
cd /d "%~dp0.."
python scripts\estado_casa.py
