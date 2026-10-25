"""Trazas distribuidas con OpenTelemetry (opcional).

Con ``ENABLE_TRACING=true`` cada servicio exporta sus spans por OTLP/HTTP a Jaeger
(``docker compose --profile observability up -d jaeger`` → http://localhost:16686):

    api-gateway  POST /api/v1/query
    └─ httpx POST rag-service/v1/query          (propagación W3C traceparent)
       └─ rag-service POST /v1/query
          ├─ rag.guardrails / rag.retrieval / rag.rerank / rag.generation
          └─ httpx → Supabase, Ollama

Sin la variable, o sin los paquetes de ``shared[otel]``, todo es un no-op: los servicios
no dependen de OpenTelemetry para funcionar.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from shared.logging import get_logger, get_trace_id

logger = get_logger(__name__)

_tracer: Any = None


def setup_tracing(app: Any, service_name: str, *, enabled: bool, endpoint: str) -> bool:
    """Instrumenta FastAPI y httpx y registra el exportador OTLP.

    Returns:
        ``True`` si la instrumentación quedó activa.
    """
    global _tracer
    if not enabled:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("otel_unavailable", hint="pip install soporte-shared[otel]")
        return False

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, excluded_urls="health,ready")
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    _tracer = trace.get_tracer(service_name)
    logger.info("otel_enabled", endpoint=endpoint)
    return True


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[None]:
    """Span hijo con el ``trace_id`` de los logs como atributo (une logs y trazas)."""
    if _tracer is None:
        yield
        return
    with _tracer.start_as_current_span(name) as current:
        current.set_attribute("app.trace_id", get_trace_id() or "")
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        yield
