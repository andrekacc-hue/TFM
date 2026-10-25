"""Cola de ingesta sobre Redis Streams.

* Stream ``documents.ingest``: un mensaje por documento a procesar.
* Grupo de consumidores ``ingest-workers``: varias réplicas del worker se reparten los
  mensajes y cada uno se entrega a un único consumidor (escalado horizontal).
* Stream ``documents.ingest.dlq``: mensajes que agotaron los reintentos (*dead-letter*).

Redis Streams da entrega *at-least-once*: un mensaje sin ``XACK`` sigue pendiente y otro
worker lo reclama si el primero cae. Por eso el pipeline es idempotente.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from redis.exceptions import RedisError, ResponseError

from shared.exceptions import UpstreamServiceError
from shared.logging import get_logger, get_trace_id

logger = get_logger(__name__)


class IngestQueue:
    """Publicación y administración del stream de ingesta.

    Args:
        client: Cliente ``redis.asyncio`` con ``decode_responses=True``.
        stream: Nombre del stream.
        group: Grupo de consumidores.
        maxlen: Longitud aproximada máxima del stream (recorte con ``~``).
    """

    def __init__(self, client: Any, stream: str = "documents.ingest", group: str = "ingest-workers", *, maxlen: int = 10_000) -> None:
        self.client = client
        self.stream = stream
        self.group = group
        self.dlq = f"{stream}.dlq"
        self.maxlen = maxlen

    async def ensure_group(self) -> None:
        """Crea el stream y el grupo si no existen (idempotente)."""
        try:
            await self.client.xgroup_create(self.stream, self.group, id="0", mkstream=True)
            logger.info("stream_group_created", stream=self.stream, group=self.group)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def publish(self, document_id: str, *, reason: str = "upload", attempt: int = 1) -> str:
        """Encola un documento para ingesta.

        Returns:
            Id del mensaje en el stream.

        Raises:
            UpstreamServiceError: Si Redis no está disponible.
        """
        fields = {
            "document_id": str(document_id),
            "reason": reason,
            "attempt": str(attempt),
            "trace_id": get_trace_id() or "",
            "enqueued_at": datetime.now(UTC).isoformat(),
        }
        try:
            message_id = await self.client.xadd(self.stream, fields, maxlen=self.maxlen, approximate=True)
        except RedisError as exc:
            raise UpstreamServiceError(
                "La cola de ingesta (Redis) no está disponible", code="queue_unavailable", details={"error": str(exc)}
            ) from exc
        logger.info("ingest_enqueued", document_id=str(document_id), reason=reason, attempt=attempt, message_id=message_id)
        return message_id

    async def dead_letter(self, fields: dict[str, str], error: str) -> str:
        """Mueve un mensaje agotado a la DLQ para revisión manual."""
        return await self.client.xadd(
            self.dlq, {**fields, "error": error[:500], "failed_at": datetime.now(UTC).isoformat()}, maxlen=self.maxlen, approximate=True
        )

    async def stats(self) -> dict[str, Any]:
        """Longitud del stream, mensajes pendientes de ACK y tamaño de la DLQ."""
        try:
            length = await self.client.xlen(self.stream)
            dlq = await self.client.xlen(self.dlq)
            try:
                pending = (await self.client.xpending(self.stream, self.group))["pending"]
            except ResponseError:
                pending = 0
            return {"stream": self.stream, "length": length, "pending": pending, "dead_letter": dlq}
        except RedisError as exc:
            raise UpstreamServiceError("Redis no disponible", code="queue_unavailable", details={"error": str(exc)}) from exc

    async def ping(self) -> bool:
        try:
            return bool(await self.client.ping())
        except RedisError:
            return False
