from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.schemas.rag import LegalQuestionResponse, LegalStatus
from src.infrastructure.whatsapp.sender import WhatsAppMessageSender


def make_dummy_response(status: LegalStatus, escalate: bool = False) -> LegalQuestionResponse:
    return LegalQuestionResponse(
        interaction_id="uuid-123",
        statut_legal=status,
        articles_cites=["Article 552"],
        explication_vulgarisee="C'est interdit par la loi.",
        conseil_pratique="Ne diffusez pas la photo.",
        avertissement_legal="Outil de vulgarisation.",
        necessite_escalade=escalate,
    )


def test_format_legal_message_nominal():
    sender = WhatsAppMessageSender()
    resp = make_dummy_response(LegalStatus.INTERDIT, escalate=False)
    msg = sender.format_legal_message(resp)

    assert "STRICTEMENT INTERDIT" in msg
    assert "Article 552" in msg
    assert "C'est interdit par la loi." in msg
    assert "Outil de vulgarisation." in msg


def test_format_legal_message_with_escalation():
    sender = WhatsAppMessageSender()
    resp = make_dummy_response(LegalStatus.ZONE_GRISE, escalate=True)
    msg = sender.format_legal_message(resp)

    assert "ZONE GRISE" in msg
    assert "Attention" in msg
    assert "juriste" in msg


@pytest.mark.asyncio
async def test_send_text_simulated_when_no_credentials():
    sender = WhatsAppMessageSender(access_token="", phone_number_id="")
    result = await sender.send_text_message("22997000000", "Bonjour")
    assert result["status"] == "simulated"
    assert result["recipient"] == "22997000000"


@pytest.mark.asyncio
async def test_send_text_with_api_call():
    sender = WhatsAppMessageSender(access_token="tok_123", phone_number_id="phone_456")

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"messages": [{"id": "wamid.123"}]})
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = await sender.send_text_message("22997000000", "Hello")
        assert "messages" in result
        mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_send_legal_response_and_interactive_buttons():
    sender = WhatsAppMessageSender(access_token="tok_123", phone_number_id="phone_456")
    resp = make_dummy_response(LegalStatus.ZONE_GRISE, escalate=True)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"messages": [{"id": "wamid.btn"}]})
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        res = await sender.send_legal_response("22997000000", resp)
        assert "messages" in res
        mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_get_media_url_simulated_and_api():
    sender_sim = WhatsAppMessageSender(access_token="", phone_number_id="")
    url = await sender_sim.get_media_url("med_123")
    assert url == "https://graph.facebook.com/v21.0/med_123/download_simulated"

    sender_real = WhatsAppMessageSender(access_token="tok", phone_number_id="phone")
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"url": "https://cdn.whatsapp.net/media_bin"})
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        res_url = await sender_real.get_media_url("med_real")
        assert res_url == "https://cdn.whatsapp.net/media_bin"


@pytest.mark.asyncio
async def test_download_media_simulated_and_api():
    sender_sim = WhatsAppMessageSender(access_token="", phone_number_id="")
    data = await sender_sim.download_media("med_123")
    assert data == b"simulated_media_binary_content"

    sender_real = WhatsAppMessageSender(access_token="tok", phone_number_id="phone")
    with patch.object(sender_real, "get_media_url", new_callable=AsyncMock) as mock_get_url:
        mock_get_url.return_value = "https://cdn.whatsapp.net/media_bin"
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.content = b"audio_or_image_binary"
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            downloaded = await sender_real.download_media("med_real")
            assert downloaded == b"audio_or_image_binary"


@pytest.mark.asyncio
async def test_send_audio_message():
    sender_sim = WhatsAppMessageSender(access_token="", phone_number_id="")
    res_sim = await sender_sim.send_audio_message("22997000000", audio_url="https://audio.ogg")
    assert res_sim["status"] == "simulated"

    sender_real = WhatsAppMessageSender(access_token="tok", phone_number_id="phone")
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"messages": [{"id": "wamid.audio"}]})
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        res_real = await sender_real.send_audio_message(
            "22997000000", audio_url="https://audio.ogg"
        )
        assert "messages" in res_real
        mock_post.assert_called_once()

