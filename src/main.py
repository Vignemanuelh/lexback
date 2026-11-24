import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqladmin import Admin
from sqlalchemy import text

from src.core.config import get_settings
from src.core.database import async_engine, sync_engine
from src.core.logging import setup_logging
from src.presentation.admin.views import (
    CitizenInteractionAdmin,
    LawVersionAdmin,
    LegalArticleAdmin,
    LegalEscalationAdmin,
    LegalStructureAdmin,
)
from src.presentation.api.v1.router import router as legal_router
from src.presentation.api.v1.whatsapp_webhook import router as whatsapp_router
from src.presentation.security import AdminAuth

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("lexbenin")
settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Cycle de vie de l'application FastAPI (démarrage et extinction)."""
    setup_logging()
    logger.info("Démarrage du service LEXBENIN - Assistant Numérique Citoyen...")
    # Vérification ou initialisation de ressources au démarrage
    yield
    logger.info("Extinction du service LEXBENIN...")
    await async_engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=(
        "Moteur IA RAG & API pour l'Assistant Numérique Citoyen "
        "sur le Code du numérique béninois."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

# Configuration CORS pour autoriser le portail citoyen Next.js
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

# Inclusion des routes API
app.include_router(legal_router, prefix=settings.API_V1_STR)
app.include_router(whatsapp_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["Santé"])
async def health_check():
    """Vérification de la disponibilité du service."""
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
    }


@app.get("/health/ready", tags=["Santé"])
async def readiness_check(response: Response):
    """Vérifie la disponibilité effective de la base de données (readiness)."""
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        logger.error("readiness_db_indisponible", exc_info=True)
        response.status_code = 503
        return {"status": "unavailable", "database": "down", "erreur": type(exc).__name__}
    return {"status": "ready", "database": "up"}


# Montage du panneau d'administration SQLAdmin
admin = Admin(
    app=app,
    engine=sync_engine,
    title="LEXBENIN Juriste & Admin",
    base_url="/admin",
    authentication_backend=AdminAuth(secret_key=settings.SECRET_KEY),
)

admin.add_view(LawVersionAdmin)
admin.add_view(LegalStructureAdmin)
admin.add_view(LegalArticleAdmin)
admin.add_view(CitizenInteractionAdmin)
admin.add_view(LegalEscalationAdmin)
