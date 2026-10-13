import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.entities.law import LegalArticle, LegalStructure
from src.infrastructure.search.hybrid_search import HybridSearchEngine, SearchResult


@pytest.mark.asyncio
async def test_hybrid_search_rrf_scoring():
    """Vérifie la fusion RRF entre résultats denses et textuels."""
    mock_gemini = MagicMock()
    mock_gemini.get_embedding = AsyncMock(return_value=[0.1] * 768)

    engine = HybridSearchEngine(gemini_client=mock_gemini, rrf_k=60)

    art1 = LegalArticle(
        id=uuid.uuid4(),
        article_number="550",
        full_content="Texte article 550",
        is_in_force=True,
    )
    art2 = LegalArticle(
        id=uuid.uuid4(),
        article_number="552",
        full_content="Texte article 552",
        is_in_force=True,
    )
    struct = LegalStructure(
        id=uuid.uuid4(),
        structure_type="CHAPITRE",
        number_label="I",
        title="Dispositions",
    )

    mock_session = AsyncMock()

    # dense hits: art1 at rank 1, art2 at rank 2
    mock_dense_res = MagicMock()
    mock_dense_res.all.return_value = [
        (art1, struct, 0.12),
        (art2, struct, 0.25),
    ]

    # fts hits: art1 at rank 1
    mock_fts_res = MagicMock()
    mock_fts_res.all.return_value = [
        (art1, struct, 0.88),
    ]

    mock_session.execute = AsyncMock(side_effect=[mock_dense_res, mock_fts_res])

    results = await engine.search(
        session=mock_session,
        query="cybercriminalité",
        top_k=5,
    )

    assert len(results) == 2
    assert isinstance(results[0], SearchResult)
    # art1 a été trouvé dans les deux sources -> plus haut score RRF
    assert results[0].article.article_number == "550"
    assert results[0].dense_rank == 1
    assert results[0].fts_rank == 1
    assert results[0].rrf_score > results[1].rrf_score
