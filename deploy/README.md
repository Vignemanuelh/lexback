# Déploiement Backend (VPS + Nginx + Supabase + Vault)

## 1. Préparer et cloner sur le VPS
```bash
sudo mkdir -p /opt/lexback /opt/lexfront && sudo chown -R $USER:$USER /opt/lexback /opt/lexfront
git clone git@github.com:Vignemanuelh/lexback.git /opt/lexback
git clone git@github.com:Vignemanuelh/lexfront.git /opt/lexfront
```

## 2. Script tout-en-un (Docker, UFW, Certbot SSL, Nginx)
```bash
cd /opt/lexback
CERTBOT_EMAIL=ton@email.com ADMIN_IP=<ton_ip_fixe_optionnel> sudo -E bash deploy/scripts/setup-vps.sh
newgrp docker
```

## 3. Vault (une seule fois)
```bash
cd /opt/lexback
docker compose -f docker-compose.prod.yml up -d vault redis
./deploy/vault/scripts/vaultctl.sh init       # noter les 5 clés + root token HORS du VPS
./deploy/vault/scripts/vaultctl.sh unseal
export VAULT_TOKEN=<root token>
./deploy/vault/scripts/vaultctl.sh bootstrap
./deploy/vault/scripts/vaultctl.sh put-secrets /chemin/secrets.tmp && shred -u /chemin/secrets.tmp
docker compose -f docker-compose.prod.yml up -d vault-agent
unset VAULT_TOKEN
```

## 4. Déploiement CI/CD
Un tag `vX.Y.Z` poussé sur `main` déclenche `release.yml` → build GHCR → SSH vers `/opt/lexback/deploy/scripts/deploy.sh <tag>` (qui fait `git pull`, tire l'image et redémarre `lexback` + `worker` avec rollback automatique).
