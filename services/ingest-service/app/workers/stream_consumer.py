"""Worker que consume ``documents.ingest`` (Redis Streams, grupo de consumidores).

Ciclo:
  1. Reclama mensajes huérfanos (sin ACK durante ``claim_idle_ms``) de workers caídos.
  2. ``XREADGROUP`` bloqueante para mensajes nuevos.
  3. Procesa con :class:`IngestionPipeline` y hace ``XACK``.

Política de errores:
  * error de contenido (formato, PDF escaneado...) → ``failed`` y ACK (no se reintenta);
  * error transitorio → se reencola con ``attempt + 1`` hasta ``max_attempts``; después,
    a la DLQ ``documents.ingest.dlq`` y ACK;
  * documento inexistente → ACK y descarte.

Puede ejecutarse dentro del ingest-service (``WORKER_ENABLED=true``) o como proceso
independiente para escalar horizontalmente::

    python -m app.workers.stream_consumer
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
from typing import Any

from redis.exceptions import RedisError

from app.core.errors import IngestError
from app.core.pipeline import IngestionPipeline
from app.core.queue import IngestQueue
from shared.exceptions import NotFoundError
from shared.logging import bind_trace_id, clear_context, get_logger, new_trace_id

logger = get_logger(__name__)


def default_consumer_name() -> str:
    """Nombre único por proceso: ``<host>-<pid>``."""
    return f"{socket.gethostname()}-{os.getpid()}"


class StreamConsumer:
    """Consumidor del stream de ingesta.

    Args:
        queue: Cola (stream + grupo).
        pipeline: Pipeline de ingesta.
        consumer_name: Identidad dentro del grupo.
        block_ms: Espera máxima de ``XREADGROUP``.
        max_attempts: Intentos antes de enviar a la DLQ.
        claim_idle_ms: Antigüedad mínima para reclamar mensajes de otros consumidores.
    """

    def __init__(
        self,
        queue: IngestQueue,
        pipeline: IngestionPipeline,
        *,
        consumer_name: str | None = None,
        block_ms: int = 5000,
        max_attempts: int = 3,
        claim_idle_ms: int = 300_000,
    ) -> None:
        self.queue = queue
        self.pipeline = pipeline
        self.consumer_name = consumer_name or default_consumer_name()
        self.block_ms = block_ms
        self.max_attempts = max_attempts
        self.claim_idle_ms = claim_idle_ms
        self.last_poll: float | None = None
        self.processed = 0
        self.failed = 0

    # ------------------------------------------------------------------
    async def run(self, stop: asyncio.Event) -> None:
        """Bucle principal hasta que se active ``stop``.

        Si Redis no está disponible (también al arrancar) espera con *backoff* exponencial
        en lugar de terminar: el worker se recupera solo cuando Redis vuelve.
        """
        logger.info("worker_started", consumer=self.consumer_name, stream=self.queue.stream, group=self.queue.group)
        backoff = 1.0
        group_ready = False
        while not stop.is_set():
            try:
                if not group_ready:
                    await self.queue.ensure_group()
                    group_ready = True
                handled = await self.poll_once()
                backoff = 1.0
                if not handled:
                    await asyncio.sleep(0)  # cede el loop entre lecturas vacías
            except asyncio.CancelledError:
                raise
            except RedisError as exc:
                logger.warning("worker_redis_error", error=str(exc), retry_in_s=backoff)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                except TimeoutError:
                    pass
                backoff = min(backoff * 2, 30.0)
        logger.info("worker_stopped", consumer=self.consumer_name, processed=self.processed, failed=self.failed)

    async def poll_once(self) -> int:
        """Una iteración: reclama huérfanos y lee mensajes nuevos.

        Returns:
            Número de mensajes procesados.
        """
        self.last_poll = time.monotonic()
        messages = await self._claim_stale()
        if not messages:
            response = await self.queue.client.xreadgroup(
                self.queue.group, self.consumer_name, {self.queue.stream: ">"}, count=1, block=self.block_ms
            )
            messages = response[0][1] if response else []
        for message_id, fields in messages:
            await self.handle(message_id, fields)
        return len(messages)

    async def _claim_stale(self) -> list[tuple[str, dict[str, str]]]:
        result = await self.queue.client.xautoclaim(
            self.queue.stream, self.queue.group, self.consumer_name, min_idle_time=self.claim_idle_ms, start_id="0-0", count=1
        )
        claimed = [(mid, fields) for mid, fields in result[1] if fields] if result else []
        if claimed:
            logger.warning("worker_claimed_stale", messages=[mid for mid, _ in claimed])
        return claimed

    # ------------------------------------------------------------------
    async def handle(self, message_id: str, fields: dict[str, Any]) -> None:
        """Procesa un mensaje y decide ACK, reintento o DLQ."""
        document_id = fields.get("document_id", "")
        attempt = int(fields.get("attempt", 1) or 1)
        bind_trace_id(fields.get("trace_id") or new_trace_id())
        log = logger.bind(message_id=message_id, document_id=document_id, attempt=attempt)
        try:
            await self.pipeline.process(document_id, attempt=attempt)
            self.processed += 1
        except NotFoundError:
            log.warning("message_discarded", reason="documento inexistente")
        except IngestError as exc:
            self.failed += 1
            if exc.retryable and attempt < self.max_attempts:
                await self.queue.publish(document_id, reason=f"retry:{fields.get('reason', '')}", attempt=attempt + 1)
                log.warning("message_requeued", next_attempt=attempt + 1, error=exc.message)
            elif exc.retryable:
                await self.queue.dead_letter({k: str(v) for k, v in fields.items()}, exc.message)
                log.error("message_dead_lettered", error=exc.message)
        except Exception as exc:  # noqa: BLE001 - el worker no debe morir por un mensaje
            self.failed += 1
            log.exception("message_unexpected_error")
            await self.queue.dead_letter({k: str(v) for k, v in fields.items()}, f"{type(exc).__name__}: {exc}")
        finally:
            await self.queue.client.xack(self.queue.stream, self.queue.group, message_id)
            clear_context()

    def is_alive(self, max_silence_s: float | None = None) -> bool:
        """``True`` si el worker ha consultado el stream recientemente."""
        if self.last_poll is None:
            return False
        limit = max_silence_s if max_silence_s is not None else self.block_ms / 1000 * 3 + 30
        return time.monotonic() - self.last_poll < limit


async def _main() -> None:  # pragma: no cover - punto de entrada del proceso
    import signal

    from app.config import get_settings
    from app.dependencies import build_container

    settings = get_settings()
    from shared.logging import configure_logging

    configure_logging(f"{settings.service_name}-worker", settings.log_level, settings.log_format)
    container = build_container(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            signal.signal(sig, lambda *_: stop.set())
    try:
        await asyncio.to_thread(container.embedder.load)
        await container.consumer.run(stop)
    finally:
        await container.aclose()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
