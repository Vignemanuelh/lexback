from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.domain.schemas.rag import LegalArticleCitation, LegalQuestionResponse, LegalStatus
from src.main import app


@pytest.mark.asyncio
async def test_ask_legal_question_streaming_endpoint():
    dummy_resp = LegalQuestionResponse(
        interaction_id="uuid-stream-1",
        statut_legal=LegalStatus.INTERDIT,
        articles_cites=["Article 552"],
        explication_vulgarisee="La captation d'image sans consentement est interdite par la loi.",
        conseil_pratique="Demandez un accord écrit.",
        avertissement_legal="Outil de vulgarisation.",
        necessite_escalade=False,
        sources=[
            LegalArticleCitation(
                article_number="Article 552",
                structure_title="Atteintes à la vie privée",
                content="Texte 552",
                relevance_score=0.9,
            )
        ],
    )

    with patch(
        "src.presentation.api.v1.router.AskLegalQuestionUseCase.execute",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.return_value = dummy_resp

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/legal/ask/stream",
                json={"question": "Puis-je poster une photo d'un collègue sans accord ?"},
            )

        assert res.status_code == 200
        assert "text/event-stream" in res.headers["content-type"]
        body_text = res.text

        # Vérifie la présence des étapes SSE
        assert '"type": "status"' in body_text
        assert '"type": "sources"' in body_text
        assert '"type": "token"' in body_text
        assert '"type": "complete"' in body_text
        assert "Article 552" in body_text
