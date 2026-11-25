#!/usr/bin/env bash
# vaultctl.sh — exploitation de Vault auto-hébergé pour LEXBENIN (à lancer depuis la racine du projet).
#
# Sous-commandes :
#   init                 Initialise Vault (5 parts, seuil 3). AFFICHE les clés une seule fois : à stocker HORS du VPS.
#   unseal               Déverrouille Vault (saisie masquée de 3 clés).
#   bootstrap            Active audit + KV v2, crée politique + AppRole, dépose role_id/secret_id pour l'agent.
#   put-secrets FICHIER  Charge/Met à jour les secrets prod depuis un fichier KEY=VALUE (complète les secrets manquants).
#   rotate-secret-id     Génère un nouveau secret_id AppRole et redémarre l'agent.
#   backup [DEST]        Snapshot Raft (nécessite VAULT_TOKEN) à copier hors du VPS (chiffré).
#
# Le token root n'est jamais écrit sur disque : exporter VAULT_TOKEN pour la session (puis le révoquer).
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
DC=(docker compose -f "$COMPOSE_FILE")
SECRET_PATH="secret/lexbenin/prod/backend"
APPROLE_VOLUME="${APPROLE_VOLUME:-lexbenin_vault_approle}"
POLICY_FILE="deploy/vault/policies/lexbenin-backend.hcl"

vault_cmd() {
  # -T : pas de TTY (permet les pipes) ; le token est transmis uniquement si défini.
  local env_args=(-e VAULT_ADDR=http://127.0.0.1:8200)
  [[ -n "${VAULT_TOKEN:-}" ]] && env_args+=(-e VAULT_TOKEN)
  "${DC[@]}" exec -T "${env_args[@]}" vault vault "$@"
}

require_token() {
  [[ -n "${VAULT_TOKEN:-}" ]] || { echo "VAULT_TOKEN requis (export VAULT_TOKEN=...)" >&2; exit 1; }
}

write_to_approle_volume() {
  # $1 = nom de fichier, contenu sur stdin. uid/gid 100:1000 = utilisateur "vault" de l'image HashiCorp.
  docker run --rm -i -v "${APPROLE_VOLUME}:/approle" alpine:3.20 sh -c \
    "cat > /approle/$1 && chown 100:1000 /approle/$1 && chmod 400 /approle/$1"
}

cmd_init() {
  echo ">> Initialisation (les clés ci-dessous ne seront PLUS jamais affichées)"
  vault_cmd operator init -key-shares=5 -key-threshold=3
  echo ">> Stockez les 5 clés d'unseal et le root token dans des lieux séparés, hors du VPS."
}

cmd_unseal() {
  for i in 1 2 3; do
    read -r -s -p "Clé d'unseal $i/3 : " key; echo
    printf '%s' "$key" | "${DC[@]}" exec -T -e VAULT_ADDR=http://127.0.0.1:8200 vault sh -c 'read -r k; vault operator unseal "$k"' >/dev/null
  done
  vault_cmd status
}

cmd_bootstrap() {
  require_token
  vault_cmd audit enable file file_path=/vault/logs/audit.log || echo "(audit déjà activé)"
  vault_cmd secrets enable -path=secret -version=2 kv || echo "(KV v2 déjà activé)"
  vault_cmd policy write lexbenin-backend - < "$POLICY_FILE"
  vault_cmd auth enable approle || echo "(approle déjà activé)"
  vault_cmd write auth/approle/role/lexbenin-backend \
    token_policies=lexbenin-backend token_ttl=1h token_max_ttl=4h secret_id_ttl=0 token_num_uses=0
  vault_cmd read -field=role_id auth/approle/role/lexbenin-backend/role-id | tr -d '\r\n' | write_to_approle_volume role_id
  vault_cmd write -f -field=secret_id auth/approle/role/lexbenin-backend/secret-id | tr -d '\r\n' | write_to_approle_volume secret_id
  echo ">> AppRole prêt. Étape suivante : ./deploy/vault/scripts/vaultctl.sh put-secrets <fichier>"
}

cmd_put_secrets() {
  require_token
  local file="${1:?fichier KEY=VALUE requis}"
  # Fusionne le fichier fourni avec des secrets générés s'ils sont absents, puis envoie en JSON via stdin.
  python3 - "$file" <<'PY' | vault_cmd kv put "$SECRET_PATH" -
import json, secrets, string, sys
data = {}
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.rstrip("\n")
    if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    data[k.strip()] = v.strip().strip("'\"")
alphabet = string.ascii_letters + string.digits
generated = {
    "SECRET_KEY": secrets.token_hex(32),
    "ADMIN_API_KEY": secrets.token_hex(24),
    "PARTNER_API_KEY": secrets.token_hex(24),
    "ADMIN_PASSWORD": "".join(secrets.choice(alphabet) for _ in range(24)),
    "ADMIN_USERNAME": "admin",
}
for k, v in generated.items():
    if not data.get(k):
        data[k] = v
        print(f"[généré] {k}", file=sys.stderr)
        if k in ("ADMIN_PASSWORD", "PARTNER_API_KEY", "ADMIN_API_KEY"):
            print(f"         {k}={v}  (à noter maintenant, non réaffiché)", file=sys.stderr)
print(json.dumps(data))
PY
  echo ">> Secrets écrits dans $SECRET_PATH. Supprimez maintenant le fichier source : shred -u '$file'"
  "${DC[@]}" restart vault-agent >/dev/null 2>&1 || true
}

cmd_rotate_secret_id() {
  require_token
  vault_cmd write -f -field=secret_id auth/approle/role/lexbenin-backend/secret-id | tr -d '\r\n' | write_to_approle_volume secret_id
  "${DC[@]}" restart vault-agent
}

cmd_backup() {
  require_token
  local dest="${1:-vault-$(date +%Y%m%d-%H%M%S).snap}"
  vault_cmd operator raft snapshot save /vault/file/backup.snap
  "${DC[@]}" cp vault:/vault/file/backup.snap "$dest"
  "${DC[@]}" exec -T vault rm -f /vault/file/backup.snap
  echo ">> Snapshot : $dest — chiffrez-le (ex. gpg -c) puis copiez-le hors du VPS."
}

case "${1:-}" in
  init) cmd_init ;;
  unseal) cmd_unseal ;;
  bootstrap) cmd_bootstrap ;;
  put-secrets) shift; cmd_put_secrets "$@" ;;
  rotate-secret-id) cmd_rotate_secret_id ;;
  backup) shift; cmd_backup "$@" ;;
  *) sed -n '2,13p' "$0"; exit 1 ;;
esac
