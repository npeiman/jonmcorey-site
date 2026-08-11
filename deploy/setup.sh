#!/usr/bin/env bash
#
# One-time (idempotent) server setup for the Professional Advisory Group site
# on Ubuntu 24.04. Run with sudo AFTER the app files are in place under
# /opt/pag/website (and optionally /opt/pag-dev/website for a dev instance).
#
#   sudo bash /opt/pag/website/deploy/setup.sh            # production only
#   sudo bash /opt/pag/website/deploy/setup.sh --with-dev # production + dev
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WITH_DEV=0
[[ "${1:-}" == "--with-dev" ]] && WITH_DEV=1

if [[ $EUID -ne 0 ]]; then
  echo "Please run with sudo: sudo bash $0" >&2
  exit 1
fi

echo "==> Ensuring python3 and nginx are installed"
apt-get update -y
apt-get install -y python3 nginx

echo "==> Creating service user 'pag'"
if ! id -u pag >/dev/null 2>&1; then
  useradd --system --home /opt/pag --shell /usr/sbin/nologin pag
fi

echo "==> Creating directories"
mkdir -p /opt/pag/website /opt/pag/data
chown -R pag:pag /opt/pag
# The website code should already be uploaded to /opt/pag/website
if [[ ! -f /opt/pag/website/server.py ]]; then
  echo "!! /opt/pag/website/server.py not found. Upload the app first (see DEPLOY.md)." >&2
  exit 1
fi

echo "==> Installing systemd service (production)"
cp "$SCRIPT_DIR/pag.service" /etc/systemd/system/pag.service

if [[ $WITH_DEV -eq 1 ]]; then
  echo "==> Setting up development instance"
  mkdir -p /opt/pag-dev/website /opt/pag-dev/data
  chown -R pag:pag /opt/pag-dev
  cp "$SCRIPT_DIR/pag-dev.service" /etc/systemd/system/pag-dev.service
fi

echo "==> Reloading systemd and starting services"
systemctl daemon-reload
systemctl enable --now pag
[[ $WITH_DEV -eq 1 ]] && systemctl enable --now pag-dev || true

echo "==> Installing nginx site (edit server_name afterward!)"
if [[ ! -f /etc/nginx/sites-available/pag ]]; then
  cp "$SCRIPT_DIR/nginx-pag.conf" /etc/nginx/sites-available/pag
fi
ln -sf /etc/nginx/sites-available/pag /etc/nginx/sites-enabled/pag
# Disable the default site if present
rm -f /etc/nginx/sites-enabled/default

echo "==> Testing and reloading nginx"
nginx -t
systemctl reload nginx

echo "==> Opening the firewall for web + SSH (if ufw is active)"
if command -v ufw >/dev/null 2>&1; then
  ufw allow OpenSSH || true
  ufw allow 'Nginx Full' || true
fi

echo ""
echo "============================================================"
echo " Setup complete."
echo "   Production app:  systemctl status pag"
[[ $WITH_DEV -eq 1 ]] && echo "   Dev app:         systemctl status pag-dev"
echo ""
echo " NEXT:"
echo "   1. Edit /etc/nginx/sites-available/pag and set server_name"
echo "      to your domain, then: sudo nginx -t && sudo systemctl reload nginx"
echo "   2. Point your domain's DNS A record at this server's IP."
echo "   3. Enable HTTPS:  sudo apt-get install -y certbot python3-certbot-nginx"
echo "                     sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com"
echo "   4. In the app's Admin > Settings, set Site Base URL to https://yourdomain.com"
echo "   5. Change the default admin password!"
echo "============================================================"
