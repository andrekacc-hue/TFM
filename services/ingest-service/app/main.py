"""Aplicación FastAPI del ingest-service.

Ejecutar en desarrollo (desde services/ingest-service):
    uvicorn app.main:create_app --factory --port 8002
Documentación OpenAPI: http://localhost:8002/docs
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import __version__
from app.config import IngestSettings, get_settings
from app.dependencies import Container, ContainerDep, build_container
from app.routes import ingest
from shared.exceptions import register_exception_handlers
from shared.logging import configure_logging, get_logger
from shared.middleware import RequestContextMiddleware
from shared.schemas import HealthResponse

logger = get_logger(__name__)


async def _preload(container: Container) -> None:
    loader = getattr(container.embedder, "load", None)
    if loader is not None:
        await asyncio.to_thread(loader)
    container.models_ready = True


def create_app(
    settings: IngestSettings | None = None,
    container_factory: Callable[[IngestSettings], Container] = build_container,
) -> FastAPI:
    """Crea la aplicación (y, si ``WORKER_ENABLED``, arranca el worker en segundo plano)."""
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = container_factory(settings)
        app.state.container = container
        tasks: list[asyncio.Task[None]] = []
        stop = asyncio.Event()

        if settings.preload_models:
            tasks.append(asyncio.create_task(_preload(container)))
        else:
            container.models_ready = True
        if settings.worker_enabled:
            tasks.append(asyncio.create_task(container.consumer.run(stop), name="ingest-worker"))

        logger.info("service_started", worker=settings.worker_enabled, stream=settings.redis_stream_ingest,
                    chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
        try:
            yield
        finally:
            stop.set()
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            await container.aclose()

    app = FastAPI(
        title="ingest-service",
        version=__version__,
        description="Ingesta asíncrona de documentos: Supabase Storage → extracción (PDF/DOCX/Markdown) → "
        "chunking → embeddings → pgvector, orquestada con Redis Streams.",
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(ingest.router)

    @app.get("/health", response_model=HealthResponse, tags=["health"], summary="Liveness")
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service=settings.service_name, version=__version__)

    @app.get("/ready", response_model=HealthResponse, tags=["health"], summary="Readiness")
    async def ready(container: ContainerDep) -> JSONResponse:
        supabase_ok, redis_ok = await asyncio.gather(container.repository.health(), container.queue.ping())
        worker = "disabled"
        if settings.worker_enabled:
            worker = "ok" if container.consumer.is_alive() else "stalled"
        checks = {
            "supabase": "ok" if supabase_ok else "error",
            "redis": "ok" if redis_ok else "error",
            "models": "ok" if container.models_ready else "loading",
            "worker": worker,
        }
        if not (supabase_ok and redis_ok):
            status = "error"
        elif not container.models_ready or worker == "stalled":
            status = "degraded"
        else:
            status = "ok"
        body = HealthResponse(status=status, service=settings.service_name, version=__version__, checks=checks)
        return JSONResponse(status_code=200 if status != "error" else 503, content=body.model_dump())

    return app
