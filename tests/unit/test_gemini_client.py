from unittest.mock import MagicMock

import pytest

from src.domain.schemas.rag import LegalResponseSchema, LegalStatus
from src.infrastructure.llm.gemini_client import GeminiClient


@pytest.mark.asyncio
async def test_gemini_client_fallback_mode():
    """Vérifie le mode fallback / simulation quand aucune clé d'API n'est fournie."""
    client = GeminiClient(api_key=None)
    client.client = None

    vec = await client.get_embedding("Test question")
    assert len(vec) == 768
    assert all(v == 0.0 for v in vec)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY requise"):
        await client.generate_legal_response("prompt", "sys")


@pytest.mark.asyncio
async def test_gemini_client_embedding_mock():
    """Vérifie la génération d'embeddings avec un client mocké."""
    client = GeminiClient(api_key="fake-key")
    mock_genai_client = MagicMock()
    mock_resp = MagicMock()
    mock_item = MagicMock()
    mock_item.values = [0.1, 0.2, 0.3]
    mock_resp.embeddings = [mock_item]
    mock_genai_client.models.embed_content.return_value = mock_resp
    client.client = mock_genai_client

    vec = await client.get_embedding("Quels sont mes droits ?")
    assert vec == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_gemini_client_generate_response_mock():
    """Vérifie la génération structurée avec un client mocké."""
    client = GeminiClient(api_key="fake-key")
    mock_genai_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = """{
        "statut_legal": "autorisé",
        "articles_cites": ["Article 100"],
        "explication_vulgarisee": "Cette action est permise.",
        "conseil_pratique": "Respectez les conditions générales.",
        "avertissement_legal": "Outil d'information.",
        "necessite_escalade": false
    }"""
    mock_genai_client.models.generate_content.return_value = mock_resp
    client.client = mock_genai_client

    res = await client.generate_legal_response("prompt", "sys")
    assert isinstance(res, LegalResponseSchema)
    assert res.statut_legal == LegalStatus.AUTORISE
    assert res.articles_cites == ["Article 100"]
