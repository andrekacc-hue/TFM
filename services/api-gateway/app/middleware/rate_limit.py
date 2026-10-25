"""Rate limiting por usuario con la librería ``limits`` (la misma que usa slowapi).

Se usa su API asíncrona directamente en lugar de los decoradores de slowapi para que:

* los límites salgan de la configuración (``RATE_LIMIT_*``) y no queden fijados al importar;
* las comprobaciones contra Redis no bloqueen el event loop;
* el contador sea compartido entre réplicas del gateway (Redis) o local (memoria).

Si Redis falla, el limitador deja pasar la petición (*fail-open*) y lo registra: un fallo
de la infraestructura de límites no debe tumbar el servicio.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request
from limits import parse
from limits.aio.storage import MemoryStorage, Storage
from limits.aio.strategies import MovingWindowRateLimiter

from shared.exceptions import AppError
from shared.logging import get_logger

logger = get_logger(__name__)


class RateLimitExceededError(AppError):
    status_code = 429
    code = "rate_limited"


def create_storage(redis_url: str | None) -> Storage:
    """Almacenamiento de contadores: Redis si está configurado, memoria si no."""
    if redis_url:
        from limits.aio.storage import RedisStorage

        return RedisStorage(f"async+{redis_url}", implementation="redispy")
    return MemoryStorage()


class RateLimiter:
    """Ventana deslizante por clave (usuario, servicio o IP).

    Args:
        storage: Almacenamiento de contadores.
    """

    def __init__(self, storage: Storage) -> None:
        self.limiter = MovingWindowRateLimiter(storage)

    async def check(self, limit: str, scope: str, key: str) -> None:
        """Consume una unidad del límite ``limit`` para ``key`` en ``scope``.

        Raises:
            RateLimitExceededError: Si se superó el límite.
        """
        item = parse(limit)
        try:
            allowed = await self.limiter.hit(item, scope, key)
        except Exception as exc:  # noqa: BLE001 - fail-open
            logger.warning("rate_limit_storage_error", error=str(exc))
            return
        if not allowed:
            stats = await self.limiter.get_window_stats(item, scope, key)
            retry_after = max(1, int(stats.reset_time - time.time()))
            logger.warning("rate_limited", scope=scope, key=key, limit=limit)
            raise RateLimitExceededError(
                f"Demasiadas solicitudes: límite de {limit}. Intenta de nuevo en {retry_after} s.",
                details={"limit": limit, "retry_after": retry_after},
            )


def client_key(request: Request) -> str:
    """Clave del limitador: id de usuario, servicio interno o IP."""
    user = getattr(request.state, "user", None)
    if user is not None and user.user_id:
        return f"user:{user.user_id}"
    if user is not None:
        return "service"
    forwarded = request.headers.get("x-forwarded-for", "")
    return f"ip:{forwarded.split(',')[0].strip() or (request.client.host if request.client else 'desconocida')}"


def rate_limit(scope: str, setting: str) -> Callable[[Request], Coroutine[Any, Any, None]]:
    """Dependencia que aplica el límite ``settings.<setting>`` al ámbito ``scope``.

    Debe declararse **después** de la dependencia de autenticación para limitar por usuario.
    """

    async def dependency(request: Request) -> None:
        container = request.app.state.container
        await container.rate_limiter.check(getattr(container.settings, setting), scope, client_key(request))

    return dependency
