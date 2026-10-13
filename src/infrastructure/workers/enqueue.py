"""Fonctions utilitaires pour l'insertion de tâches dans les files Arq / Redis."""

import contextlib
from typing import Any

import structlog
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from src.core.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

_redis_pool: ArqRedis | None = None


async def get_redis_pool() -> ArqRedis | None:
    """Récupère ou initialise le pool de connexions Redis pour Arq."""
    global _redis_pool
    if _redis_pool is None:
        try:
            _redis_pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
            logger.info("arq_pool_redis_connecte", redis_url=settings.REDIS_URL)
        except Exception as e:
            logger.warning("arq_pool_redis_inaccessible", erreur=str(e))
            return None
    return _redis_pool


async def close_redis_pool() -> None:
    """Ferme proprement le pool de connexions Redis."""
    global _redis_pool
    if _redis_pool is not None:
        with contextlib.suppress(Exception):
            await _redis_pool.close()
        _redis_pool = None


async def enqueue_whatsapp_media_job(
    user_phone_hash: str,
    media_id: str,
    media_type: str,
    caption: str | None = None,
    pool: ArqRedis | None = None,
) -> Any:
    """Enfile une tâche de traitement média dans Redis Arq."""
    redis = pool or await get_redis_pool()
    if not redis:
        logger.warning(
            "job_non_enfile_redis_hors_ligne",
            media_id=media_id,
        )
        return None

    try:
        job = await redis.enqueue_job(
            "process_async_whatsapp_media",
            user_phone_hash=user_phone_hash,
            media_id=media_id,
            media_type=media_type,
            caption=caption,
        )
        logger.info(
            "job_media_enfile",
            job_id=job.job_id if job else None,
            media_id=media_id,
        )
        return job
    except Exception as e:
        logger.error("erreur_enfilement_job_media", erreur=str(e), exc_info=True)
        return None


async def enqueue_tts_job(
    text: str,
    output_format: str = "ogg",
    pool: ArqRedis | None = None,
) -> Any:
    """Enfile une tâche de synthèse vocale TTS dans Redis Arq."""
    redis = pool or await get_redis_pool()
    if not redis:
        return None

    try:
        job = await redis.enqueue_job(
            "generate_speech_tts",
            text=text,
            output_format=output_format,
        )
        return job
    except Exception as e:
        logger.error("erreur_enfilement_job_tts", erreur=str(e))
        return None
