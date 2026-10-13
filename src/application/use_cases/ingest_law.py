import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.law import (
    ArticleEmbedding,
    LawVersion,
    LegalArticle,
    LegalStructure,
)
from src.infrastructure.llm.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


@dataclass
class ParsedArticle:
    """Représentation intermédiaire d'un article extrait d'un texte brut."""

    article_number: str
    content: str
    title: str | None = None
    hierarchy: dict[str, Any] | None = None


@dataclass
class IngestionReport:
    """Rapport statistique détaillé de l'opération d'ingestion."""

    law_version_id: uuid.UUID
    code_name: str
    official_reference: str
    total_articles: int
    created_articles: int
    updated_articles: int
    total_structures: int
    created_structures: int
    embeddings_computed: int


def parse_structure_component(
    level_type: str, raw_value: Any
) -> tuple[str, str, str]:
    """Extrait (structure_type, number_label, title) depuis une chaîne ou un dict.

    Exemples:
    - 'LIVRE PRELIMINAIRE' -> ('LIVRE', 'PRELIMINAIRE', 'LIVRE PRELIMINAIRE')
    - 'TITRE PREMIER' -> ('TITRE', 'PREMIER', 'TITRE PREMIER')
    - 'CHAPITRE II : Des principes généraux' -> ('CHAPITRE', 'II', 'Des principes généraux')
    - {'structure_type': 'SECTION', 'number_label': 'I', 'title': 'Champ'}
    """
    if isinstance(raw_value, dict):
        stype = str(raw_value.get("structure_type") or level_type.upper()).strip()
        num_label = str(raw_value.get("number_label") or "").strip()
        title = str(raw_value.get("title") or f"{stype} {num_label}").strip()
        return stype, num_label, title

    raw_str = str(raw_value).strip()
    match = re.match(
        r"^(LIVRE|TITRE|CHAPITRE|SECTION)\s+([^\s:-]+(?:\s+[^\s:-]+)?)(?:\s*[:–-]\s*(.+))?$",
        raw_str,
        re.IGNORECASE,
    )
    if match:
        stype = match.group(1).upper()
        num_label = match.group(2).strip()
        title = match.group(3).strip() if match.group(3) else raw_str
        return stype, num_label, title

    parts = raw_str.split(maxsplit=1)
    if len(parts) == 2 and parts[0].upper() in {"LIVRE", "TITRE", "CHAPITRE", "SECTION"}:
        return parts[0].upper(), parts[1].strip(), raw_str

    return level_type.upper(), raw_str, raw_str


class IngestLawUseCase:
    """Découpe, valide, structure et indexe le Code du numérique dans PostgreSQL + pgvector."""

    ARTICLE_SPLIT_REGEX = re.compile(
        r"(?:^|\n)\s*(?:Article|Art\.)\s*(1er|\d+(?:[-–]\d+)?)\s*[:.-]?\s*",
        re.IGNORECASE | re.MULTILINE,
    )

    def __init__(self, gemini_client: GeminiClient | None = None) -> None:
        self.gemini_client = gemini_client or GeminiClient()

    def parse_legal_text(self, raw_text: str) -> list[ParsedArticle]:
        """Découpe le texte intégral brut en articles individuels."""
        matches = list(self.ARTICLE_SPLIT_REGEX.finditer(raw_text))
        parsed_articles: list[ParsedArticle] = []

        if not matches:
            logger.warning("Aucun article détecté avec l'expression régulière standard.")
            return []

        for i, match in enumerate(matches):
            art_num = match.group(1).strip()
            start_pos = match.end()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(raw_text)

            content = raw_text[start_pos:end_pos].strip()
            if content:
                # Tentative d'extraction d'un titre sur la première ligne
                lines = content.split("\n", 1)
                first_line = lines[0].strip()
                title: str | None = None
                body_content = content
                if len(lines) > 1 and len(first_line) < 120 and not first_line.endswith("."):
                    title = first_line
                    body_content = lines[1].strip()

                parsed_articles.append(
                    ParsedArticle(
                        article_number=art_num,
                        title=title,
                        content=body_content,
                    )
                )

        logger.info(f"{len(parsed_articles)} articles découpés depuis le texte brut.")
        return parsed_articles

    async def ingest_from_json(
        self,
        session: AsyncSession,
        json_path: str | Path,
        code_name: str = "Code du numérique",
        official_reference: str = "Loi 2017-20 modifiée 2020-35",
        promulgation_date: date | None = date(2018, 4, 20),
        effective_date: date | None = date(2021, 1, 6),
        notes: str | None = None,
        batch_size: int = 50,
        compute_embeddings: bool = True,
    ) -> IngestionReport:
        """Charge un fichier JSON structuré et exécute l'ingestion complète idempotente."""
        path = Path(json_path)
        if not path.is_file():
            raise FileNotFoundError(f"Le fichier JSON d'ingestion est introuvable : {path}")

        with open(path, encoding="utf-8") as f:
            articles_data: list[dict[str, Any]] = json.load(f)

        logger.info(f"Chargement de {len(articles_data)} articles depuis {path}")
        return await self.ingest_articles(
            session=session,
            articles_data=articles_data,
            code_name=code_name,
            official_reference=official_reference,
            promulgation_date=promulgation_date,
            effective_date=effective_date,
            notes=notes,
            batch_size=batch_size,
            compute_embeddings=compute_embeddings,
        )

    async def ingest_articles(
        self,
        session: AsyncSession,
        articles_data: list[dict[str, Any]],
        code_name: str = "Code du numérique",
        official_reference: str = "Loi 2017-20 modifiée 2020-35",
        promulgation_date: date | None = date(2018, 4, 20),
        effective_date: date | None = date(2021, 1, 6),
        notes: str | None = None,
        batch_size: int = 50,
        compute_embeddings: bool = True,
    ) -> IngestionReport:
        """Ingère les articles et leur arborescence hiérarchique avec idempotence totale."""
        # 1. Résolution ou création idempotente de LawVersion
        stmt_version = select(LawVersion).where(LawVersion.official_reference == official_reference)
        res_version = await session.execute(stmt_version)
        law_version = res_version.scalars().first()

        if law_version is None:
            law_version = LawVersion(
                code_name=code_name,
                official_reference=official_reference,
                promulgation_date=promulgation_date,
                effective_date=effective_date,
                is_active=True,
                notes=notes,
            )
            session.add(law_version)
            await session.flush()
            logger.info(f"Nouvelle LawVersion créée : {official_reference} (ID: {law_version.id})")
        else:
            law_version.code_name = code_name
            law_version.is_active = True
            if promulgation_date is not None:
                law_version.promulgation_date = promulgation_date
            if effective_date is not None:
                law_version.effective_date = effective_date
            if notes is not None:
                law_version.notes = notes
            await session.flush()
            logger.info(f"LawVersion existante mise à jour : {official_reference} (ID: {law_version.id})")

        # 2. Préchargement des structures existantes pour idempotence
        stmt_structs = select(LegalStructure).where(LegalStructure.law_version_id == law_version.id)
        res_structs = await session.execute(stmt_structs)
        existing_structs = res_structs.scalars().all()

        structures_cache: dict[tuple[uuid.UUID | None, str, str], LegalStructure] = {
            (s.parent_id, s.structure_type, s.number_label): s for s in existing_structs
        }
        created_structures_count = 0
        order_counter = len(structures_cache)

        # 3. Préchargement des articles existants pour idempotence
        stmt_articles = select(LegalArticle).where(LegalArticle.law_version_id == law_version.id)
        res_articles = await session.execute(stmt_articles)
        existing_articles = res_articles.scalars().all()
        articles_cache: dict[str, LegalArticle] = {
            a.article_number: a for a in existing_articles
        }

        # 4. Préchargement des embeddings existants indexés par article_id
        existing_article_ids = [a.id for a in existing_articles]
        embeddings_cache: dict[uuid.UUID, ArticleEmbedding] = {}
        if existing_article_ids:
            stmt_embeddings = select(ArticleEmbedding).where(
                ArticleEmbedding.article_id.in_(existing_article_ids),
                ArticleEmbedding.model_name == "text-embedding-004",
            )
            res_embeddings = await session.execute(stmt_embeddings)
            for emb in res_embeddings.scalars().all():
                embeddings_cache[emb.article_id] = emb

        created_articles_count = 0
        updated_articles_count = 0
        computed_embeddings_count = 0

        # Niveaux hiérarchiques canoniques ordonnés
        hierarchy_levels = ["livre", "titre", "chapitre", "section"]

        for idx, art_dict in enumerate(articles_data):
            art_number = str(art_dict.get("article_number", "")).strip()
            if not art_number:
                continue

            art_title = art_dict.get("title")
            art_content = art_dict.get("full_content") or art_dict.get("content", "")
            art_in_force = bool(art_dict.get("is_in_force", True))
            art_amendment_notes = art_dict.get("amendment_notes")

            # A. Résolution hiérarchique
            raw_hierarchy = art_dict.get("hierarchy") or {}
            current_parent_id: uuid.UUID | None = None
            most_specific_structure: LegalStructure | None = None

            for lvl_key in hierarchy_levels:
                lvl_val = raw_hierarchy.get(lvl_key)
                if not lvl_val:
                    continue

                stype, snum, stitle = parse_structure_component(lvl_key, lvl_val)
                cache_key = (current_parent_id, stype, snum)

                if cache_key in structures_cache:
                    struct = structures_cache[cache_key]
                    if stitle and struct.title != stitle:
                        struct.title = stitle
                else:
                    order_counter += 1
                    struct = LegalStructure(
                        law_version_id=law_version.id,
                        parent_id=current_parent_id,
                        structure_type=stype,
                        number_label=snum,
                        title=stitle,
                        order_index=order_counter,
                    )
                    session.add(struct)
                    await session.flush()
                    structures_cache[cache_key] = struct
                    created_structures_count += 1

                current_parent_id = struct.id
                most_specific_structure = struct

            # B. Création ou mise à jour de l'article
            structure_id = most_specific_structure.id if most_specific_structure else None
            search_text = f"Article {art_number} {art_title or ''} {art_content}".strip()
            search_vector_expr = func.to_tsvector("french", search_text)

            if art_number in articles_cache:
                article = articles_cache[art_number]
                article.title = art_title
                article.full_content = art_content
                article.structure_id = structure_id
                article.is_in_force = art_in_force
                article.search_vector = search_vector_expr
                if art_amendment_notes:
                    article.amendment_notes = art_amendment_notes
                updated_articles_count += 1
            else:
                article = LegalArticle(
                    law_version_id=law_version.id,
                    structure_id=structure_id,
                    article_number=art_number,
                    title=art_title,
                    full_content=art_content,
                    is_in_force=art_in_force,
                    amendment_notes=art_amendment_notes,
                    search_vector=search_vector_expr,
                )
                session.add(article)
                await session.flush()
                articles_cache[art_number] = article
                created_articles_count += 1

            # C. Génération et indexation de l'embedding
            if compute_embeddings:
                emb_text_parts = [f"Article {art_number}"]
                if art_title:
                    emb_text_parts.append(f": {art_title}")
                emb_text_parts.append(f"\n\n{art_content}")
                embed_input = "".join(emb_text_parts)

                existing_emb = embeddings_cache.get(article.id)
                if existing_emb is None:
                    vector = await self.gemini_client.get_embedding(embed_input)
                    new_emb = ArticleEmbedding(
                        article_id=article.id,
                        model_name="text-embedding-004",
                        embedding=vector,
                    )
                    session.add(new_emb)
                    embeddings_cache[article.id] = new_emb
                    computed_embeddings_count += 1

            # Flush par lot
            if batch_size > 0 and (idx + 1) % batch_size == 0:
                await session.flush()
                logger.info(f"Progression ingestion : {idx + 1}/{len(articles_data)} articles traités.")

        # Validation finale de la transaction
        await session.commit()
        await session.refresh(law_version)

        report = IngestionReport(
            law_version_id=law_version.id,
            code_name=code_name,
            official_reference=official_reference,
            total_articles=len(articles_cache),
            created_articles=created_articles_count,
            updated_articles=updated_articles_count,
            total_structures=len(structures_cache),
            created_structures=created_structures_count,
            embeddings_computed=computed_embeddings_count,
        )
        logger.info(
            f"Ingestion terminée avec succès pour '{official_reference}' : "
            f"{report.total_articles} articles au total ({report.created_articles} créés, "
            f"{report.updated_articles} mis à jour), {report.total_structures} structures "
            f"({report.created_structures} créées), {report.embeddings_computed} nouveaux embeddings."
        )
        return report

    async def ingest_law_version(
        self,
        session: AsyncSession,
        code_name: str,
        official_reference: str,
        effective_date: date,
        raw_text: str,
    ) -> LawVersion:
        """Méthode de compatibilité pour ingérer un texte brut découpé dynamiquement."""
        parsed = self.parse_legal_text(raw_text)
        articles_dicts = [
            {
                "article_number": p.article_number,
                "title": p.title,
                "full_content": p.content,
                "hierarchy": p.hierarchy or {},
            }
            for p in parsed
        ]
        await self.ingest_articles(
            session=session,
            articles_data=articles_dicts,
            code_name=code_name,
            official_reference=official_reference,
            effective_date=effective_date,
            batch_size=50,
            compute_embeddings=True,
        )
        stmt = select(LawVersion).where(LawVersion.official_reference == official_reference)
        res = await session.execute(stmt)
        return res.scalar_one()


# Alias pour rétro-compatibilité
LawIngestionUseCase = IngestLawUseCase
