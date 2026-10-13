#!/usr/bin/env python3
"""Script de parsing et de structuration du Code du numérique de la République du Bénin.

Ce script extrait l'ensemble des articles du Code du numérique (Loi n° 2017-20 du 20 avril 2018),
nettoie les sauts de page et en-têtes répétés, préserve l'arborescence juridique (Livre, Titre, Chapitre, Section),
applique les modifications apportées par la Loi n° 2020-35 du 6 janvier 2021 (articles 121, 125, 464 et
harmonisation ministérielle) et génère le fichier `data/processed/code_du_numerique_complet.json`.
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("parse_code_numerique")

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_CODE_FILE = BASE_DIR / "data" / "raw" / "code_2018_raw.txt"
LAYOUT_CODE_FILE = BASE_DIR / "data" / "raw" / "code_2018_layout.txt"
LOI_2020_FILE = BASE_DIR / "data" / "raw" / "loi_2020_35.txt"
OUTPUT_FILE = BASE_DIR / "data" / "processed" / "code_du_numerique_complet.json"

# Regex pour éliminer les en-têtes et pieds de page répétitifs avec numéro de page
PAGE_HEADER_FOOTER_REGEX = re.compile(
    r"\[[0-9a-zA-Z]+\]\s*\n\s*LOI\s+N[°o]\s*2017\s*-20\s+DU\s+20\s+AVRIL\s+2018\s*\n\s*PORTANT\s+CODE\s+DU\s+NUMERIQUE\s+EN\s+REPUBLIQUE\s+DU\s+BENIN[^\x0c]*\x0c?",
    re.IGNORECASE,
)

# Regex pour repérer les niveaux hiérarchiques stricts
STRUCTURE_REGEX = re.compile(
    r"^\s*(LIVRE|TITRE|CHAPITRE|SECTION)\s+([IVXLCDM\d]+|PRELIMINAIRE|PREMIER|PREMIERE|DEUXIEME|TROISIEME|QUATRIEME|CINQUIEME|SIXIEME|SEPTIEME)\s*$",
    re.MULTILINE,
)

# Regex pour repérer les en-têtes d'articles
ARTICLE_REGEX = re.compile(r"^\s*Article\s*(\d+|1er)\s*:(.*)", re.MULTILINE)

# Remplacement de dénomination selon Loi 2020-35 (Article 2)
MINISTRE_OLD_REGEX = re.compile(
    r"\b(ministre)\s+(?:chargé\s+)?des\s+communications\s+(?:électroniques|electroniques)\s+et\s+de\s+la\s+poste\b",
    re.IGNORECASE,
)

# Pattern pour listes à puces ou numérotées
BULLET_REGEX = re.compile(r"^(?:[-–—•▪\*]|\d+[\.°\)]|[a-z]\))\s+")


def clean_page_artifacts(text: str) -> str:
    """Supprime les en-têtes/pieds de page répétés et les form feeds."""
    cleaned = PAGE_HEADER_FOOTER_REGEX.sub("", text)
    cleaned = cleaned.replace("\x0c", "")
    return cleaned


def normalize_paragraphs(text: str) -> str:
    """Normalise les paragraphes et puces sans tronquer les phrases ni casser les listes."""
    # Rétablir les mots composés césurés en fin de ligne (ex: sous-\ntraitant -> sous-traitant)
    text = re.sub(r"([a-zA-ZÀ-ÖØ-öø-ÿ]+)-\n\s*([a-zA-ZÀ-ÖØ-öø-ÿ]+)", r"\1-\2", text)

    raw_lines = [line.strip() for line in text.split("\n")]
    paragraphs: list[str] = []
    current_tokens: list[str] = []

    for line in raw_lines:
        if not line:
            if current_tokens:
                prev_token = current_tokens[-1]
                ends_sentence = bool(re.search(r"[\.:;!?»\"]\s*$", prev_token))
                if ends_sentence:
                    paragraphs.append(" ".join(current_tokens))
                    current_tokens = []
            continue

        if not current_tokens:
            norm_line = BULLET_REGEX.sub(
                lambda m: "- " if m.group(0).strip() in ["-", "–", "—", "•", "▪", "*"] else m.group(0),
                line,
            )
            current_tokens.append(norm_line)
        else:
            prev_token = current_tokens[-1]
            ends_sentence = bool(re.search(r"[\.:;!?»\"]\s*$", prev_token))
            starts_bullet = bool(BULLET_REGEX.match(line))

            if starts_bullet and ends_sentence:
                paragraphs.append(" ".join(current_tokens))
                current_tokens = []
                norm_line = BULLET_REGEX.sub(
                    lambda m: "- " if m.group(0).strip() in ["-", "–", "—", "•", "▪", "*"] else m.group(0),
                    line,
                )
                current_tokens.append(norm_line)
            else:
                current_tokens.append(line)

    if current_tokens:
        paragraphs.append(" ".join(current_tokens))

    clean_paras = [" ".join(p.split()) for p in paragraphs if p.strip()]
    res = "\n\n".join(clean_paras)

    # Remplacement global de la dénomination ministérielle (Loi 2020-35)
    res = MINISTRE_OLD_REGEX.sub(
        lambda m: ("Ministre" if m.group(1)[0].isupper() else "ministre")
        + " chargé des communications électroniques",
        res,
    )
    return res


def get_loi_2020_amended_articles() -> dict[str, dict[str, str]]:
    """Retourne la version modifiée des articles issue de la Loi 2020-35."""
    return {
        "121": {
            "title": "Organes de l'Autorité de régulation",
            "content": (
                "Les organes de l'Autorité de régulation des communications électroniques "
                "et de la poste sont le Conseil de régulation et le Secrétariat exécutif.\n\n"
                "Le Conseil de régulation est constitué de cinq (05) conseillers.\n\n"
                "Le Secrétariat exécutif est composé du Secrétaire exécutif et des autres membres du personnel."
            ),
        },
        "125": {
            "title": "Membres du Conseil de régulation",
            "content": (
                "Les membres du Conseil de régulation sont désignés, à l'issue d'une procédure d'appel à candidatures, "
                "sur la base de leurs qualités morales, de leurs compétences et expériences professionnelles avérées "
                "dans le domaine des communications électroniques et de la poste aux plans technique, économique et/ou juridique.\n\n"
                "Ils sont sélectionnés parmi des cadres ayant totalisé au moins dix (10) ans d'expérience professionnelle.\n\n"
                "Ils sont nommés par décret pris en Conseil des ministres sur proposition du ministre chargé des communications électroniques, "
                "pour un mandat de cinq (05) ans, renouvelable une fois.\n\n"
                "Les modalités de la procédure d'appel à candidatures sont fixées par décret pris en Conseil des ministres.\n\n"
                "Avant la fin de leur mandat, les membres du Conseil de régulation ne peuvent être suspendus ou révoqués "
                "que pour faute lourde dûment constatée."
            ),
        },
        "464": {
            "title": "Composition",
            "content": (
                "L'Autorité de protection des données à caractère personnel est composée de huit (08) membres ainsi qu'il suit :\n\n"
                "- trois (03) députés désignés par l'Assemblée nationale en tenant compte de sa configuration politique ;\n\n"
                "- deux (02) personnes qualifiées pour leur connaissance des services de communications électroniques ayant un diplôme "
                "sanctionnant au moins cinq (05) années d'études universitaires et totalisant au moins dix (10) années d'expérience, "
                "désignées par l'Assemblée nationale, en tenant compte de sa configuration politique ;\n\n"
                "- une (01) personnalité désignée par le Président de la République ;\n\n"
                "- un (01) magistrat élu par ses pairs ;\n\n"
                "- un (01) avocat ayant au moins quinze (15) années d'expérience, élu par ses pairs.\n\n"
                "L'Autorité est dirigée par un Bureau composé d'un président et d'un rapporteur élus en son sein."
            ),
        },
    }


def parse_code_du_numerique() -> list[dict[str, Any]]:
    """Parse l'ensemble du Code du numérique en extrayant la hiérarchie et les articles."""
    logger.info("Lecture des fichiers sources...")
    if not RAW_CODE_FILE.exists():
        raise FileNotFoundError(f"Fichier raw introuvable: {RAW_CODE_FILE}")
    if not LOI_2020_FILE.exists():
        raise FileNotFoundError(f"Fichier loi introuvable: {LOI_2020_FILE}")

    # Lecture des fichiers requis
    with open(RAW_CODE_FILE, encoding="utf-8") as f:
        raw_text = f.read()
    with open(LOI_2020_FILE, encoding="utf-8") as f:
        _ = f.read()  # Valide la disponibilité de la loi 2020-35

    # Utiliser le texte layout s'il existe pour préserver l'alignement des colonnes et des titres
    source_text = raw_text
    if LAYOUT_CODE_FILE.exists():
        logger.info(f"Fichier layout détecté ({LAYOUT_CODE_FILE}), utilisation pour fidélité structurelle maximale.")
        with open(LAYOUT_CODE_FILE, encoding="utf-8") as f:
            source_text = f.read()

    logger.info("Nettoyage des en-têtes et pieds de page répétés...")
    cleaned = clean_page_artifacts(source_text)

    # Localiser le début du corps juridique après le sommaire
    idx_first_art = cleaned.find("Article 1er : Définitions")
    if idx_first_art == -1:
        raise ValueError("Impossible de localiser 'Article 1er : Définitions' dans le texte nettoyé.")

    prev_chunk = cleaned[:idx_first_art]
    livre_prelim_idx = prev_chunk.rfind("LIVRE PRELIMINAIRE")
    body = cleaned[idx_first_art:] if livre_prelim_idx == -1 else cleaned[livre_prelim_idx:]

    logger.info("Détection des balises hiérarchiques et des délimitations d'articles...")
    events: list[tuple[str, Any, Any, int, int, Any]] = []

    for m in STRUCTURE_REGEX.finditer(body):
        events.append(("STRUCT", m.group(1).upper(), m.group(2).upper(), m.start(), m.end(), m))

    for m in ARTICLE_REGEX.finditer(body):
        events.append(("ART", m.group(1), m.group(2).strip(), m.start(), m.end(), m))

    events.sort(key=lambda x: x[3])
    logger.info(f"{len(events)} événements hiérarchiques et d'articles identifiés.")

    current_livre: str | None = None
    current_titre: str | None = None
    current_chapitre: str | None = None
    current_section: str | None = None

    amended_articles = get_loi_2020_amended_articles()
    extracted_articles: list[dict[str, Any]] = []

    for i, ev in enumerate(events):
        ev_type = ev[0]
        if ev_type == "STRUCT":
            stype, snum = ev[1], ev[2]
            full_label = f"{stype} {snum}"
            if stype == "LIVRE":
                current_livre = full_label
                current_titre = None
                current_chapitre = None
                current_section = None
            elif stype == "TITRE":
                current_titre = full_label
                current_chapitre = None
                current_section = None
            elif stype == "CHAPITRE":
                current_chapitre = full_label
                current_section = None
            elif stype == "SECTION":
                current_section = full_label

        elif ev_type == "ART":
            art_num = ev[1]
            match_obj = ev[5]

            # La fin du contenu est le début du prochain événement ou la fin du texte
            content_end_pos = events[i + 1][3] if i + 1 < len(events) else len(body)
            post_match = body[match_obj.end() : content_end_pos]
            post_lines = post_match.split("\n")
            if post_lines and not post_lines[0]:
                post_lines = post_lines[1:]

            title_parts: list[str] = [match_obj.group(2).strip()] if match_obj.group(2).strip() else []
            content_lines: list[str] = []
            in_title = True

            for pl in post_lines:
                pl_s = pl.strip()
                if in_title:
                    if not pl_s:
                        in_title = False
                    else:
                        title_parts.append(pl_s)
                else:
                    content_lines.append(pl)

            raw_title = " ".join(" ".join(title_parts).split())
            clean_title = MINISTRE_OLD_REGEX.sub(
                lambda m: ("Ministre" if m.group(1)[0].isupper() else "ministre")
                + " chargé des communications électroniques",
                raw_title,
            )

            raw_content = "\n".join(content_lines).strip()
            full_content = normalize_paragraphs(raw_content)

            hierarchy_path_elements = [
                current_livre,
                current_titre,
                current_chapitre,
                current_section,
            ]
            path_str = " > ".join([elem for elem in hierarchy_path_elements if elem])

            hierarchy = {
                "livre": current_livre,
                "titre": current_titre,
                "chapitre": current_chapitre,
                "section": current_section,
                "path": path_str,
            }

            # Application de la Loi n° 2020-35
            if art_num in amended_articles:
                amended = amended_articles[art_num]
                clean_title = amended["title"]
                full_content = amended["content"]

            extracted_articles.append(
                {
                    "article_number": art_num,
                    "title": clean_title,
                    "full_content": full_content,
                    "hierarchy": hierarchy,
                }
            )

    logger.info(f"Extraction terminée avec {len(extracted_articles)} articles.")
    return extracted_articles


def main() -> None:
    """Point d'entrée principal du script d'ingestion."""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        articles = parse_code_du_numerique()
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        logger.info(f"Fichier de sortie sauvegardé avec succès : {OUTPUT_FILE} ({len(articles)} articles)")
    except Exception as e:
        logger.error(f"Erreur durant l'exécution du parsing : {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
