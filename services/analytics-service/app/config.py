"""Configuración del analytics-service."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from shared.config import BaseServiceSettings


class AnalyticsSettings(BaseServiceSettings):
    """Parámetros de agregación, cache y exportación."""

    service_name: str = "analytics-service"
    metrics_cache_ttl: int = Field(60, ge=0, le=3600, description="Segundos de cache de cada métrica")
    max_range_days: int = Field(366, ge=1)
    default_range_days: int = Field(7, ge=1)
    export_max_rows: int = Field(10_000, ge=100, le=100_000)
    export_page_size: int = Field(1000, ge=100, le=5000)


@lru_cache
def get_settings() -> AnalyticsSettings:
    return AnalyticsSettings()  # type: ignore[call-arg]
