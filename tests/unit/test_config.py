from src.core.config import get_settings


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
