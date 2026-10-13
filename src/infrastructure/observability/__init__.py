"""Module d'observabilité et de monitoring pour LEXBENIN."""
from src.infrastructure.observability.langfuse_tracer import LangfuseTracer, get_langfuse_tracer

__all__ = ["LangfuseTracer", "get_langfuse_tracer"]
