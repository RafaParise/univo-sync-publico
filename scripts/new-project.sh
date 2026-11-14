#!/usr/bin/env bash
# Cria um projeto novo plugado na infra: container + subdomínio + registro no parise-core.
# Uso: ./scripts/new-project.sh <nome> <imagem|build> <porta_interna>
#  ex.: ./scripts/new-project.sh blog nginx:alpine 80
set -euo pipefail
cd "$(dirname "$0")/.."
name="${1:?nome}"; image="${2:?imagem}"; port="${3:?porta}"
[[ "$name" =~ ^[a-z0-9-]+$ ]] || { echo "nome: só a-z, 0-9, -"; exit 1; }
d="projects/$name"
[[ -e "$d" ]] && { echo "já existe: $d"; exit 1; }
mkdir -p "$d"; cp projects/_template/compose.yml.tpl "$d/compose.yml"; cp projects/_template/site.caddy.tpl "$d/site.caddy"
sed -i "s/__NAME__/$name/g; s|__IMAGE__|$image|g; s/__PORT__/$port/g" "$d/compose.yml" "$d/site.caddy"
mkdir -p "data/$name"
echo "Criado $d. Ajuste $d/compose.yml se precisar, depois:"
echo "  ./scripts/pc up -d && docker exec caddy caddy reload --config /etc/caddy/Caddyfile"
echo "  Acesso: http://$name.\${DOMAIN}"
