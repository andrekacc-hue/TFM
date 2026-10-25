"""Agregación de métricas sobre las funciones SQL ``tfm.metrics_*`` (migración 08).

PostgreSQL calcula percentiles y tasas; este módulo valida rangos, invoca las funciones
con service_role y cachea los resultados unos segundos (el dashboard refresca a menudo
y las métricas de un periodo cerrado no cambian).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from shared.exceptions import ValidationAppError
from shared.redis_client import Cache, cache_key
from shared.supabase_client import SupabaseRepository

Bucket = Literal["hour", "day", "week", "month"]
Channel = Literal["web", "teams", "api"]


@dataclass(frozen=True)
class DateRange:
    """Intervalo semiabierto ``[start, end)`` en UTC."""

    start: datetime
    end: datetime

    @classmethod
    def resolve(
        cls,
        start: datetime | None,
        end: datetime | None,
        *,
        default_days: int = 7,
        max_days: int = 366,
    ) -> DateRange:
        """Completa y valida el rango (por defecto, los últimos ``default_days`` días).

        Raises:
            ValidationAppError: Si ``start >= end`` o el rango supera ``max_days``.
        """
        end = _as_utc(end) if end else datetime.now(UTC)
        start = _as_utc(start) if start else end - timedelta(days=default_days)
        if start >= end:
            raise ValidationAppError("La fecha inicial debe ser anterior a la final")
        if end - start > timedelta(days=max_days):
            raise ValidationAppError(f"El rango máximo es de {max_days} días")
        return cls(start, end)

    def params(self) -> dict[str, str]:
        return {"p_from": self.start.isoformat(), "p_to": self.end.isoformat()}


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class MetricsAggregator:
    """Fachada sobre las funciones de métricas.

    Args:
        repository: Acceso a PostgREST con service_role.
        cache: Cache de resultados.
        ttl: Segundos de cache (0 desactiva).
    """

    def __init__(self, repository: SupabaseRepository, cache: Cache, *, ttl: int = 60) -> None:
        self.repository = repository
        self.cache = cache
        self.ttl = ttl

    async def _rpc(self, function: str, params: dict[str, Any]) -> Any:
        key = cache_key("metrics", function, repr(sorted(params.items())))
        if self.ttl:
            cached = await self.cache.get_json(key)
            if cached is not None:
                return cached
        result = await self.repository.rpc(function, params)
        if self.ttl:
            await self.cache.set_json(key, result, ttl=self.ttl)
        return result

    async def summary(self, period: DateRange, channel: Channel | None = None) -> dict[str, Any]:
        """Totales, tasas de abstención y satisfacción, percentiles de latencia y tokens."""
        return await self._rpc("metrics_summary", {**period.params(), "p_channel": channel})

    async def timeseries(self, period: DateRange, bucket: Bucket = "day", channel: Channel | None = None) -> list[dict[str, Any]]:
        """Consultas, abstenciones, latencia y feedback por intervalo."""
        return await self._rpc("metrics_timeseries", {**period.params(), "p_bucket": bucket, "p_channel": channel})

    async def top_documents(self, period: DateRange, limit: int = 10) -> list[dict[str, Any]]:
        """Documentos más citados como fuente."""
        return await self._rpc("metrics_top_documents", {**period.params(), "p_limit": limit})

    async def unanswered(self, period: DateRange, limit: int = 20) -> list[dict[str, Any]]:
        """Preguntas que terminaron en abstención (brechas de documentación)."""
        return await self._rpc("metrics_unanswered", {**period.params(), "p_limit": limit})

    async def knowledge_base(self) -> dict[str, Any]:
        """Documentos por estado, área y tipo; chunks, incidentes y golden dataset."""
        return await self._rpc("metrics_knowledge_base", {})
