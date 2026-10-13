import re
import logging
from dataclasses import dataclass
from datetime import date
from sqlalchemy import func
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
    article_number: str
    content: str
    structure_type: str | None = None
    structure_title: str | None = None


class LawIngestionUseCase:
    """Découpe, valide et indexe le Code du numérique par article complet."""

    ARTICLE_SPLIT_REGEX = re.compile(
        r"(?:^|\n)\s*(?:Article|Art\.)\s*(\d+(?:[-–]\d+)?)\s*[:.-]?\s*",
        re.IGNORECASE | re.MULTILINE,
    )

    STRUCTURE_REGEX = re.compile(
        r"(?:^|\n)\s*(LIVRE|TITRE|CHAPITRE|SECTION)\s+([IVXLCDM\d]+(?:er|ère)?)\s*[:.-]?\s*([^\n]+)",
        re.IGNORECASE | re.MULTILINE,
    )

    def __init__(self, gemini_client: GeminiClient):
        self.gemini_client = gemini_client

    def parse_legal_text(self, raw_text: str) -> list[ParsedArticle]:
        """Découpe le texte intégral en articles complets tout en capturant la hiérarchie."""
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
                parsed_articles.append(
                    ParsedArticle(
                        article_number=art_num,
                        content=content,
                    )
                )

        logger.info(f"{len(parsed_articles)} articles découpés avec succès.")
        return parsed_articles

    async def ingest_law_version(
        self,
        session: AsyncSession,
        code_name: str,
        official_reference: str,
        effective_date: date,
        raw_text: str,
    ) -> LawVersion:
        """Enregistre une nouvelle version de loi et indexe l'ensemble de ses articles."""

        # 1. Création de la version de loi
        law_version = LawVersion(
            code_name=code_name,
            official_reference=official_reference,
            effective_date=effective_date,
            is_active=True,
        )
        session.add(law_version)
        await session.flush()  # Obtient l'ID généré

        # 2. Découpage
        articles = self.parse_legal_text(raw_text)

        # 3. Insertion et indexation de chaque article
        for parsed in articles:
            article = LegalArticle(
                law_version_id=law_version.id,
                article_number=parsed.article_number,
                full_content=parsed.content,
                is_in_force=True,
                search_vector=func.to_tsvector("french", f"Article {parsed.article_number} {parsed.content}"),
            )
            session.add(article)
            await session.flush()

            # 4. Calcul de l'embedding
            vector = await self.gemini_client.get_embedding(
                f"Article {parsed.article_number}: {parsed.content}"
            )
            embedding = ArticleEmbedding(
                article_id=article.id,
                model_name="text-embedding-004",
                embedding=vector,
            )
            session.add(embedding)

        await session.commit()
        await session.refresh(law_version)
        logger.info(f"Version {official_reference} indexée avec {len(articles)} articles.")
        return law_version
