from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEY = "super_secret_key_change_in_production_min_32_characters"
DEFAULT_WHATSAPP_APP_SECRET = "meta_app_secret_key_change_in_production"
DEFAULT_WHATSAPP_VERIFY_TOKEN = "lexbenin_webhook_verify_token"
DEFAULT_POSTGRES_PASSWORD = "lexbenin_secret_pass"


class Settings(BaseSettings):
    """Configuration centrale de l'application LEXBENIN."""

    model_config = SettingsConfigDict(
        # Le fichier rendu par Vault Agent (production) l'emporte sur .env (développement)
        env_file=(".env", "/vault/secrets/backend.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Général
    PROJECT_NAME: str = "LEXBENIN - Assistant Numérique Citoyen"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = DEFAULT_SECRET_KEY

    # Sécurité & exposition
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    ENABLE_API_DOCS: bool | None = None
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = ""
    ADMIN_API_KEY: str = ""
    PARTNER_API_KEY: str = ""

    # Base de données PostgreSQL
    POSTGRES_USER: str = "lexbenin"
    POSTGRES_PASSWORD: str = "lexbenin_secret_pass"
    POSTGRES_DB: str = "lexbenin_db"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str = (
        "postgresql+asyncpg://lexbenin:lexbenin_secret_pass@localhost:5432/lexbenin_db"
    )
    DATABASE_SYNC_URL: str = (
        "postgresql+psycopg2://lexbenin:lexbenin_secret_pass@localhost:5432/lexbenin_db"
    )
    # Supabase : pooler transactionnel (6543) incompatible avec les prepared statements asyncpg
    DATABASE_DISABLE_STATEMENT_CACHE: bool = False

    # Redis & File asynchrone
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_URL: str = "redis://localhost:6379/0"

    # Google Gemini (Free Tier Multi-Modèles)
    GEMINI_API_KEY: str = ""
    GEMINI_TEXT_MODEL: str = "gemini-4-hydrogen"
    GEMINI_FALLBACK_MODELS: str = (
        "gemini-4-hydrogen,gemini-3.8-flash,gemini-3.5-flash-lite,"
        "gemini-3.6-flash,gemini-3-flash-preview,gemini-2.5-flash-lite"
    )
    GEMINI_MODEL_COOLDOWN_SECONDS: int = 60
    GEMINI_EMBEDDING_MODEL: str = "text-embedding-004"
    EMBEDDING_DIMENSION: int = 768

    # Langfuse Observabilité
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_BASE_URL: str = "https://cloud.langfuse.com"

    # WhatsApp API
    WHATSAPP_VERIFY_TOKEN: str = "lexbenin_webhook_verify_token"
    WHATSAPP_APP_SECRET: str = "meta_app_secret_key_change_in_production"
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_API_VERSION: str = "v21.0"
    WHATSAPP_API_BASE_URL: str = "https://graph.facebook.com"

    # Multimodal & Médias
    MAX_MEDIA_SIZE_MB: int = 16
    TEMP_MEDIA_DIR: str = "/tmp"

    def get_cors_origins(self) -> list[str]:
        """Retourne la liste nettoyée des origines CORS autorisées."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def docs_enabled(self) -> bool:
        """Indique si Swagger/ReDoc sont exposés (désactivés par défaut en production)."""
        if self.ENABLE_API_DOCS is not None:
            return self.ENABLE_API_DOCS
        return self.ENVIRONMENT != "production"

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        """Refuse de démarrer en production avec des secrets par défaut ou une config ouverte."""
        if self.ENVIRONMENT != "production":
            return self
        problems: list[str] = []
        if self.SECRET_KEY == DEFAULT_SECRET_KEY or len(self.SECRET_KEY) < 32:
            problems.append("SECRET_KEY par défaut ou trop courte (<32)")
        if self.WHATSAPP_APP_SECRET == DEFAULT_WHATSAPP_APP_SECRET:
            problems.append("WHATSAPP_APP_SECRET par défaut")
        if self.WHATSAPP_VERIFY_TOKEN == DEFAULT_WHATSAPP_VERIFY_TOKEN:
            problems.append("WHATSAPP_VERIFY_TOKEN par défaut")
        if DEFAULT_POSTGRES_PASSWORD in self.DATABASE_URL:
            problems.append("mot de passe PostgreSQL par défaut dans DATABASE_URL")
        if not self.ADMIN_PASSWORD or len(self.ADMIN_PASSWORD) < 12:
            problems.append("ADMIN_PASSWORD absent ou trop court (<12)")
        if len(self.PARTNER_API_KEY) < 20:
            problems.append("PARTNER_API_KEY absente ou trop courte (<20)")
        if "*" in self.get_cors_origins():
            problems.append("CORS_ORIGINS ne doit pas contenir '*'")
        if problems:
            raise ValueError("Configuration production invalide : " + "; ".join(problems))
        return self

    def get_text_model_candidates(self) -> list[str]:
        """Retourne la chaîne ordonnée et dédupliquée des modèles Gemini texte/multimodal."""
        raw = [self.GEMINI_TEXT_MODEL, *self.GEMINI_FALLBACK_MODELS.split(",")]
        seen: set[str] = set()
        candidates: list[str] = []
        for item in raw:
            model = item.strip()
            if model and model not in seen:
                seen.add(model)
                candidates.append(model)
        return candidates


@lru_cache
def get_settings() -> Settings:
    return Settings()
