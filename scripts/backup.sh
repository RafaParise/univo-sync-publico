#!/usr/bin/env bash
# Backup de data/ (exceto ROMs pesadas) e configs. Mantém os 7 últimos.
# Agende: crontab -e  ->  0 3 * * * /caminho/parise-infra/scripts/backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
dest="${BACKUP_DIR:-$HOME/parise-backups}"
mkdir -p "$dest"
f="$dest/parise-$(date +%F).tar.gz"
tar --exclude='data/arena' --exclude='data/tailscale' -czf "$f" data .env docker-compose.yml caddy portal projects scripts services
ls -1t "$dest"/parise-*.tar.gz | tail -n +8 | xargs -r rm --
echo "Backup: $f"
