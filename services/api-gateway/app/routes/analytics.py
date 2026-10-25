"""Métricas y reportes (proxy al analytics-service)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request, Response

from app.dependencies import ContainerDep
from app.middleware.auth import CurrentUser, require_role
from app.middleware.rate_limit import rate_limit

router = APIRouter(prefix="/api/v1", tags=["analítica"])

Metric = Literal["summary", "timeseries", "top-documents", "unanswered", "knowledge-base"]


@router.get(
    "/analytics/{metric}",
    summary="Métricas del asistente",
    dependencies=[Depends(require_role("editor")), Depends(rate_limit("analytics", "rate_limit_default"))],
)
async def metric(metric: Metric, request: Request, user: CurrentUser, container: ContainerDep) -> Response:
    """Parámetros admitidos: ``from``, ``to`` (ISO 8601), ``channel``, ``bucket`` y ``limit``,
    según la métrica. Disponible para editores y administradores."""
    return await container.analytics.forward("GET", f"/v1/metrics/{metric}", user=user, params=request.query_params)


@router.get(
    "/reports/queries.{fmt}",
    summary="Exportar consultas (CSV / JSON)",
    dependencies=[Depends(require_role("admin")), Depends(rate_limit("export", "rate_limit_export"))],
)
async def export(fmt: Literal["csv", "json"], request: Request, user: CurrentUser, container: ContainerDep) -> Response:
    """Incluye preguntas e identificadores de usuario: solo administradores."""
    return await container.analytics.forward("GET", f"/v1/reports/queries.{fmt}", user=user, params=request.query_params)
