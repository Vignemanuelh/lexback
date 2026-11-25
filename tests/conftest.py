from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.schemas.rag import LegalResponseSchema, LegalStatus


@pytest.fixture
def mock_gemini():
    """Mock obligatoire pour le client Google Gemini (embeddings et structured output)."""
    with patch("src.infrastructure.llm.gemini_client.GeminiClient") as mock_client:
        instance = mock_client.return_value
        # Simule l'embedding 768 dimensions
        instance.get_embedding = AsyncMock(return_value=[0.05] * 768)
        # Simule la réponse structurée officielle
        instance.generate_legal_response = AsyncMock(
            return_value=LegalResponseSchema(
                statut_legal=LegalStatus.INTERDIT,
                articles_cites=["Article 552"],
                explication_vulgarisee=(
                    "La captation ou la diffusion de l'image d'une personne sans son "
                    "consentement préalable est interdite par la loi béninoise."
                ),
                conseil_pratique=(
                    "Ne diffusez pas cette photo sans avoir recueilli l'accord "
                    "écrit ou formel de la personne concernée."
                ),
                avertissement_legal=(
                    "Cet assistant est un outil d'information et ne remplace pas "
                    "un conseil juridique professionnel dispensé par un avocat."
                ),
                necessite_escalade=False,
            )
        )
        yield instance


@pytest.fixture
def mock_whatsapp():
    """Mock obligatoire pour l'API Meta WhatsApp Graph."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"messages": [{"id": "wamid.HBgL..."}]}),
        )
        yield mock_post


@pytest.fixture
def mock_whisper():
    """Mock pour la transcription vocale (STT)."""
    with patch(
        "src.infrastructure.audio.transcriber.AudioTranscriber.transcribe_file",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = "Est-ce que je peux publier la capture d'un message privé sur Facebook ?"
        yield m


@pytest.fixture
def mock_tts():
    """Mock pour la synthèse vocale (TTS)."""
    with patch(
        "src.infrastructure.audio.synthesizer.SpeechSynthesizer.synthesize_speech",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = b"OggS_fake_audio_bytes"
        yield m

