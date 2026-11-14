#!/usr/bin/env bash
# Cria a reescrita DNS *.DOMAIN -> IP do servidor via API do AdGuard.
# Uso: ./scripts/dns-rewrite.sh <usuario_adguard> <senha_adguard> [ip]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
user="${1:?usuario}"; pass="${2:?senha}"
ip="${3:-$(hostname -I | awk '{print $1}')}"
curl -fsS -u "$user:$pass" -H 'Content-Type: application/json' \
  -d "{\"domain\":\"*.${DOMAIN}\",\"answer\":\"${ip}\"}" \
  http://127.0.0.1:3000/control/rewrite/add
curl -fsS -u "$user:$pass" -H 'Content-Type: application/json' \
  -d "{\"domain\":\"${DOMAIN}\",\"answer\":\"${ip}\"}" \
  http://127.0.0.1:3000/control/rewrite/add
echo "OK: *.${DOMAIN} -> ${ip}"
