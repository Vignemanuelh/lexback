#!/usr/bin/env python3
"""Script CLI d'exécution de l'ingestion du Code du numérique dans PostgreSQL + pgvector.

Usage:
    python scripts/run_ingestion.py --json data/processed/code_du_numerique_complet.json --batch-size 50
"""

import argparse
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

# Assure que le répertoire racine du projet est dans sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.application.use_cases.ingest_law import IngestLawUseCase  # noqa: E402
from src.core.database import AsyncSessionLocal  # noqa: E402
from src.infrastructure.llm.gemini_client import GeminiClient  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_ingestion")


async def main_async(args: argparse.Namespace) -> None:
    json_path = Path(args.json)
    if not json_path.is_absolute():
        json_path = BASE_DIR / json_path

    if not json_path.exists():
        logger.error(f"Fichier introuvable: {json_path}")
        sys.exit(1)

    logger.info(f"Démarrage de l'ingestion depuis {json_path}")
    logger.info(f"Paramètres : batch_size={args.batch_size}, compute_embeddings={not args.skip_embeddings}")

    gemini_client = GeminiClient()
    use_case = IngestLawUseCase(gemini_client=gemini_client)

    async with AsyncSessionLocal() as session:
        report = await use_case.ingest_from_json(
            session=session,
            json_path=json_path,
            code_name=args.code_name,
            official_reference=args.official_reference,
            promulgation_date=date.fromisoformat(args.promulgation_date) if args.promulgation_date else None,
            effective_date=date.fromisoformat(args.effective_date) if args.effective_date else None,
            batch_size=args.batch_size,
            compute_embeddings=not args.skip_embeddings,
        )

    logger.info("=== BILAN DE L'INGESTION ===")
    logger.info(f"Version ID          : {report.law_version_id}")
    logger.info(f"Référence officielle: {report.official_reference}")
    logger.info(f"Articles au total   : {report.total_articles}")
    logger.info(f"Articles créés      : {report.created_articles}")
    logger.info(f"Articles mis à jour : {report.updated_articles}")
    logger.info(f"Structures au total : {report.total_structures}")
    logger.info(f"Structures créées   : {report.created_structures}")
    logger.info(f"Embeddings calculés : {report.embeddings_computed}")
    logger.info("Ingestion achevée avec succès.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingestion et indexation du Code du numérique dans PostgreSQL 18 pgvector."
    )
    parser.add_argument(
        "--json",
        type=str,
        default="data/processed/code_du_numerique_complet.json",
        help="Chemin vers le fichier JSON des articles structurés.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Nombre d'articles par lot pour le flush intermédiaire (défaut: 50).",
    )
    parser.add_argument(
        "--code-name",
        type=str,
        default="Code du numérique",
        help="Nom du code juridique (défaut: 'Code du numérique').",
    )
    parser.add_argument(
        "--official-reference",
        type=str,
        default="Code du numérique (Loi 2017-20 modifiée 2020-35)",
        help="Référence officielle de la loi.",
    )
    parser.add_argument(
        "--promulgation-date",
        type=str,
        default="2018-04-20",
        help="Date de promulgation (format YYYY-MM-DD).",
    )
    parser.add_argument(
        "--effective-date",
        type=str,
        default="2021-01-06",
        help="Date d'entrée en vigueur (format YYYY-MM-DD).",
    )
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Désactive la génération d'embeddings vectoriels (utile pour test sans API key).",
    )

    args = parser.parse_args()
    try:
        asyncio.run(main_async(args))
    except Exception as e:
        logger.error(f"Erreur fatale lors de l'ingestion : {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
