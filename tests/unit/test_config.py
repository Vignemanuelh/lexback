from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.config import get_settings
from src.core.database import Base, init_db


def test_settings_defaults():
    """Vérifie les paramètres par défaut de l'application."""
    settings = get_settings()
    assert settings.PROJECT_NAME == "LEXBENIN - Assistant Numérique Citoyen"
    assert settings.EMBEDDING_DIMENSION == 768
    assert settings.POSTGRES_PORT == 5432
    assert "postgresql" in settings.DATABASE_URL
    assert settings.ENVIRONMENT in ["development", "staging", "production"]


def test_settings_lru_cache():
    """Vérifie que get_settings retourne une instance mise en cache."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


@pytest.mark.asyncio
async def test_init_db_registers_entities_and_creates_tables():
    """Vérifie que init_db enregistre toutes les tables métier avant create_all."""
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()
    mock_conn.run_sync = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("src.core.database.async_engine") as mock_engine:
        mock_engine.begin.return_value = mock_ctx
        await init_db()

    mock_conn.execute.assert_awaited_once()
    mock_conn.run_sync.assert_awaited_once()
    for table in ("law_versions", "legal_articles", "article_embeddings", "citizen_interactions"):
        assert table in Base.metadata.tables
