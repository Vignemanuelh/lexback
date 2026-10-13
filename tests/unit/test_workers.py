"""Tests unitaires pour les workers d'arrière-plan Arq et le traitement multimédia."""

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.workers.enqueue import (
    close_redis_pool,
    enqueue_tts_job,
    enqueue_whatsapp_media_job,
    get_redis_pool,
)
from src.infrastructure.workers.tasks import (
    cleanup_old_temp_files,
    generate_speech_tts,
    process_async_whatsapp_media,
)
from src.infrastructure.workers.worker import WorkerSettings, shutdown, startup


@pytest.mark.asyncio
async def test_process_async_whatsapp_media():
    """Vérifie l'exécution réussie de la tâche de traitement de média WhatsApp."""
    ctx = {}
    res = await process_async_whatsapp_media(
        ctx=ctx,
        user_phone_hash="hash_user_123",
        media_id="media_meta_456",
        media_type="audio",
        caption="Question vocale",
    )
    assert res["status"] == "success"
    assert res["user_hash"] == "hash_user_123"
    assert res["media_id"] == "media_meta_456"


@pytest.mark.asyncio
async def test_generate_speech_tts():
    """Vérifie la génération vocale TTS par le worker."""
    mock_synth = MagicMock()
    mock_synth.synthesize_speech = AsyncMock(return_value=b"RIFFfakeoggopusbytes")

    ctx = {"synthesizer": mock_synth}
    res = await generate_speech_tts(ctx=ctx, text="Explication juridique de l'article 552")
    assert res["status"] == "success"
    assert res["size_bytes"] == len(b"RIFFfakeoggopusbytes")
    assert res["format"] == "ogg"


@pytest.mark.asyncio
async def test_cleanup_old_temp_files(tmp_path):
    """Vérifie la purge périodique des fichiers orphelins selon RG-JUR7."""
    test_file = tmp_path / "lexbenin_old_123.ogg"
    test_file.write_bytes(b"test_audio")

    past_time = time.time() - 7200
    os.utime(str(test_file), (past_time, past_time))

    with patch("src.infrastructure.workers.tasks.settings.TEMP_MEDIA_DIR", str(tmp_path)):
        res = await cleanup_old_temp_files(_ctx={})
        assert res["cleaned_files"] >= 1
        assert not os.path.exists(str(test_file))


def test_worker_settings_configuration():
    """Vérifie que la configuration du worker respecte les spécifications Arq."""
    assert len(WorkerSettings.functions) == 3
    assert len(WorkerSettings.cron_jobs) == 1
    assert WorkerSettings.max_jobs == 10
    assert WorkerSettings.job_timeout == 300
    assert WorkerSettings.retry_jobs is True


@pytest.mark.asyncio
async def test_worker_lifecycle():
    """Vérifie les fonctions de démarrage et d'arrêt du worker."""
    ctx: dict = {}
    await startup(ctx)
    assert "synthesizer" in ctx
    await shutdown(ctx)


@pytest.mark.asyncio
async def test_enqueue_jobs_with_mock_pool():
    """Vérifie l'insertion de tâches dans la file Arq via le pool."""
    mock_pool = AsyncMock()
    mock_job = MagicMock()
    mock_job.job_id = "job_uuid_999"
    mock_pool.enqueue_job.return_value = mock_job

    job = await enqueue_whatsapp_media_job(
        user_phone_hash="hash_abc",
        media_id="media_xyz",
        media_type="image",
        caption="Analyse capture",
        pool=mock_pool,
    )
    assert job is mock_job
    mock_pool.enqueue_job.assert_called_once_with(
        "process_async_whatsapp_media",
        user_phone_hash="hash_abc",
        media_id="media_xyz",
        media_type="image",
        caption="Analyse capture",
    )

    mock_pool.reset_mock()
    job_tts = await enqueue_tts_job(text="Article 550", pool=mock_pool)
    assert job_tts is mock_job
    mock_pool.enqueue_job.assert_called_once_with(
        "generate_speech_tts",
        text="Article 550",
        output_format="ogg",
    )


@pytest.mark.asyncio
async def test_enqueue_jobs_fallback_when_redis_offline():
    """Vérifie que l'échec de connexion à Redis est géré gracieusement sans crash."""
    with patch("src.infrastructure.workers.enqueue.create_pool", side_effect=ConnectionError("Redis down")):
        await close_redis_pool()
        pool = await get_redis_pool()
        assert pool is None

        res1 = await enqueue_whatsapp_media_job("hash", "m1", "audio", pool=None)
        assert res1 is None

        res2 = await enqueue_tts_job("texte", pool=None)
        assert res2 is None
        await close_redis_pool()
