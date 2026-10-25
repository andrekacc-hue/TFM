"""Exportación de reportes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.core.aggregator import Channel
from app.dependencies import ContainerDep, PeriodDep, require_internal_key

router = APIRouter(prefix="/v1/reports", tags=["reportes"], dependencies=[Depends(require_internal_key)])


@router.get(
    "/queries.{fmt}",
    summary="Exportar el registro de consultas",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}, "application/json": {}}}},
)
async def export_queries(
    fmt: Literal["csv", "json"], container: ContainerDep, period: PeriodDep, channel: Channel | None = None
) -> Response:
    """Consultas del periodo con latencia por etapa, fuentes y feedback (CSV para Excel o JSON)."""
    stamp = f"{period.start:%Y%m%d}-{period.end:%Y%m%d}"
    if fmt == "csv":
        body, media = await container.reporter.to_csv(period, channel), "text/csv; charset=utf-8"
    else:
        body, media = await container.reporter.to_json(period, channel), "application/json"
    return Response(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="consultas_{stamp}.{fmt}"'},
    )
