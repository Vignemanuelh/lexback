from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.core.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    """Classe de base pour tous les modèles SQLAlchemy."""

    pass


# Moteur asynchrone pour les opérations API et RAG
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    pool_size=10,
    max_overflow=20,
)

# Fabrique de sessions asynchrones
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Moteur synchrone pour SQLAdmin et les scripts de migration
sync_engine = create_engine(
    settings.DATABASE_SYNC_URL,
    echo=False,
    pool_pre_ping=True,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dépendance FastAPI pour obtenir une session de base de données asynchrone."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
