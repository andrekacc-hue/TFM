"""Logging estructurado con structlog y propagación de ``trace_id``.

Todos los eventos incluyen ``service`` y, dentro de una petición, ``trace_id`` (vía
``contextvars``), de modo que una consulta puede seguirse entre gateway, rag-service y
analytics-service.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

import structlog

_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)


def new_trace_id() -> str:
    """Genera un identificador de traza (32 hex, compatible con W3C trace-id)."""
    return uuid.uuid4().hex


def get_trace_id() -> str | None:
    """Devuelve el ``trace_id`` de la petición en curso, si existe."""
    return _trace_id.get()


def bind_trace_id(trace_id: str) -> None:
    """Asocia ``trace_id`` al contexto actual (logs y respuestas)."""
    _trace_id.set(trace_id)
    structlog.contextvars.bind_contextvars(trace_id=trace_id)


def clear_context() -> None:
    """Limpia el contexto de logging al terminar una petición."""
    _trace_id.set(None)
    structlog.contextvars.clear_contextvars()


def configure_logging(service_name: str, level: str = "INFO", fmt: str = "json") -> None:
    """Configura structlog y el logging estándar de Python.

    Args:
        service_name: Nombre del servicio, añadido a cada evento.
        level: Nivel mínimo (DEBUG, INFO, WARNING, ERROR).
        fmt: ``json`` para producción o ``console`` para desarrollo.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    def add_service(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event_dict.setdefault("service", service_name)
        return event_dict

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_service,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)

    # Librerías ruidosas
    for noisy in ("httpx", "httpcore", "urllib3", "sentence_transformers", "filelock"):
        logging.getLogger(noisy).setLevel(max(log_level, logging.WARNING))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Obtiene un logger estructurado."""
    return structlog.get_logger(name)
