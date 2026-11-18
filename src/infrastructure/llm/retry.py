import asyncio
import logging
import time
from collections.abc import Callable, Sequence

logger = logging.getLogger(__name__)

TRANSIENT_ERROR_MARKERS = ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded")
FALLBACK_ERROR_MARKERS = (
    *TRANSIENT_ERROR_MARKERS,
    "404",
    "NOT_FOUND",
    "quota",
    "Quota",
    "rate limit",
    "RATE_LIMIT",
)

_MODEL_COOLDOWN_UNTIL: dict[str, float] = {}


def clear_model_cooldowns() -> None:
    """Réinitialise le registre de cooldown des modèles Gemini (utile pour les tests)."""
    _MODEL_COOLDOWN_UNTIL.clear()


def is_transient_genai_error(exc: Exception) -> bool:
    """Détecte les erreurs transitoires réseau ou de capacité de l'API Gemini."""
    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if status_code in (429, 500, 502, 503, 504):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    message = str(exc)
    return any(marker in message for marker in TRANSIENT_ERROR_MARKERS)


def is_fallback_eligible_error(exc: Exception) -> bool:
    """Détecte si une erreur justifie une bascule immédiate vers le modèle Gemini suivant."""
    if is_transient_genai_error(exc):
        return True
    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if status_code == 404:
        return True
    message = str(exc)
    return any(marker in message for marker in FALLBACK_ERROR_MARKERS)


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


async def run_gemini_with_fallback[T](
    call_for_model: Callable[[str], T],
    models: Sequence[str],
    cooldown_seconds: int = 60,
) -> tuple[T, str]:
    """Exécute un appel Gemini en basculant automatiquement sur la liste de modèles de repli."""
    if not models:
        raise ValueError("La liste des modèles Gemini candidats ne peut pas être vide.")

    now = time.monotonic()
    active_models = [m for m in models if _MODEL_COOLDOWN_UNTIL.get(m, 0.0) <= now]
    ordered_candidates = active_models if active_models else list(models)

    last_exc: Exception | None = None
    for idx, model_name in enumerate(ordered_candidates):
        try:
            result = await asyncio.to_thread(call_for_model, model_name)
            _MODEL_COOLDOWN_UNTIL.pop(model_name, None)
            return result, model_name
        except Exception as exc:
            last_exc = exc
            if not is_fallback_eligible_error(exc):
                raise
            if cooldown_seconds > 0:
                _MODEL_COOLDOWN_UNTIL[model_name] = time.monotonic() + cooldown_seconds
            if idx + 1 < len(ordered_candidates):
                next_model = ordered_candidates[idx + 1]
                logger.warning(
                    "Bascule modèle Gemini : %s indisponible/saturé (%s) -> essai %s",
                    model_name,
                    exc,
                    next_model,
                )

    assert last_exc is not None
    raise last_exc
