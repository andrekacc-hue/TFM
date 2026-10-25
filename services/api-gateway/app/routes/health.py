"""Salud del gateway y de los servicios internos."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import __version__
from app.dependencies import ContainerDep
from shared.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness")
async def health(container: ContainerDep) -> HealthResponse:
    return HealthResponse(status="ok", service=container.settings.service_name, version=__version__)


@router.get("/ready", response_model=HealthResponse, summary="Readiness agregada")
async def ready(container: ContainerDep) -> JSONResponse:
    """Comprueba Supabase y el ``/health`` de cada servicio interno.

    ``degraded`` si falta analytics (las consultas siguen funcionando); ``error`` si faltan
    Supabase o el rag-service.
    """
    names = ("supabase", "rag-service", "ingest-service", "analytics-service")
    results = await asyncio.gather(
        container.repository.health(), container.rag.healthy(), container.ingest.healthy(), container.analytics.healthy()
    )
    checks = {name: "ok" if ok else "error" for name, ok in zip(names, results, strict=True)}
    if checks["supabase"] == "error" or checks["rag-service"] == "error":
        status = "error"
    elif "error" in checks.values():
        status = "degraded"
    else:
        status = "ok"
    body = HealthResponse(status=status, service=container.settings.service_name, version=__version__, checks=checks)
    return JSONResponse(status_code=503 if status == "error" else 200, content=body.model_dump())
