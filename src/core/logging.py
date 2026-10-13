import logging
import sys

import structlog

from src.core.config import get_settings

settings = get_settings()


def setup_logging() -> None:
    """Configure le logging structuré JSON avec structlog pour la production et le dev."""
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    # Configuration du logging standard Python
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Processeurs structlog pour enrichir les logs
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.ENVIRONMENT == "development":
        # Sortie colorée et lisible pour le développement local
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        # Sortie JSON stricte pour la production et l'observabilité
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Retourne une instance de BoundLogger pour le logging structuré."""
    return structlog.get_logger(name)
