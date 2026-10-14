#!/usr/bin/env python3
"""Script de diagnostic et de vérification de la connexion à Supabase / PostgreSQL.

Usage:
    python scripts/test_supabase_connection.py
"""

import asyncio
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import text
from src.core.config import get_settings
from src.core.database import AsyncSessionLocal, init_db


async def check_database():
    settings = get_settings()
    db_url = settings.DATABASE_URL

    # Masque le mot de passe pour l'affichage sécurisé
    safe_url = db_url
    if "@" in safe_url and ":" in safe_url.split("@")[0]:
        prefix, rest = safe_url.split("@", 1)
        scheme_user = prefix.rsplit(":", 1)[0]
        safe_url = f"{scheme_user}:******@{rest}"

    print("==================================================================")
    print("🔍 DIAGNOSTIC DE CONNEXION SUPABASE / POSTGRESQL (LEXBENIN)")
    print("==================================================================")
    print(f"📡 URL cible : {safe_url}")

    try:
        print("\n⏳ 1. Test de connexion réseau...")
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT version();"))
            pg_version = result.scalar()
            print(f"✅ Connexion réussie ! Version PostgreSQL : {pg_version}")

            print("\n⏳ 2. Vérification de l'extension 'vector' (pgvector)...")
            ext_check = await session.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector';")
            )
            ext_version = ext_check.scalar()
            if ext_version:
                print(f"✅ Extension pgvector activée (version : {ext_version}) !")
            else:
                print("⚠️ L'extension 'vector' n'est pas encore activée sur cette base.")
                print("💡 Exécutez dans le SQL Editor de Supabase : CREATE EXTENSION IF NOT EXISTS vector;")

            print("\n⏳ 3. Synchronisation et vérification des tables...")
            await init_db()

            count_check = await session.execute(
                text("SELECT count(*) FROM legal_articles;")
            )
            article_count = count_check.scalar() or 0
            print(f"📚 Articles du Code du numérique en base : {article_count} / 646")

            if article_count == 0:
                print("\n💡 La base est connectée mais vide. Pour ingérer les 646 articles, lancez :")
                print("   python scripts/run_ingestion.py --json data/processed/code_du_numerique_complet.json")
            else:
                print("🎉 Base de données opérationnelle et prête pour les requêtes citoyennes !")

    except Exception as e:
        print(f"\n❌ Échec de la connexion à la base de données : {e}")
        print("\n💡 Vérifiez :")
        print("   1. Que votre mot de passe Supabase dans .env est correct.")
        print("   2. Que vous utilisez bien 'postgresql+asyncpg://...' pour DATABASE_URL.")
        print("   3. Que le projet Supabase n'est pas en pause.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(check_database())
