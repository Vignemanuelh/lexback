from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.application.use_cases.process_whatsapp_message import ProcessWhatsAppMessageUseCase
from src.domain.schemas.rag import LegalQuestionResponse, LegalStatus
from src.main import app


@pytest.mark.asyncio
async def test_whatsapp_webhook_get_verification_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(
            "/api/v1/whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "lexbenin_webhook_verify_token",
                "hub.challenge": "1158201444",
            },
        )
    assert res.status_code == 200
    assert res.text == "1158201444"


@pytest.mark.asyncio
async def test_whatsapp_webhook_get_verification_forbidden():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(
            "/api/v1/whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_token",
                "hub.challenge": "12345",
            },
        )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_whatsapp_webhook_post_always_returns_200():
    transport = ASGITransport(app=app)
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "messages": [{
                        "from": "22997000000",
                        "id": "wamid.123",
                        "type": "text",
                        "text": {"body": "Bonjour"},
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    with patch(
        "src.presentation.api.v1.whatsapp_webhook._process_whatsapp_in_background",
        new_callable=AsyncMock,
    ) as mock_bg:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post("/api/v1/whatsapp/webhook", json=payload)
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}
        mock_bg.assert_called_once()


@pytest.mark.asyncio
async def test_process_whatsapp_text_message():
    mock_ask = MagicMock()
    mock_ask.execute = AsyncMock(
        return_value=LegalQuestionResponse(
            interaction_id="uuid-1",
            statut_legal=LegalStatus.INTERDIT,
            articles_cites=["Article 552"],
            explication_vulgarisee="Interdit",
            conseil_pratique="Conseil",
            avertissement_legal="Legal",
            necessite_escalade=False,
        )
    )
    mock_sender = MagicMock()
    mock_sender.send_legal_response = AsyncMock(return_value={"status": "sent"})
    mock_transcriber = MagicMock()
    mock_vision = MagicMock()

    use_case = ProcessWhatsAppMessageUseCase(
        ask_use_case=mock_ask,
        whatsapp_sender=mock_sender,
        transcriber=mock_transcriber,
        vision_analyzer=mock_vision,
    )

    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "22997112233",
                        "type": "text",
                        "text": {"body": "Puis-je poster une photo sans accord ?"},
                    }]
                }
            }]
        }]
    }

    mock_session = AsyncMock()
    result = await use_case.execute(session=mock_session, payload=payload)

    assert result["status"] == "processed"
    assert result["statut_legal"] == "interdit"
    mock_ask.execute.assert_called_once()
    mock_sender.send_legal_response.assert_called_once()


@pytest.mark.asyncio
async def test_process_whatsapp_audio_message():
    mock_ask = MagicMock()
    mock_ask.execute = AsyncMock(
        return_value=LegalQuestionResponse(
            interaction_id="uuid-2",
            statut_legal=LegalStatus.AUTORISE,
            articles_cites=["Article 577"],
            explication_vulgarisee="Autorisé",
            conseil_pratique="Conseil",
            avertissement_legal="Legal",
            necessite_escalade=False,
        )
    )
    mock_sender = MagicMock()
    mock_sender.send_legal_response = AsyncMock(return_value={"status": "sent"})
    mock_transcriber = MagicMock()
    mock_transcriber.transcribe_bytes = AsyncMock(return_value="Puis-je chiffrer mes emails ?")
    mock_vision = MagicMock()

    use_case = ProcessWhatsAppMessageUseCase(
        ask_use_case=mock_ask,
        whatsapp_sender=mock_sender,
        transcriber=mock_transcriber,
        vision_analyzer=mock_vision,
    )

    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "22997112233",
                        "type": "audio",
                        "audio": {"id": "media-audio-123"},
                    }]
                }
            }]
        }]
    }

    mock_session = AsyncMock()
    result = await use_case.execute(session=mock_session, payload=payload)

    assert result["status"] == "processed"
    mock_transcriber.transcribe_bytes.assert_called_once()
    mock_ask.execute.assert_called_once()


@pytest.mark.asyncio
async def test_process_whatsapp_interactive_button_escalation():
    mock_ask = MagicMock()
    mock_sender = MagicMock()
    mock_sender.send_text_message = AsyncMock(return_value={"status": "sent"})
    mock_transcriber = MagicMock()
    mock_vision = MagicMock()

    use_case = ProcessWhatsAppMessageUseCase(
        ask_use_case=mock_ask,
        whatsapp_sender=mock_sender,
        transcriber=mock_transcriber,
        vision_analyzer=mock_vision,
    )

    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "22997112233",
                        "type": "interactive",
                        "interactive": {
                            "button_reply": {"id": "escalade_juriste", "title": "Parler à un juriste"}
                        },
                    }]
                }
            }]
        }]
    }

    mock_session = AsyncMock()
    result = await use_case.execute(session=mock_session, payload=payload)

    assert result["status"] == "escalation_acknowledged"
    mock_sender.send_text_message.assert_called_once()
