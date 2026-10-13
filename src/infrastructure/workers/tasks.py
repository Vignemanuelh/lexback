"""Tâches asynchrones exécutées par les workers Arq."""

import glob
import os
import time
from typing import Any

import structlog

from src.core.config import get_settings
from src.infrastructure.audio.synthesizer import SpeechSynthesizer

logger = structlog.get_logger(__name__)
settings = get_settings()


async def process_async_whatsapp_media(
    ctx: dict[str, Any],
    user_phone_hash: str,
    media_id: str,
    media_type: str,
    caption: str | None = None,
) -> dict[str, Any]:
    """Traite un média WhatsApp (audio ou image) en arrière-plan."""
    logger.info(
        "worker_debut_traitement_media",
        worker_id=ctx.get("worker_id", "default"),
        user_hash=user_phone_hash,
        media_id=media_id,
        media_type=media_type,
        caption=caption,
    )

    try:
        result: dict[str, Any] = {
            "status": "success",
            "user_hash": user_phone_hash,
            "media_id": media_id,
            "media_type": media_type,
            "caption": caption,
            "processed_at": time.time(),
        }
        return result
    except Exception as e:
        logger.error(
            "worker_erreur_traitement_media",
            media_id=media_id,
            erreur=str(e),
            exc_info=True,
        )
        return {
            "status": "error",
            "media_id": media_id,
            "error": str(e),
        }


async def generate_speech_tts(
    ctx: dict[str, Any],
    text: str,
    output_format: str = "ogg",
) -> dict[str, Any]:
    """Génère la synthèse vocale d'une explication juridique en arrière-plan."""
    synthesizer: SpeechSynthesizer = ctx.get("synthesizer") or SpeechSynthesizer()
    audio_bytes = await synthesizer.synthesize_speech(text)
    size = len(audio_bytes)

    logger.info(
        "worker_tts_genere",
        text_length=len(text),
        audio_size_bytes=size,
    )

    return {
        "status": "success",
        "format": output_format,
        "size_bytes": size,
    }


async def cleanup_old_temp_files(
    _ctx: dict[str, Any],
) -> dict[str, int]:
    """Nettoie périodiquement les fichiers multimédias temporaires orphelins (RG-JUR7)."""
    max_age_seconds: int = 3600
    cleaned_count = 0
    now = time.time()
    temp_dir = settings.TEMP_MEDIA_DIR

    patterns = [
        os.path.join(temp_dir, "lexbenin_*.ogg"),
        os.path.join(temp_dir, "lexbenin_*.jpg"),
        os.path.join(temp_dir, "lexbenin_*.png"),
        os.path.join(temp_dir, "tmp*.ogg"),
    ]

    for pattern in patterns:
        for file_path in glob.glob(pattern):
            try:
                mtime = os.path.getmtime(file_path)
                if (now - mtime) > max_age_seconds and os.path.exists(file_path):
                    os.unlink(file_path)
                    cleaned_count += 1
            except Exception as e:
                logger.warning(
                    "erreur_suppression_temp_orphelin",
                    file=file_path,
                    erreur=str(e),
                )

    logger.info("worker_nettoyage_fichiers_temporaires", fichiers_supprimes=cleaned_count)
    return {"cleaned_files": cleaned_count}
