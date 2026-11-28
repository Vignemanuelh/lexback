#!/usr/bin/env bash
# setup-vps.sh — Prépare un VPS Ubuntu/Debian pour LEXBENIN (Docker, UFW, Nginx, Certbot).
#
# Prérequis avant exécution :
#   1. Les DNS lexbenin.emmanuelhoudji.com et apilexbenin.emmanuelhoudji.com pointent vers ce VPS.
#   2. Ce script est lancé avec sudo (ou en root) depuis /opt/lexback ou n'importe où.
#
# Variables optionnelles :
#   DEPLOY_USER=ubuntu ADMIN_IP=1.2.3.4 CERTBOT_EMAIL=moi@domaine.com sudo -E bash setup-vps.sh
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-${SUDO_USER:-$USER}}"
DOMAIN_FRONT="${DOMAIN_FRONT:-lexbenin.emmanuelhoudji.com}"
DOMAIN_API="${DOMAIN_API:-apilexbenin.emmanuelhoudji.com}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
ADMIN_IP="${ADMIN_IP:-}"

if [[ "$EUID" -ne 0 ]]; then
  echo "Exécutez ce script avec sudo : sudo -E bash $0" >&2
  exit 1
fi

echo "==> [1/5] Installation Docker, Nginx, Certbot et Git..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git nginx certbot python3-certbot-nginx docker.io docker-compose-plugin ufw
systemctl enable --now docker

if id "$DEPLOY_USER" >/dev/null 2>&1; then
  usermod -aG docker "$DEPLOY_USER"
fi

echo "==> [2/5] Configuration du pare-feu UFW (22, 80, 443)..."
ufw allow 22/tcp >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable

echo "==> [3/5] Préparation des répertoires /opt/lexback et /opt/lexfront..."
mkdir -p /opt/lexback /opt/lexfront /var/www/certbot
chown -R "$DEPLOY_USER:$DEPLOY_USER" /opt/lexback /opt/lexfront

# Initialisation .images.env si les dépôts sont déjà clonés
[[ -f /opt/lexback/deploy/images.env.example && ! -f /opt/lexback/.images.env ]] && \
  cp /opt/lexback/deploy/images.env.example /opt/lexback/.images.env && \
  chown "$DEPLOY_USER:$DEPLOY_USER" /opt/lexback/.images.env

[[ -f /opt/lexfront/deploy/images.env.example && ! -f /opt/lexfront/.images.env ]] && \
  cp /opt/lexfront/deploy/images.env.example /opt/lexfront/.images.env && \
  chown "$DEPLOY_USER:$DEPLOY_USER" /opt/lexfront/.images.env

echo "==> [4/5] Certificats SSL (Let's Encrypt)..."
systemctl stop nginx || true
email_flag="--register-unsafely-without-email"
[[ -n "$CERTBOT_EMAIL" ]] && email_flag="--email $CERTBOT_EMAIL"

for domain in "$DOMAIN_FRONT" "$DOMAIN_API"; do
  if [[ ! -d "/etc/letsencrypt/live/$domain" ]]; then
    certbot certonly --standalone --non-interactive --agree-tos $email_flag -d "$domain"
  else
    echo "Certificat déjà présent pour $domain"
  fi
done

echo "==> [5/5] Activation des configurations Nginx..."
if [[ -f /opt/lexback/deploy/nginx/lexbenin-api.conf ]]; then
  cp /opt/lexback/deploy/nginx/lexbenin-api.conf /etc/nginx/sites-available/lexbenin-api.conf
  if [[ -n "$ADMIN_IP" ]]; then
    sed -i "s|# allow 203.0.113.10;|allow ${ADMIN_IP};|; s|# deny  all;|deny  all;|" \
      /etc/nginx/sites-available/lexbenin-api.conf
  fi
  ln -sf /etc/nginx/sites-available/lexbenin-api.conf /etc/nginx/sites-enabled/lexbenin-api.conf
fi

if [[ -f /opt/lexfront/deploy/nginx/lexbenin-front.conf ]]; then
  cp /opt/lexfront/deploy/nginx/lexbenin-front.conf /etc/nginx/sites-available/lexbenin-front.conf
  ln -sf /etc/nginx/sites-available/lexbenin-front.conf /etc/nginx/sites-enabled/lexbenin-front.conf
fi

rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx

echo ""
echo "✅ VPS prêt !"
echo "   Prochaines étapes :"
echo "   1. Déconnectez/reconnectez SSH pour activer le groupe docker sur '$DEPLOY_USER'"
echo "   2. Initialisez Vault : cd /opt/lexback && docker compose -f docker-compose.prod.yml up -d vault redis"
echo "   3. Lancez ./deploy/vault/scripts/vaultctl.sh init | unseal | bootstrap | put-secrets"
