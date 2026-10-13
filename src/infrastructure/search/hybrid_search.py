import logging
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.law import ArticleEmbedding, LawVersion, LegalArticle, LegalStructure
from src.infrastructure.llm.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


class SearchResult:
    def __init__(
        self,
        article: LegalArticle,
        structure: LegalStructure | None,
        rrf_score: float,
        dense_rank: int | None = None,
        fts_rank: int | None = None,
        is_exact_match: bool = False,
    ):
        self.article = article
        self.structure = structure
        self.rrf_score = rrf_score
        self.dense_rank = dense_rank
        self.fts_rank = fts_rank
        self.is_exact_match = is_exact_match


class HybridSearchEngine:
    """Moteur de recherche hybride combinant BM25 (tsvector) et dense vectoriel (pgvector)."""

    ARTICLE_QUERY_REGEX = re.compile(r"(?:article|art\.?)\s*(\d+(?:[-–]\d+)?)", re.IGNORECASE)

    def __init__(
        self,
        gemini_client: GeminiClient,
        rrf_k: int = 60,
        dense_weight: float = 1.0,
        fts_weight: float = 1.0,
        exact_boost: float = 2.0,
    ):
        self.gemini_client = gemini_client
        self.rrf_k = rrf_k
        self.dense_weight = dense_weight
        self.fts_weight = fts_weight
        self.exact_boost = exact_boost

    def extract_queried_article_numbers(self, query: str) -> list[str]:
        """Détecte si la requête mentionne explicitement un ou plusieurs numéros d'articles."""
        return [m.strip() for m in self.ARTICLE_QUERY_REGEX.findall(query)]

    async def search(
        self,
        session: AsyncSession,
        query: str,
        top_k: int = 5,
        dense_limit: int = 15,
        fts_limit: int = 15,
    ) -> list[SearchResult]:
        """Exécute la recherche hybride RRF et renvoie les articles les plus pertinents."""

        # 1. Recherche Dense (Embeddings)
        query_vector = await self.gemini_client.get_embedding(query)
        dense_stmt = (
            select(
                LegalArticle,
                LegalStructure,
                ArticleEmbedding.embedding.cosine_distance(query_vector).label("distance"),
            )
            .join(LawVersion, LegalArticle.law_version_id == LawVersion.id)
            .join(ArticleEmbedding, LegalArticle.id == ArticleEmbedding.article_id)
            .outerjoin(LegalStructure, LegalArticle.structure_id == LegalStructure.id)
            .where(
                LawVersion.is_active.is_(True),
                LegalArticle.is_in_force.is_(True),
            )
            .order_by("distance")
            .limit(dense_limit)
        )
        dense_res = await session.execute(dense_stmt)
        dense_hits = dense_res.all()

        # 2. Recherche Textuelle (Full-Text Search PostgreSQL en français)
        clean_query = query.replace("'", " ").replace('"', " ").strip()
        fts_stmt = (
            select(
                LegalArticle,
                LegalStructure,
                func.ts_rank_cd(
                    LegalArticle.search_vector,
                    func.plainto_tsquery("french", clean_query),
                ).label("rank"),
            )
            .join(LawVersion, LegalArticle.law_version_id == LawVersion.id)
            .outerjoin(LegalStructure, LegalArticle.structure_id == LegalStructure.id)
            .where(
                LawVersion.is_active.is_(True),
                LegalArticle.is_in_force.is_(True),
                LegalArticle.search_vector.op("@@")(func.plainto_tsquery("french", clean_query)),
            )
            .order_by(
                func.ts_rank_cd(
                    LegalArticle.search_vector,
                    func.plainto_tsquery("french", clean_query),
                ).desc()
            )
            .limit(fts_limit)
        )
        fts_res = await session.execute(fts_stmt)
        fts_hits = fts_res.all()

        # 3. Reciprocal Rank Fusion (RRF)
        article_scores: dict[str, dict[str, Any]] = {}

        for rank, (article, structure, _dist) in enumerate(dense_hits, start=1):
            art_id = str(article.id)
            article_scores[art_id] = {
                "article": article,
                "structure": structure,
                "score": self.dense_weight * (1.0 / (self.rrf_k + rank)),
                "dense_rank": rank,
                "fts_rank": None,
                "is_exact_match": False,
            }

        for rank, (article, structure, _rank_score) in enumerate(fts_hits, start=1):
            art_id = str(article.id)
            addition = self.fts_weight * (1.0 / (self.rrf_k + rank))
            if art_id in article_scores:
                article_scores[art_id]["score"] += addition
                article_scores[art_id]["fts_rank"] = rank
            else:
                article_scores[art_id] = {
                    "article": article,
                    "structure": structure,
                    "score": addition,
                    "dense_rank": None,
                    "fts_rank": rank,
                    "is_exact_match": False,
                }

        # 4. Boost des mentions exactes d'articles
        queried_articles = self.extract_queried_article_numbers(query)
        if queried_articles:
            exact_stmt = (
                select(LegalArticle, LegalStructure)
                .join(LawVersion, LegalArticle.law_version_id == LawVersion.id)
                .outerjoin(LegalStructure, LegalArticle.structure_id == LegalStructure.id)
                .where(
                    LawVersion.is_active.is_(True),
                    LegalArticle.is_in_force.is_(True),
                    LegalArticle.article_number.in_(queried_articles),
                )
            )
            exact_res = await session.execute(exact_stmt)
            exact_hits = exact_res.all()
            for article, structure in exact_hits:
                art_id = str(article.id)
                if art_id in article_scores:
                    article_scores[art_id]["score"] += self.exact_boost
                    article_scores[art_id]["is_exact_match"] = True
                else:
                    article_scores[art_id] = {
                        "article": article,
                        "structure": structure,
                        "score": self.exact_boost,
                        "dense_rank": None,
                        "fts_rank": None,
                        "is_exact_match": True,
                    }

        # Tri par score RRF décroissant
        sorted_results = sorted(article_scores.values(), key=lambda x: x["score"], reverse=True)

        return [
            SearchResult(
                article=item["article"],
                structure=item["structure"],
                rrf_score=item["score"],
                dense_rank=item["dense_rank"],
                fts_rank=item["fts_rank"],
                is_exact_match=item.get("is_exact_match", False),
            )
            for item in sorted_results[:top_k]
        ]
