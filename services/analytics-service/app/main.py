"""Aplicación FastAPI del analytics-service.

Ejecutar en desarrollo (desde services/analytics-service):
    uvicorn app.main:create_app --factory --port 8003
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import __version__
from app.config import AnalyticsSettings, get_settings
from app.dependencies import Container, ContainerDep, build_container
from app.routes import metrics, reports
from shared.exceptions import register_exception_handlers
from shared.logging import configure_logging
from shared.middleware import RequestContextMiddleware
from shared.schemas import HealthResponse
from shared.telemetry import setup_tracing


def create_app(
    settings: AnalyticsSettings | None = None,
    container_factory: Callable[[AnalyticsSettings], Container] = build_container,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container_factory(settings)
        try:
            yield
        finally:
            await app.state.container.aclose()

    app = FastAPI(
        title="analytics-service",
        version=__version__,
        description="Métricas de uso, latencia, abstención y satisfacción del asistente; exportación de reportes.",
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    setup_tracing(app, settings.service_name, enabled=settings.enable_tracing, endpoint=settings.jaeger_endpoint)
    register_exception_handlers(app)
    app.include_router(metrics.router)
    app.include_router(reports.router)

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service=settings.service_name, version=__version__)

    @app.get("/ready", response_model=HealthResponse, tags=["health"])
    async def ready(container: ContainerDep) -> JSONResponse:
        supabase_ok, cache_ok = await asyncio.gather(container.repository.health(), container.cache.ping())
        checks = {
            "supabase": "ok" if supabase_ok else "error",
            "cache": "ok" if cache_ok else ("disabled" if not getattr(container.cache, "enabled", True) else "error"),
        }
        status = "ok" if supabase_ok else "error"
        body = HealthResponse(status=status, service=settings.service_name, version=__version__, checks=checks)
        return JSONResponse(status_code=200 if supabase_ok else 503, content=body.model_dump())

    return app
