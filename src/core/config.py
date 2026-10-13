from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration centrale de l'application LEXBENIN."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Général
    PROJECT_NAME: str = "LEXBENIN - Assistant Numérique Citoyen"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "super_secret_key_change_in_production_min_32_characters"

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
        "postgresql://lexbenin:lexbenin_secret_pass@localhost:5432/lexbenin_db"
    )

    # Redis & File asynchrone
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_URL: str = "redis://localhost:6379/0"

    # Google Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_TEXT_MODEL: str = "gemini-2.0-flash"
    GEMINI_EMBEDDING_MODEL: str = "text-embedding-004"
    EMBEDDING_DIMENSION: int = 768

    # Langfuse Observabilité
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_BASE_URL: str = "https://cloud.langfuse.com"

    # WhatsApp API
    WHATSAPP_VERIFY_TOKEN: str = "lexbenin_webhook_verify_token"
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_API_VERSION: str = "v21.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
