import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.mark.asyncio
async def test_health_check():
    """Vérifie le point d'accès /health via transport ASGI."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "service" in data


@pytest.mark.asyncio
async def test_faq_endpoint():
    """Vérifie le point d'accès /api/v1/legal/faq via transport ASGI."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/legal/faq")
    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)
    assert len(items) >= 3
    assert "question" in items[0]
    assert "statut_legal" in items[0]


@pytest.mark.asyncio
async def test_admin_corpus_upload_invalid_extension():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        files = {"file": ("code.txt", b"plain text content", "text/plain")}
        res = await ac.post("/api/v1/legal/admin/corpus/upload", files=files)
    assert res.status_code == 400
    assert "Seuls les fichiers .json" in res.json()["detail"]


@pytest.mark.asyncio
async def test_admin_corpus_upload_valid_json():
    import uuid
    from unittest.mock import AsyncMock, patch

    from src.application.use_cases.ingest_law import IngestionReport

    mock_report = IngestionReport(
        law_version_id=uuid.uuid4(),
        code_name="Code du numérique",
        official_reference="Loi 2017-20",
        total_articles=5,
        created_articles=5,
        updated_articles=0,
        total_structures=2,
        created_structures=2,
        embeddings_computed=0,
    )

    with patch(
        "src.application.use_cases.ingest_law.IngestLawUseCase.ingest_from_json",
        new_callable=AsyncMock,
        return_value=mock_report,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            files = {"file": ("code.json", b'{"metadata": {}, "structures": []}', "application/json")}
            res = await ac.post("/api/v1/legal/admin/corpus/upload", files=files)

        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["total_articles"] == 5
        assert data["created_articles"] == 5

