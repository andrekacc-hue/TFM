"""Aplicación FastAPI del api-gateway: el único servicio expuesto al exterior (puerto 8000).

Ejecutar en desarrollo (desde services/api-gateway):
    uvicorn app.main:create_app --factory --port 8000
Documentación OpenAPI: http://localhost:8000/docs
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import GatewaySettings, get_settings
from app.dependencies import Container, build_container
from app.middleware.tracing import TRACE_HEADER, RequestContextMiddleware
from app.routes import analytics, documents, health, query
from shared.exceptions import register_exception_handlers
from shared.logging import configure_logging, get_logger

logger = get_logger(__name__)

DESCRIPTION = """
API pública del **Sistema Inteligente de Soporte Técnico** (TI Producción, Produbanco).

**Autenticación:** `Authorization: Bearer <access_token de Supabase Auth>`. El rol y el área
del usuario se leen de `tfm.profiles`. Los servicios internos (bot de Teams) usan
`X-Internal-Api-Key` y, opcionalmente, `X-User-Email` para actuar en nombre de un usuario.

| Rol | Puede |
|-----|-------|
| viewer | consultar al asistente y valorar respuestas |
| editor | + subir y reindexar documentos de su área, ver métricas |
| admin  | + todas las áreas, cola de ingesta y exportación de reportes |

Cada respuesta incluye `X-Trace-Id`, que identifica la petición en los logs de todos los
servicios y en `tfm.queries.trace_id`.
"""


def create_app(
    settings: GatewaySettings | None = None,
    container_factory: Callable[[GatewaySettings], Container] = build_container,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container_factory(settings)
        logger.info(
            "gateway_started",
            rag=settings.rag_service_url,
            ingest=settings.ingest_service_url,
            analytics=settings.analytics_service_url,
            rate_limit_storage="redis" if settings.redis_url else "memory",
        )
        try:
            yield
        finally:
            await app.state.container.aclose()

    app = FastAPI(title="Soporte TI Produbanco — API", version=__version__, description=DESCRIPTION, lifespan=lifespan)
    # Orden: el último añadido es el más externo. CORS debe envolver todo (también los errores).
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", TRACE_HEADER],
        expose_headers=[TRACE_HEADER, "Content-Disposition", "Retry-After"],
    )
    register_exception_handlers(app)
    for router in (health.router, query.router, documents.router, analytics.router):
        app.include_router(router)
    return app
