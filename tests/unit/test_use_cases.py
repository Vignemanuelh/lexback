from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.use_cases.ask_legal_question import AskLegalQuestionUseCase
from src.domain.schemas.rag import LegalQuestionRequest, LegalStatus


@pytest.mark.asyncio
async def test_ask_use_case_empty_search_escalates():
    """RG-JUR1 & RG-JUR5 : Si aucun article n'est trouvé, escalade immédiate sans appel LLM."""
    mock_gemini = MagicMock()
    mock_search = MagicMock()
    mock_search.search = AsyncMock(return_value=[])  # Aucun article trouvé
    mock_guardrail = MagicMock()

    use_case = AskLegalQuestionUseCase(
        gemini_client=mock_gemini,
        search_engine=mock_search,
        guardrail=mock_guardrail,
    )

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    request = LegalQuestionRequest(
        question="Quelle est la règle sur le vol de drone non connecté ?"
    )
    response = await use_case.execute(session=mock_session, request=request)

    assert response.statut_legal == LegalStatus.ZONE_GRISE
    assert response.necessite_escalade is True
    # Vérifie que Gemini n'a pas été appelé inutilement
    mock_gemini.generate_legal_response.assert_not_called()


@pytest.mark.asyncio
async def test_ask_use_case_success_with_guardrail():
    """Vérifie le flux nominal complet avec recherche, appel LLM et garde-fou."""
    from src.application.guardrails.citation_guardrail import GuardrailResult
    from src.domain.entities.law import LegalArticle, LegalStructure
    from src.domain.schemas.rag import LegalResponseSchema
    from src.infrastructure.search.hybrid_search import SearchResult

    art = LegalArticle(
        article_number="552",
        full_content="La captation de l'image d'une personne sans son accord est punie.",
        is_in_force=True,
    )
    struct = LegalStructure(
        structure_type="CHAPITRE",
        number_label="II",
        title="Atteintes à la vie privée",
    )
    search_hit = SearchResult(
        article=art,
        structure=struct,
        rrf_score=0.85,
        dense_rank=1,
        fts_rank=1,
    )

    mock_gemini = MagicMock()
    llm_resp = LegalResponseSchema(
        statut_legal=LegalStatus.INTERDIT,
        articles_cites=["Article 552"],
        explication_vulgarisee="C'est interdit par l'article 552.",
        conseil_pratique="Ne diffusez pas la photo.",
        necessite_escalade=False,
    )
    mock_gemini.generate_legal_response = AsyncMock(return_value=llm_resp)

    mock_search = MagicMock()
    mock_search.search = AsyncMock(return_value=[search_hit])

    mock_guardrail = MagicMock()
    mock_guardrail.validate.return_value = GuardrailResult(
        is_valid=True,
        validated_response=llm_resp,
        hallucinated_articles=[],
    )

    use_case = AskLegalQuestionUseCase(
        gemini_client=mock_gemini,
        search_engine=mock_search,
        guardrail=mock_guardrail,
    )

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    request = LegalQuestionRequest(
        question="Puis-je diffuser une photo d'un collègue sans lui demander ?"
    )
    response = await use_case.execute(session=mock_session, request=request)

    assert response.statut_legal == LegalStatus.INTERDIT
    assert response.necessite_escalade is False
    assert len(response.sources) == 1
    assert response.sources[0].article_number == "Article 552"
    assert response.confidence_score == 1.0
    mock_gemini.generate_legal_response.assert_called_once()

