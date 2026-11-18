import asyncio
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

TRANSIENT_ERROR_MARKERS = ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded")


def is_transient_genai_error(exc: Exception) -> bool:
    """Détecte les erreurs transitoires réseau ou de capacité de l'API Gemini."""
    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if status_code in (429, 500, 502, 503, 504):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    message = str(exc)
    return any(marker in message for marker in TRANSIENT_ERROR_MARKERS)


async def run_gemini_with_retry[T](
    func: Callable[[], T],
    max_attempts: int = 3,
    base_delay_seconds: float = 0.6,
) -> T:
    """Exécute un appel synchrone Google GenAI dans un thread dédié avec backoff sur 503/429."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await asyncio.to_thread(func)
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not is_transient_genai_error(exc):
                raise
            delay = base_delay_seconds * attempt
            logger.warning(
                "Erreur transitoire Gemini (tentative %s/%s), nouvelle tentative dans %.1fs : %s",
                attempt,
                max_attempts,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
