"""Aplicación FastAPI del rag-service.

Ejecutar en desarrollo (desde services/rag-service):
    uvicorn app.main:create_app --factory --port 8001 --reload
Documentación OpenAPI: http://localhost:8001/docs
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import __version__
from app.config import RagSettings, get_settings
from app.dependencies import Container, ContainerDep, build_container, preload_models
from app.routes import query
from shared.exceptions import register_exception_handlers
from shared.logging import configure_logging, get_logger
from shared.middleware import RequestContextMiddleware
from shared.schemas import HealthResponse

logger = get_logger(__name__)


def create_app(
    settings: RagSettings | None = None,
    container_factory: Callable[[RagSettings], Container] = build_container,
) -> FastAPI:
    """Crea la aplicación.

    Args:
        settings: Configuración; por defecto se lee del entorno.
        container_factory: Constructor de dependencias (los tests inyectan dobles).
    """
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = container_factory(settings)
        app.state.container = container
        preload: asyncio.Task[None] | None = None
        if settings.preload_models:
            preload = asyncio.create_task(preload_models(container))
        logger.info(
            "service_started",
            llm_provider=container.llm.provider,
            llm_model=container.llm.model,
            rerank=type(container.reranker).__name__,
            schema=settings.supabase_schema,
        )
        try:
            yield
        finally:
            if preload and not preload.done():
                preload.cancel()
            await container.aclose()

    app = FastAPI(
        title="rag-service",
        version=__version__,
        description="Orquestación RAG del Sistema de Soporte TI Produbanco: retrieval (pgvector), "
        "reranking (cross-encoder), generación con LLM intercambiable y guardrails.",
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(query.router)

    @app.get("/health", response_model=HealthResponse, tags=["health"], summary="Liveness")
    async def health() -> HealthResponse:
        """El proceso está vivo (no comprueba dependencias)."""
        return HealthResponse(status="ok", service=settings.service_name, version=__version__)

    @app.get("/ready", response_model=HealthResponse, tags=["health"], summary="Readiness")
    async def ready(container: ContainerDep) -> JSONResponse:
        """Comprueba Supabase, el LLM, la cache y la carga de modelos."""
        supabase_ok, llm_ok, cache_ok = await asyncio.gather(
            container.repository.health(), container.llm.health(), container.cache.ping()
        )
        checks = {
            "supabase": "ok" if supabase_ok else "error",
            "llm": f"ok ({container.llm.provider}:{container.llm.model})" if llm_ok else "error",
            "cache": "ok" if cache_ok else ("disabled" if not getattr(container.cache, "enabled", True) else "error"),
            "models": "ok" if container.models_ready else "loading",
        }
        if not (supabase_ok and llm_ok):
            status = "error"
        elif checks["cache"] == "error" or not container.models_ready:
            status = "degraded"
        else:
            status = "ok"
        body = HealthResponse(status=status, service=settings.service_name, version=__version__, checks=checks)
        return JSONResponse(status_code=200 if status != "error" else 503, content=body.model_dump())

    return app
