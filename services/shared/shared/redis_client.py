"""Cache en Redis con degradación elegante.

Si Redis no está configurado o deja de responder, la cache se desactiva y el servicio sigue
funcionando (más lento) en lugar de fallar: la cache es una optimización, no una
dependencia crítica.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Protocol

from shared.logging import get_logger

logger = get_logger(__name__)


def cache_key(namespace: str, *parts: str) -> str:
    """Construye una clave estable: ``<namespace>:<sha256(parts)>``."""
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


class Cache(Protocol):
    """Interfaz mínima de cache JSON."""

    async def get_json(self, key: str) -> Any | None: ...

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None: ...

    async def ping(self) -> bool: ...

    async def aclose(self) -> None: ...


class NullCache:
    """Cache vacía: se usa cuando Redis no está configurado."""

    enabled = False

    async def get_json(self, key: str) -> Any | None:
        return None

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        return None

    async def ping(self) -> bool:
        return False

    async def aclose(self) -> None:
        return None


class RedisCache:
    """Cache JSON sobre ``redis.asyncio`` con *circuit breaker* simple.

    Tras un error de conexión deja de intentar durante ``cooldown`` segundos.

    Args:
        client: Cliente ``redis.asyncio.Redis``.
        default_ttl: TTL por defecto en segundos.
        cooldown: Segundos sin reintentar tras un fallo.
    """

    enabled = True

    def __init__(self, client: Any, default_ttl: int = 3600, cooldown: float = 30.0) -> None:
        self._client = client
        self._default_ttl = default_ttl
        self._cooldown = cooldown
        self._disabled_until = 0.0

    def _available(self) -> bool:
        return time.monotonic() >= self._disabled_until

    def _trip(self, exc: Exception) -> None:
        self._disabled_until = time.monotonic() + self._cooldown
        logger.warning("redis_unavailable", error=str(exc), retry_in_s=self._cooldown)

    async def get_json(self, key: str) -> Any | None:
        if not self._available():
            return None
        try:
            raw = await self._client.get(key)
        except Exception as exc:  # noqa: BLE001 - cualquier fallo de Redis degrada a "sin cache"
            self._trip(exc)
            return None
        return json.loads(raw) if raw is not None else None

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        if not self._available():
            return
        try:
            await self._client.set(key, json.dumps(value), ex=ttl or self._default_ttl)
        except Exception as exc:  # noqa: BLE001
            self._trip(exc)

    async def ping(self) -> bool:
        try:
            return bool(await self._client.ping())
        except Exception:  # noqa: BLE001
            return False

    async def aclose(self) -> None:
        await self._client.aclose()


def create_stream_client(redis_url: str, *, block_ms: int = 5000) -> Any:
    """Cliente Redis para Streams (mensajería, no cache).

    A diferencia de la cache, aquí Redis SÍ es una dependencia crítica: el timeout de
    lectura debe superar el ``BLOCK`` de ``XREADGROUP`` para no cortar la espera.

    Args:
        redis_url: URL de Redis.
        block_ms: Milisegundos que ``XREADGROUP`` espera mensajes nuevos.
    """
    import redis.asyncio as redis

    return redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=2.0,
        socket_timeout=block_ms / 1000 + 5,
        health_check_interval=30,
    )


def create_cache(redis_url: str | None, default_ttl: int = 3600) -> Cache:
    """Crea la cache adecuada según la configuración.

    Args:
        redis_url: URL de Redis o ``None``.
        default_ttl: TTL por defecto.

    Returns:
        :class:`RedisCache` si hay URL; :class:`NullCache` en caso contrario.
    """
    if not redis_url:
        logger.info("cache_disabled", reason="REDIS_URL no configurada")
        return NullCache()
    import redis.asyncio as redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry

    # Un único intento con timeout corto: la cache debe fallar rápido, nunca bloquear la consulta
    client = redis.from_url(
        redis_url,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
        retry=Retry(NoBackoff(), 0),
        retry_on_timeout=False,
    )
    return RedisCache(client, default_ttl=default_ttl)
