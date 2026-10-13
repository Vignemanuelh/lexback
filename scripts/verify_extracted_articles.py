#!/usr/bin/env python3
"""Script de validation et de vérification de complétude du Code du numérique parsé.

Ce script vérifie :
1. La présence et validité du fichier JSON généré (`data/processed/code_du_numerique_complet.json`).
2. Le nombre total d'articles (doit être supérieur à 640).
3. La présence intacte des articles stratégiques (1er, 121, 125, 464, 550, 552, 558, 647).
4. La bonne intégration des dispositions de la Loi n° 2020-35 (articles modifiés et harmonisation ministérielle).
5. L'intégrité rédactionnelle (aucune troncature de phrase, suppression totale des artefacts de page, arborescence complète).
"""

import json
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("verify_extracted_articles")

BASE_DIR = Path(__file__).resolve().parent.parent
PROCESSED_FILE = BASE_DIR / "data" / "processed" / "code_du_numerique_complet.json"

STRATEGIC_ARTICLES = ["1er", "121", "125", "464", "550", "552", "558", "647"]


def verify_articles_json() -> bool:
    """Valide l'intégrité globale et unitaire des articles extraits."""
    if not PROCESSED_FILE.exists():
        logger.error(f"Fichier résultat introuvable : {PROCESSED_FILE}")
        return False

    try:
        with open(PROCESSED_FILE, encoding="utf-8") as f:
            articles = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Le fichier JSON est invalide : {e}")
        return False

    if not isinstance(articles, list):
        logger.error(f"Le contenu JSON racine doit être une liste (reçu {type(articles).__name__})")
        return False

    total_articles = len(articles)
    logger.info(f"Nombre total d'articles trouvés : {total_articles}")

    if total_articles <= 640:
        logger.error(f"Échec : le nombre d'articles ({total_articles}) doit être strictement supérieur à 640.")
        return False

    # Indexation par article_number
    articles_by_num: dict[str, list[dict]] = {}
    for art in articles:
        num = art.get("article_number", "")
        articles_by_num.setdefault(num, []).append(art)

    errors: list[str] = []

    # 1. Vérification des articles stratégiques
    for target in STRATEGIC_ARTICLES:
        if target not in articles_by_num:
            errors.append(f"Article stratégique manquant : Article {target}")
            continue

        item = articles_by_num[target][0]
        content = item.get("full_content", "").strip()
        title = item.get("title", "").strip()
        hier = item.get("hierarchy", {})

        if not content:
            errors.append(f"Article {target} a un contenu vide !")
        if len(content) < 50:
            errors.append(f"Article {target} a un contenu anormalement court ({len(content)} caractères)")
        if not hier.get("livre"):
            errors.append(f"Article {target} n'a pas de Livre rattaché !")
        if not hier.get("path"):
            errors.append(f"Article {target} n'a pas de chemin hiérarchique (path) !")

    # 2. Vérification de l'intégration de la Loi 2020-35
    art_121 = articles_by_num.get("121", [{}])[0]
    content_121 = art_121.get("full_content", "")
    if "cinq (05) conseillers" not in content_121 or "Secrétariat exécutif" not in content_121:
        errors.append("Article 121 : La version nouvelle issue de la Loi 2020-35 n'est pas présente.")

    art_125 = articles_by_num.get("125", [{}])[0]
    content_125 = art_125.get("full_content", "")
    if "appel à candidatures" not in content_125 or "dix (10) ans" not in content_125:
        errors.append("Article 125 : La version nouvelle issue de la Loi 2020-35 n'est pas présente.")

    art_464 = articles_by_num.get("464", [{}])[0]
    content_464 = art_464.get("full_content", "")
    if "huit (08) membres" not in content_464 or "trois (03) députés" not in content_464:
        errors.append("Article 464 : La version nouvelle issue de la Loi 2020-35 n'est pas présente.")

    # 3. Vérification de l'harmonisation ministérielle (interdiction de l'ancienne dénomination)
    old_minister_pattern = re.compile(
        r"ministre\s+(?:chargé\s+)?des\s+communications\s+(?:électroniques|electroniques)\s+et\s+de\s+la\s+poste",
        re.IGNORECASE,
    )
    for art in articles:
        num = art.get("article_number", "?")
        content = art.get("full_content", "")
        title = art.get("title", "")
        if old_minister_pattern.search(content) or old_minister_pattern.search(title):
            errors.append(
                f"Article {num} contient encore l'ancienne mention 'ministre ... et de la poste' non remplacée."
            )

    # 4. Vérification de la non-troncature et suppression d'artefacts
    page_header_pattern = re.compile(r"\[\d+\]|LOI\s+N°2017\s*-20|\x0c", re.IGNORECASE)
    for art in articles:
        num = art.get("article_number", "?")
        content = art.get("full_content", "")
        title = art.get("title", "")

        # Détection d'en-têtes résiduels
        if page_header_pattern.search(content) or page_header_pattern.search(title):
            errors.append(f"Article {num} contient des en-têtes ou sauts de page non nettoyés !")

        # Détection de troncature flagrante (phrase coupée se terminant par un mot de liaison ou tiret)
        stripped_content = content.rstrip()
        if stripped_content.endswith(("-", " et", " ou", " la", " le", " de", " du", " dans", " par")):
            errors.append(f"Article {num} semble tronqué en fin de texte (se termine par '{stripped_content[-10:]}')")

    # Bilan
    if errors:
        logger.error(f"Validation ÉCHOUÉE : {len(errors)} erreur(s) détectée(s) :")
        for err in errors[:10]:
            logger.error(f" - {err}")
        if len(errors) > 10:
            logger.error(f" ... et {len(errors) - 10} autre(s) erreur(s).")
        return False

    logger.info("=" * 60)
    logger.info("TOUTES LES VÉRIFICATIONS SONT RÉUSSIES AVEC SUCCÈS !")
    logger.info(f" - Nombre total d'articles validés : {total_articles} (> 640)")
    logger.info(" - Présence certifiée des articles 1er, 121, 125, 464, 550, 552, 558, 647")
    logger.info(" - Amendements Loi 2020-35 intégrés à 100% (articles 121, 125, 464 et ministres)")
    logger.info(" - Zéro artefact de saut de page résiduel")
    logger.info(" - Intégrité rédactionnelle et arborescence juridique complètes")
    logger.info("=" * 60)
    return True


def main() -> None:
    """Point d'entrée du script de vérification."""
    success = verify_articles_json()
    if not success:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
