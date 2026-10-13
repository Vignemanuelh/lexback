"""Configuration du Worker Arq pour le traitement asynchrone."""

from typing import Any, cast

import structlog
from arq import cron
from arq.connections import RedisSettings

from src.core.config import get_settings
from src.infrastructure.audio.synthesizer import SpeechSynthesizer
from src.infrastructure.workers.tasks import (
    cleanup_old_temp_files,
    generate_speech_tts,
    process_async_whatsapp_media,
)

logger = structlog.get_logger(__name__)
settings = get_settings()


async def startup(ctx: dict[str, Any]) -> None:
    """Initialise les ressources partagées du worker au démarrage."""
    logger.info("arq_worker_demarrage", redis_url=settings.REDIS_URL)
    ctx["synthesizer"] = SpeechSynthesizer()


async def shutdown(_ctx: dict[str, Any]) -> None:
    """Nettoie les connexions à l'arrêt du worker."""
    logger.info("arq_worker_arret")


class WorkerSettings:
    """Paramètres d'exécution du worker Arq."""

    functions = [
        process_async_whatsapp_media,
        generate_speech_tts,
        cleanup_old_temp_files,
    ]
    cron_jobs = [
        cron(cast(Any, cleanup_old_temp_files), hour=3, minute=0),
    ]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 10
    job_timeout = 300
    retry_jobs = True
    max_tries = 3
