#!/usr/bin/env bash
# Prepara o servidor (Debian/Ubuntu/Raspberry Pi OS) e sobe tudo.
# Uso: sudo ./scripts/bootstrap.sh
set -euo pipefail
cd "$(dirname "$0")/.."

[[ $EUID -eq 0 ]] || { echo "Rode com sudo."; exit 1; }

# 1) Docker
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi

# 2) Encaminhamento de IP (necessário para subnet router / exit node do Tailscale)
cat > /etc/sysctl.d/99-parise.conf <<'EOF'
net.ipv4.ip_forward=1
net.ipv6.conf.all.forwarding=1
EOF
sysctl --system >/dev/null

# 3) Libera a porta 53 (systemd-resolved ocupa em Ubuntu/Debian) para o AdGuard
if systemctl is-active --quiet systemd-resolved; then
  mkdir -p /etc/systemd/resolved.conf.d
  printf '[Resolve]\nDNSStubListener=no\n' > /etc/systemd/resolved.conf.d/parise.conf
  ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf
  systemctl restart systemd-resolved
fi

# 4) .env
if [[ ! -f .env ]]; then
  cp .env.example .env
  sed -i "s|^PARISE_TOKEN=.*|PARISE_TOKEN=$(openssl rand -hex 24)|" .env
  echo ">> Edite .env: preencha TS_AUTHKEY e confira LAN_CIDR. Depois rode este script de novo."
  exit 0
fi
grep -q '^TS_AUTHKEY=.\+' .env || { echo "TS_AUTHKEY vazio em .env"; exit 1; }

mkdir -p data/{tailscale,caddy,adguard/work,adguard/conf,parise-core,arena,files,filebrowser,kuma}
chmod +x scripts/*

# 5) Sobe
./scripts/pc up -d --build
ip=$(hostname -I | awk '{print $1}')
cat <<EOF

Pronto. IP do servidor: $ip
Próximos passos (uma vez só):
 1. AdGuard: http://$ip:3000 -> assistente, painel na porta 3000, DNS na 53.
 2. AdGuard > Filtros > Reescritas DNS: *.\$DOMAIN -> $ip   (ou ./scripts/dns-rewrite.sh)
 3. Roteador: DHCP/DNS primário = $ip  (ou configure só nos aparelhos).
 4. Tailscale admin: aprove "exit node" e a rota da LAN em parise-hub;
    em DNS, adicione $ip como nameserver global para o celular resolver *.\$DOMAIN fora de casa.
 5. Portal: http://$ip  | API: http://parise-core.\$DOMAIN
EOF
