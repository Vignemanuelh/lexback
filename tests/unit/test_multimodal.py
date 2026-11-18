import json
from unittest.mock import MagicMock

import pytest

from src.infrastructure.audio.synthesizer import SpeechSynthesizer
from src.infrastructure.audio.transcriber import AudioTranscriber
from src.infrastructure.vision.analyzer import VisionAnalyzer


@pytest.mark.asyncio
async def test_audio_transcriber_file_not_found():
    transcriber = AudioTranscriber()
    with pytest.raises(FileNotFoundError):
        await transcriber.transcribe_file("/tmp/non_existent_file_12345.ogg")


@pytest.mark.asyncio
async def test_audio_transcriber_simulation_mode():
    transcriber = AudioTranscriber(gemini_api_key=None)
    transcriber.client = None

    text = await transcriber.transcribe_bytes(b"dummy_bytes", suffix=".ogg")
    assert "Transcription vocale simulée" in text


@pytest.mark.asyncio
async def test_audio_transcriber_with_client():
    transcriber = AudioTranscriber(gemini_api_key="fake-key")
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "Puis-je diffuser une photo sans consentement ?"
    mock_client.models.generate_content.return_value = mock_resp
    transcriber.client = mock_client

    text = await transcriber.transcribe_bytes(b"fake_audio_bytes", suffix=".ogg")
    assert text == "Puis-je diffuser une photo sans consentement ?"
    mock_client.models.generate_content.assert_called_once()


@pytest.mark.asyncio
async def test_vision_analyzer_file_not_found():
    analyzer = VisionAnalyzer()
    with pytest.raises(FileNotFoundError):
        await analyzer.analyze_image_file("/tmp/non_existent_img_999.jpg")


@pytest.mark.asyncio
async def test_vision_analyzer_simulation_mode():
    analyzer = VisionAnalyzer(gemini_api_key=None)
    analyzer.client = None

    result = await analyzer.analyze_image_bytes(b"dummy_img_bytes", suffix=".jpg")
    assert "extracted_text" in result
    assert "formulated_question" in result
    assert "WhatsApp" in result["extracted_text"]


@pytest.mark.asyncio
async def test_vision_analyzer_with_client():
    analyzer = VisionAnalyzer(gemini_api_key="fake-key")
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = json.dumps({
        "extracted_text": "Faux profil détecté",
        "context": "Capture écran Instagram",
        "formulated_question": "Est-ce une usurpation d'identité ?",
    })
    mock_client.models.generate_content.return_value = mock_resp
    analyzer.client = mock_client

    result = await analyzer.analyze_image_bytes(b"fake_image_bytes", suffix=".png")
    assert result["extracted_text"] == "Faux profil détecté"
    assert result["formulated_question"] == "Est-ce une usurpation d'identité ?"


@pytest.mark.asyncio
async def test_speech_synthesizer_nominal():
    synth = SpeechSynthesizer()
    audio = await synth.synthesize_speech("Bonjour citoyen béninois")
    assert len(audio) > 0
    assert audio.startswith(b"OggS")

    empty_audio = await synth.synthesize_speech("")
    assert empty_audio == b""


@pytest.mark.asyncio
async def test_audio_transcriber_webm_mime_type():
    transcriber = AudioTranscriber(gemini_api_key="fake-key")
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "Est-ce légal ?"
    mock_client.models.generate_content.return_value = mock_resp
    transcriber.client = mock_client

    text = await transcriber.transcribe_bytes(b"webm_audio_bytes", suffix=".webm")
    assert text == "Est-ce légal ?"
    contents = mock_client.models.generate_content.call_args.kwargs["contents"]
    assert contents[0].inline_data.mime_type == "audio/webm"


@pytest.mark.asyncio
async def test_vision_analyzer_fenced_json_and_503_retry():
    from unittest.mock import AsyncMock, patch

    analyzer = VisionAnalyzer(gemini_api_key="fake-key")
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = '```json\n{"extracted_text": "Menace SMS", "formulated_question": "Est-ce du chantage ?"}\n```'
    mock_client.models.generate_content.side_effect = [
        RuntimeError("503 UNAVAILABLE"),
        mock_resp,
    ]
    analyzer.client = mock_client

    with patch("src.infrastructure.llm.retry.asyncio.sleep", new_callable=AsyncMock):
        result = await analyzer.analyze_image_bytes(b"img", suffix=".png")

    assert result["extracted_text"] == "Menace SMS"
    assert result["formulated_question"] == "Est-ce du chantage ?"
    assert mock_client.models.generate_content.call_count == 2
