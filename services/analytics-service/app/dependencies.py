"""Composición de dependencias del analytics-service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Header, Query, Request

from app.config import AnalyticsSettings
from app.core.aggregator import DateRange, MetricsAggregator
from app.core.reporter import QueryReporter
from shared.auth import verify_internal_api_key
from shared.redis_client import Cache, create_cache
from shared.supabase_client import SupabaseRepository


@dataclass
class Container:
    settings: AnalyticsSettings
    repository: SupabaseRepository
    cache: Cache
    aggregator: MetricsAggregator
    reporter: QueryReporter

    async def aclose(self) -> None:
        await self.repository.aclose()
        await self.cache.aclose()


def build_container(settings: AnalyticsSettings) -> Container:
    repository = SupabaseRepository(
        settings.supabase_url,
        settings.supabase_service_role_key.get_secret_value(),
        schema=settings.supabase_schema,
        timeout=30,
    )
    cache = create_cache(settings.redis_url, settings.metrics_cache_ttl)
    return Container(
        settings,
        repository,
        cache,
        MetricsAggregator(repository, cache, ttl=settings.metrics_cache_ttl),
        QueryReporter(repository, page_size=settings.export_page_size, max_rows=settings.export_max_rows),
    )


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


def require_internal_key(container: ContainerDep, x_internal_api_key: Annotated[str | None, Header()] = None) -> None:
    """Solo el api-gateway puede consultar métricas (él aplica el control por rol)."""
    verify_internal_api_key(x_internal_api_key, container.settings.internal_api_key.get_secret_value())


def get_period(
    container: ContainerDep,
    start: Annotated[datetime | None, Query(alias="from", description="Inicio (ISO 8601). Por defecto: hace 7 días")] = None,
    end: Annotated[datetime | None, Query(alias="to", description="Fin exclusivo (ISO 8601). Por defecto: ahora")] = None,
) -> DateRange:
    settings = container.settings
    return DateRange.resolve(start, end, default_days=settings.default_range_days, max_days=settings.max_range_days)


PeriodDep = Annotated[DateRange, Depends(get_period)]
