"""Endpoints de métricas para el dashboard y la evaluación."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.core.aggregator import Bucket, Channel
from app.dependencies import ContainerDep, PeriodDep, require_internal_key

router = APIRouter(prefix="/v1/metrics", tags=["métricas"], dependencies=[Depends(require_internal_key)])


def _period_info(period: PeriodDep) -> dict[str, str]:
    return {"from": period.start.isoformat(), "to": period.end.isoformat()}


@router.get("/summary", summary="Resumen del periodo")
async def summary(container: ContainerDep, period: PeriodDep, channel: Channel | None = None) -> dict[str, Any]:
    """Consultas, usuarios, abstención, bloqueos, latencia (p50/p90/p95/p99 y por etapa),
    tokens, satisfacción y desglose por canal y modelo."""
    return {**_period_info(period), "channel": channel, **(await container.aggregator.summary(period, channel))}


@router.get("/timeseries", summary="Serie temporal")
async def timeseries(
    container: ContainerDep, period: PeriodDep, bucket: Bucket = "day", channel: Channel | None = None
) -> dict[str, Any]:
    return {**_period_info(period), "bucket": bucket, "points": await container.aggregator.timeseries(period, bucket, channel)}


@router.get("/top-documents", summary="Documentos más citados")
async def top_documents(
    container: ContainerDep, period: PeriodDep, limit: Annotated[int, Query(ge=1, le=100)] = 10
) -> dict[str, Any]:
    return {**_period_info(period), "documents": await container.aggregator.top_documents(period, limit)}


@router.get("/unanswered", summary="Preguntas sin respuesta")
async def unanswered(
    container: ContainerDep, period: PeriodDep, limit: Annotated[int, Query(ge=1, le=200)] = 20
) -> dict[str, Any]:
    """Preguntas que terminaron en abstención: indican qué documentación falta."""
    return {**_period_info(period), "questions": await container.aggregator.unanswered(period, limit)}


@router.get("/knowledge-base", summary="Estado de la base de conocimientos")
async def knowledge_base(container: ContainerDep) -> dict[str, Any]:
    return await container.aggregator.knowledge_base()
