"""Tests unitaires pour le service d'observabilité LangfuseTracer."""

from unittest.mock import MagicMock, patch

from src.infrastructure.observability.langfuse_tracer import LangfuseTracer, get_langfuse_tracer


def test_langfuse_tracer_disabled_when_no_keys():
    """Vérifie que LangfuseTracer bascule en mode inactif si aucune clé n'est fournie."""
    with patch("src.infrastructure.observability.langfuse_tracer.get_settings") as mock_settings:
        mock_settings.return_value.LANGFUSE_PUBLIC_KEY = ""
        mock_settings.return_value.LANGFUSE_SECRET_KEY = ""
        tracer = LangfuseTracer()
        assert tracer.enabled is False
        assert tracer.client is None

        # Vérifie que les méthodes sont des no-ops sans lever d'erreur
        trace_id = tracer.create_trace(name="test_trace")
        assert trace_id is not None
        assert isinstance(trace_id, str)

        span = tracer.start_span(trace_id=trace_id, name="test_span")
        assert span is None

        tracer.end_span(span)
        tracer.record_feedback(trace_id=trace_id, rating=5)
        tracer.flush()


def test_langfuse_tracer_with_mock_client():
    """Vérifie le comportement de LangfuseTracer avec un client simulé."""
    mock_client = MagicMock()
    mock_client.create_trace_id.return_value = "trace-uuid-123"
    mock_span = MagicMock()
    mock_client.start_observation.return_value = mock_span

    tracer = LangfuseTracer(client=mock_client)
    assert tracer.enabled is True

    # Création de trace
    trace_id = tracer.create_trace(name="legal_rag", channel="whatsapp", metadata={"user": "abc"})
    assert trace_id == "trace-uuid-123"
    mock_client.create_event.assert_called_once()

    # Gestion de span
    span = tracer.start_span(trace_id=trace_id, name="retriever_step", span_type="retriever")
    assert span is mock_span
    tracer.end_span(span, outputs={"count": 3})
    mock_span.end.assert_called_once_with(output={"count": 3}, status_message=None)

    # Enregistrement de feedback
    tracer.record_feedback(trace_id=trace_id, rating=4, comment="Excellente réponse")
    mock_client.create_score.assert_called_once_with(
        trace_id=trace_id,
        name="citizen_satisfaction",
        value=4.0,
        comment="Excellente réponse",
    )

    # Flush
    tracer.flush()
    mock_client.flush.assert_called_once()


def test_langfuse_tracer_resilient_to_exceptions():
    """Vérifie que les erreurs internes de Langfuse ne se propagent jamais."""
    mock_client = MagicMock()
    mock_client.create_event.side_effect = RuntimeError("Langfuse timeout")
    mock_client.start_observation.side_effect = RuntimeError("Span error")
    mock_client.create_score.side_effect = RuntimeError("Score error")
    mock_client.flush.side_effect = RuntimeError("Flush error")

    tracer = LangfuseTracer(client=mock_client)

    # Ne doit lever aucune exception
    trace_id = tracer.create_trace()
    assert trace_id is not None

    span = tracer.start_span(trace_id=trace_id, name="faulty_span")
    assert span is None

    tracer.record_feedback(trace_id=trace_id, rating=1)
    tracer.flush()


def test_get_langfuse_tracer_singleton():
    """Vérifie que get_langfuse_tracer retourne une instance singleton."""
    t1 = get_langfuse_tracer()
    t2 = get_langfuse_tracer()
    assert t1 is t2
