"""Trazas OpenTelemetry: desactivadas por defecto y sin efecto en el código instrumentado."""

from fastapi import FastAPI

from shared import telemetry


def test_disabled_tracing_is_a_noop():
    assert telemetry.setup_tracing(FastAPI(), "test", enabled=False, endpoint="http://x") is False
    with telemetry.span("rag.retrieval", **{"rag.top_k": 20}):
        value = 42
    assert value == 42


def test_spans_are_recorded_when_enabled(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "_tracer", provider.get_tracer("test"))

    with telemetry.span("rag.generation", **{"rag.chunks": 5, "ignorado": None}):
        pass

    [recorded] = exporter.get_finished_spans()
    assert recorded.name == "rag.generation"
    assert recorded.attributes["rag.chunks"] == 5
    assert "ignorado" not in recorded.attributes
