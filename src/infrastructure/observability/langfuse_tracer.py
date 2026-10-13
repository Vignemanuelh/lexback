"""Service d'observabilité et de traçabilité pour le moteur RAG avec Langfuse.

Ce module capture les latences, la fidélité juridique et les évaluations citoyennes
tout en garantissant l'absence d'impact bloquant sur le flux applicatif.
"""

import uuid
from typing import Any

import structlog
from langfuse import Langfuse

from src.core.config import get_settings

logger = structlog.get_logger(__name__)


class LangfuseTracer:
    """Gestionnaire de traces et de métriques d'évaluation pour LEXBENIN."""

    def __init__(self, client: Langfuse | None = None) -> None:
        settings = get_settings()
        self.enabled = bool(
            settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY
        )
        self.client: Langfuse | None = None

        if client is not None:
            self.client = client
            self.enabled = True
        elif self.enabled:
            try:
                self.client = Langfuse(
                    public_key=settings.LANGFUSE_PUBLIC_KEY,
                    secret_key=settings.LANGFUSE_SECRET_KEY,
                    host=settings.LANGFUSE_BASE_URL,
                )
                logger.info(
                    "langfuse_initialise",
                    host=settings.LANGFUSE_BASE_URL,
                )
            except Exception as e:
                logger.warning(
                    "langfuse_initialisation_echouee",
                    erreur=str(e),
                )
                self.enabled = False

    def create_trace(
        self,
        name: str = "rag_legal_interaction",
        user_hash: str | None = None,
        channel: str = "web",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Génère un identifiant de trace et initialise le contexte."""
        if not self.enabled or not self.client:
            return str(uuid.uuid4())

        try:
            trace_id = self.client.create_trace_id()
            meta = metadata or {}
            meta.update({
                "channel": channel,
                "user_hash": user_hash or "anonymous",
            })
            self.client.create_event(
                name=f"{name}_start",
                metadata=meta,
            )
            return trace_id
        except Exception as e:
            logger.warning("langfuse_trace_creation_error", erreur=str(e))
            return str(uuid.uuid4())

    def start_span(
        self,
        trace_id: str,
        name: str,
        span_type: str = "span",
        inputs: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Démarre une observation ou span (retriever, generation, guardrail)."""
        if not self.enabled or not self.client:
            return None

        try:
            meta = metadata or {}
            if trace_id:
                meta["trace_id"] = trace_id
            client: Any = self.client
            return client.start_observation(
                name=name,
                as_type=span_type,
                input=inputs,
                metadata=meta,
            )
        except Exception as e:
            logger.warning("langfuse_start_span_error", span=name, erreur=str(e))
            return None

    def end_span(
        self,
        span: Any,
        outputs: Any = None,
        status_message: str | None = None,
    ) -> None:
        """Clôture une observation avec ses sorties."""
        if not self.enabled or span is None:
            return

        try:
            if hasattr(span, "end"):
                span.end(output=outputs, status_message=status_message)
        except Exception as e:
            logger.warning("langfuse_end_span_error", erreur=str(e))

    def record_feedback(
        self,
        trace_id: str,
        rating: int,
        comment: str | None = None,
    ) -> None:
        """Enregistre la note de satisfaction citoyenne dans Langfuse."""
        if not self.enabled or not self.client:
            return

        try:
            self.client.create_score(
                trace_id=trace_id,
                name="citizen_satisfaction",
                value=float(rating),
                comment=comment,
            )
            logger.info(
                "langfuse_feedback_enregistre",
                trace_id=trace_id,
                rating=rating,
            )
        except Exception as e:
            logger.warning("langfuse_record_feedback_error", erreur=str(e))

    def flush(self) -> None:
        """Vide le buffer d'événements vers le serveur Langfuse."""
        if not self.enabled or not self.client:
            return

        try:
            self.client.flush()
        except Exception as e:
            logger.warning("langfuse_flush_error", erreur=str(e))


_tracer_instance: LangfuseTracer | None = None


def get_langfuse_tracer() -> LangfuseTracer:
    """Retourne l'instance singleton du traceur Langfuse."""
    global _tracer_instance
    if _tracer_instance is None:
        _tracer_instance = LangfuseTracer()
    return _tracer_instance
