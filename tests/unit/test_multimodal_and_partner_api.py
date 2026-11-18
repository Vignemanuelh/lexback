import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.core.database import get_db_session
from src.domain.schemas.rag import LegalArticleCitation, LegalQuestionResponse, LegalStatus
from src.main import app


@pytest.fixture(autouse=True)
def override_db():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar.return_value = 5
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.get = AsyncMock(return_value=None)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    app.dependency_overrides[get_db_session] = lambda: mock_session
    yield mock_session
    app.dependency_overrides.pop(get_db_session, None)


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_whisper")
async def test_ask_multimodal_audio():
    """Vérifie l'endpoint multimodal avec un fichier audio simulé."""
    dummy_resp = LegalQuestionResponse(
        interaction_id="uuid-multi-1",
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
            dummy_audio = io.BytesIO(b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00dummy_audio_bytes")
            files = {"file": ("note_vocale.ogg", dummy_audio, "audio/ogg")}
            data = {"channel": "WEB", "user_id": "citizen_test"}
            res = await ac.post("/api/v1/legal/ask/multimodal", files=files, data=data)

        assert res.status_code == 200
        resp_data = res.json()
        assert "statut_legal" in resp_data
        assert resp_data["detected_media_type"] == "audio"
        assert "explication_vulgarisee" in resp_data
        assert "articles_cites" in resp_data


@pytest.mark.asyncio
async def test_ask_multimodal_image():
    """Vérifie l'endpoint multimodal avec une capture d'écran simulée."""
    dummy_resp = LegalQuestionResponse(
        interaction_id="uuid-multi-2",
        statut_legal=LegalStatus.A_RISQUE,
        articles_cites=["Article 558"],
        explication_vulgarisee="L'usurpation d'identité en ligne présente un risque pénal majeur.",
        conseil_pratique="Signalez le profil immédiatement.",
        avertissement_legal="Outil de vulgarisation.",
        necessite_escalade=True,
        sources=[],
    )

    with (
        patch(
            "src.infrastructure.vision.analyzer.VisionAnalyzer.analyze_image_file",
            new_callable=AsyncMock,
        ) as mock_analyze,
        patch(
            "src.presentation.api.v1.router.AskLegalQuestionUseCase.execute",
            new_callable=AsyncMock,
        ) as mock_exec,
    ):
        mock_analyze.return_value = {
            "extracted_text": "Compte piraté demandant de l'argent",
            "context": "Capture WhatsApp",
            "contains_identifiable_person": True,
            "is_potential_ai_or_manipulated": False,
            "formulated_question": "Un compte WhatsApp piraté extorque de l'argent.",
        }
        mock_exec.return_value = dummy_resp

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            dummy_image = io.BytesIO(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRdummy_png_bytes")
            files = {"file": ("capture.png", dummy_image, "image/png")}
            data = {"text_prompt": "Est-ce légal selon le code du numérique ?", "channel": "WEB"}
            res = await ac.post("/api/v1/legal/ask/multimodal", files=files, data=data)

        assert res.status_code == 200
        resp_data = res.json()
        assert "statut_legal" in resp_data
        assert resp_data["detected_media_type"] == "image"
        assert "explication_vulgarisee" in resp_data


@pytest.mark.asyncio
async def test_ask_multimodal_unsupported_format():
    """Vérifie le rejet HTTP 400 d'un format binaire non supporté."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        dummy_file = io.BytesIO(b"binary_executable_data")
        files = {"file": ("script.sh", dummy_file, "application/x-sh")}
        res = await ac.post("/api/v1/legal/ask/multimodal", files=files)

    assert res.status_code == 400
    assert "Format de fichier non pris en charge" in res.json()["detail"]


@pytest.mark.asyncio
async def test_partner_escalations_list():
    """Vérifie la récupération de la file d'attente citoyenne pour les juristes."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/legal/partner/escalations")

    assert res.status_code == 200
    items = res.json()
    assert isinstance(items, list)
    assert len(items) >= 1
    assert "reference_number" in items[0]
    assert "question_summary" in items[0]
    assert "status" in items[0]


@pytest.mark.asyncio
async def test_partner_escalations_filter_by_status():
    """Vérifie le filtrage par statut dans la file partenaire."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/legal/partner/escalations?status_filter=PENDING")

    assert res.status_code == 200
    items = res.json()
    for item in items:
        assert item["status"] == "PENDING"


@pytest.mark.asyncio
async def test_partner_escalations_patch():
    """Vérifie la mise à jour d'un dossier par le juriste référent."""
    transport = ASGITransport(app=app)
    demo_id = "e0a1b2c3-d4e5-4a6b-8c7d-9e0f1a2b3c4d"
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "status": "IN_REVIEW",
            "assigned_jurist": "Me Karen Houndété",
            "jurist_response": "Dossier pris en charge pour orientation Barreau.",
        }
        res = await ac.patch(f"/api/v1/legal/partner/escalations/{demo_id}", json=payload)

    assert res.status_code == 200
    updated = res.json()
    assert updated["status"] == "IN_REVIEW"
    assert updated["assigned_jurist"] == "Me Karen Houndété"


@pytest.mark.asyncio
async def test_partner_metrics():
    """Vérifie les métriques conventionnées d'audit et performance."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/legal/partner/metrics")

    assert res.status_code == 200
    data = res.json()
    assert data["accuracy_rate"] >= 95.0
    assert data["citation_verification_rate"] >= 99.0
    assert data["total_indexed_articles"] == 646
    assert data["apdp_encrypted"] is True


@pytest.mark.asyncio
async def test_partner_endpoints_survive_transient_db_error():
    """Vérifie la résilience CORS/200 des endpoints partenaire en cas d'erreur SQLAlchemy."""
    from sqlalchemy.exc import OperationalError

    failing_session = AsyncMock()
    failing_session.execute = AsyncMock(
        side_effect=OperationalError("SELECT 1", {}, Exception("connection closed"))
    )
    app.dependency_overrides[get_db_session] = lambda: failing_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            metrics_res = await ac.get("/api/v1/legal/partner/metrics")
            esc_res = await ac.get("/api/v1/legal/partner/escalations")

        assert metrics_res.status_code == 200
        assert metrics_res.json()["sla_average_hours"] == 4.25
        assert metrics_res.json()["pending_audits_count"] == 12
        assert esc_res.status_code == 200
        assert isinstance(esc_res.json(), list)
    finally:
        app.dependency_overrides.pop(get_db_session, None)
