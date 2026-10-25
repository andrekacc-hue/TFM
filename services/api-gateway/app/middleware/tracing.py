"""Trazabilidad: ``X-Trace-Id`` de extremo a extremo.

El gateway es el origen de la traza: reutiliza el ``X-Trace-Id`` del cliente si es válido o
genera uno nuevo (``RequestContextMiddleware``), lo añade a cada log y lo propaga a los
servicios internos. Así una consulta del portal puede seguirse en los logs del gateway, del
rag-service y en la fila de ``tfm.queries`` (columna ``trace_id``).
"""

from __future__ import annotations

from shared.logging import get_trace_id
from shared.middleware import TRACE_HEADER, RequestContextMiddleware

__all__ = ["TRACE_HEADER", "RequestContextMiddleware", "downstream_trace_headers"]


def downstream_trace_headers() -> dict[str, str]:
    """Cabeceras de traza a propagar a los servicios internos."""
    trace_id = get_trace_id()
    return {"X-Trace-Id": trace_id} if trace_id else {}
