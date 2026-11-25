# Déploiement Backend (VPS + Nginx + Supabase + Vault)

## 1. Sur le VPS
```bash
git clone git@github.com:Vignemanuelh/lexback.git /opt/lexback
cd /opt/lexback
cp deploy/images.env.example .images.env
```

## 2. Nginx + Certbot
```bash
sudo cp deploy/nginx/lexbenin-api.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/lexbenin-api.conf /etc/nginx/sites-enabled/
sudo mkdir -p /var/www/certbot
sudo certbot certonly --webroot -w /var/www/certbot -d apilexbenin.emmanuelhoudji.com
sudo nginx -t && sudo systemctl reload nginx
```
*(Penser à renseigner votre IP dans le bloc `/admin` de `lexbenin-api.conf`.)*

## 3. Vault (une seule fois)
```bash
docker compose -f docker-compose.prod.yml up -d vault redis
./deploy/vault/scripts/vaultctl.sh init       # noter les 5 clés + root token HORS du VPS
./deploy/vault/scripts/vaultctl.sh unseal
export VAULT_TOKEN=<root token>
./deploy/vault/scripts/vaultctl.sh bootstrap
./deploy/vault/scripts/vaultctl.sh put-secrets /chemin/secrets.tmp && shred -u /chemin/secrets.tmp
docker compose -f docker-compose.prod.yml up -d
unset VAULT_TOKEN
```

## 4. Déploiement CI/CD
Un tag `vX.Y.Z` poussé sur `main` déclenche `release.yml` → build GHCR → SSH vers `/opt/lexback/deploy/scripts/deploy.sh <tag>` (qui fait `git pull`, tire l'image et redémarre `lexback` + `worker` avec rollback automatique).
