"""Jerarquía de excepciones de dominio y su traducción a respuestas HTTP."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from shared.logging import get_logger, get_trace_id

logger = get_logger(__name__)


class AppError(Exception):
    """Error base de la aplicación.

    Attributes:
        message: Mensaje legible (en español) para el cliente.
        code: Código estable, apto para que el frontend lo interprete.
        status_code: Código HTTP asociado.
        details: Información adicional opcional (sin datos sensibles).
    """

    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}


class ValidationAppError(AppError):
    """Datos de entrada inválidos."""

    status_code = 422
    code = "validation_error"


class AuthenticationError(AppError):
    """Credenciales ausentes o inválidas."""

    status_code = 401
    code = "unauthenticated"


class AuthorizationError(AppError):
    """El usuario no tiene permiso para la operación."""

    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    """Recurso inexistente o no visible para el usuario."""

    status_code = 404
    code = "not_found"


class UpstreamServiceError(AppError):
    """Fallo de una dependencia externa (Supabase, Redis, otro microservicio)."""

    status_code = 502
    code = "upstream_error"


class LLMProviderError(UpstreamServiceError):
    """Fallo del proveedor de LLM (Ollama, Claude, OpenAI)."""

    code = "llm_provider_error"


def _error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message, "trace_id": get_trace_id()}}
    if details:
        body["error"]["details"] = details
    return body


def register_exception_handlers(app: FastAPI) -> None:
    """Registra manejadores que devuelven errores con formato homogéneo.

    Formato: ``{"error": {"code", "message", "trace_id", "details?"}}``.

    Args:
        app: Aplicación FastAPI.
    """

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        log = logger.warning if exc.status_code < 500 else logger.error
        log("app_error", code=exc.code, status=exc.status_code, error=exc.message, details=exc.details)
        return JSONResponse(status_code=exc.status_code, content=_error_body(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(err.get("loc", [])), "msg": err.get("msg", "")} for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_error_body("validation_error", "Solicitud inválida", {"errors": errors}),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=_error_body("internal_error", "Error interno del servicio"),
        )
