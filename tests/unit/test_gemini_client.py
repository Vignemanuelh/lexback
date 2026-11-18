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
    call_kwargs = mock_genai_client.models.embed_content.call_args.kwargs
    assert call_kwargs["config"].output_dimensionality == 768


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


@pytest.mark.asyncio
async def test_gemini_client_fallback_on_429_and_cooldown(monkeypatch):
    """Vérifie la bascule automatique sur quota 429 et la mise en cooldown du modèle saturé."""
    from src.core.config import Settings
    from src.infrastructure.llm import gemini_client as gc_module
    from src.infrastructure.llm.retry import clear_model_cooldowns

    clear_model_cooldowns()
    monkeypatch.setattr(gc_module, "settings", Settings(_env_file=None))
    client = GeminiClient(api_key="fake-key")
    mock_genai_client = MagicMock()
    ok_resp = MagicMock()
    ok_resp.text = """{
        "statut_legal": "autorisé",
        "articles_cites": ["Article 100"],
        "explication_vulgarisee": "Permis.",
        "conseil_pratique": "RAS.",
        "avertissement_legal": "Info.",
        "necessite_escalade": false
    }"""

    called_models: list[str] = []

    def fake_generate(*, model: str, **_kwargs):
        called_models.append(model)
        if model == "gemini-4-hydrogen":
            raise RuntimeError("429 RESOURCE_EXHAUSTED: free tier limit reached")
        return ok_resp

    mock_genai_client.models.generate_content.side_effect = fake_generate
    client.client = mock_genai_client

    res1 = await client.generate_legal_response("prompt", "sys")
    assert res1.statut_legal == LegalStatus.AUTORISE
    assert client.last_used_model == "gemini-3.8-flash"
    assert called_models == ["gemini-4-hydrogen", "gemini-3.8-flash"]

    # Appel suivant pendant le cooldown : saute directement gemini-4-hydrogen
    called_models.clear()
    res2 = await client.generate_legal_response("prompt", "sys")
    assert res2.statut_legal == LegalStatus.AUTORISE
    assert called_models == ["gemini-3.8-flash"]
    clear_model_cooldowns()


@pytest.mark.asyncio
async def test_gemini_client_does_not_swallow_non_fallback_errors():
    """Vérifie qu'une erreur client 400 (non liée au quota) échoue immédiatement."""
    from src.infrastructure.llm.retry import clear_model_cooldowns

    clear_model_cooldowns()
    client = GeminiClient(api_key="fake-key")
    mock_genai_client = MagicMock()
    mock_genai_client.models.generate_content.side_effect = ValueError("400 INVALID_ARGUMENT")
    client.client = mock_genai_client

    with pytest.raises(ValueError, match="400 INVALID_ARGUMENT"):
        await client.generate_legal_response("prompt", "sys")
    assert mock_genai_client.models.generate_content.call_count == 1
