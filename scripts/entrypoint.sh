#!/usr/bin/env bash
set -e

echo "🚀 [LEXBENIN] Initialisation du conteneur Backend..."

# Attente de la base de données PostgreSQL
python -c "
import socket, time, os, sys
host = os.environ.get('POSTGRES_HOST', 'localhost')
port = int(os.environ.get('POSTGRES_PORT', '5432'))
print(f'⏳ Attente de PostgreSQL sur {host}:{port}...')
connected = False
for i in range(30):
    try:
        with socket.create_connection((host, port), timeout=2):
            print('✅ PostgreSQL est accessible et prêt !')
            connected = True
            break
    except OSError:
        time.sleep(1)
if not connected:
    print('⚠️ PostgreSQL non joignable immédiatement, tentative de démarrage...')
"

# Synchronisation des extensions et des tables
python -c "
import asyncio
from src.core.database import init_db
try:
    asyncio.run(init_db())
    print('✅ Extensions pgvector et tables synchronisées.')
except Exception as e:
    print(f'⚠️ Initialisation DB reportée : {e}')
"

# Ingestion automatique au premier démarrage si le fichier existe et que le flag est activé
if [ "$AUTO_INGEST_ON_STARTUP" = "true" ] && [ -f "data/processed/code_du_numerique_complet.json" ]; then
    echo "📚 Ingestion automatique du Code du numérique béninois (646 articles)..."
    python scripts/run_ingestion.py --json data/processed/code_du_numerique_complet.json --batch-size 50 || true
fi

echo "✨ Lancement de la commande applicative : $@"
exec "$@"
