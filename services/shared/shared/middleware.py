"""Middleware ASGI de contexto de petición: ``trace_id`` y log de acceso."""

from __future__ import annotations

import re
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from shared.logging import bind_trace_id, clear_context, get_logger, new_trace_id

TRACE_HEADER = "x-trace-id"
_VALID_TRACE = re.compile(r"^[A-Za-z0-9\-_.]{8,64}$")

logger = get_logger("http")


class RequestContextMiddleware:
    """Propaga ``X-Trace-Id`` entre servicios y registra cada petición.

    Si la petición trae ``X-Trace-Id`` (o ``X-Request-Id``) válido se reutiliza; si no, se
    genera uno nuevo. El valor se devuelve en la cabecera ``X-Trace-Id`` de la respuesta.
    """

    def __init__(self, app: ASGIApp, *, skip_paths: tuple[str, ...] = ("/health",)) -> None:
        self.app = app
        self.skip_paths = skip_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        incoming = headers.get(TRACE_HEADER) or headers.get("x-request-id")
        trace_id = incoming if incoming and _VALID_TRACE.match(incoming) else new_trace_id()
        bind_trace_id(trace_id)

        started = time.perf_counter()
        status_code = 500

        async def send_with_trace(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((TRACE_HEADER.encode(), trace_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace)
        finally:
            path = scope.get("path", "")
            if path not in self.skip_paths:
                logger.info(
                    "http_request",
                    method=scope.get("method"),
                    path=path,
                    status=status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )
            clear_context()
