"""Outbox poller: publica en Redis los documentos ``pending`` que nadie encoló.

Fuentes de documentos pendientes:
  * subidas directas a Storage registradas por la Edge Function ``on-document-upload``;
  * reindexaciones pedidas con la Edge Function ``reindex-document``;
  * documentos encolados cuyo mensaje se perdió (Redis reiniciado sin persistencia):
    si llevan más de ``stale_seconds`` en ``pending`` se reclaman de nuevo.

``tfm.claim_pending_documents`` usa ``FOR UPDATE SKIP LOCKED``, así que varias réplicas del
servicio pueden sondear a la vez sin publicar el mismo documento dos veces.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.core.queue import IngestQueue
from shared.exceptions import AppError
from shared.logging import get_logger
from shared.supabase_client import SupabaseRepository

logger = get_logger(__name__)


class OutboxPoller:
    """Reclama documentos pendientes y los publica en el stream de ingesta.

    Args:
        repository: PostgREST con service_role.
        queue: Cola de ingesta.
        interval_seconds: Pausa entre sondeos.
        batch_size: Documentos reclamados por sondeo.
        stale_seconds: Antigüedad a partir de la cual un documento encolado se reencola.
    """

    def __init__(
        self,
        repository: SupabaseRepository,
        queue: IngestQueue,
        *,
        interval_seconds: float = 15.0,
        batch_size: int = 10,
        stale_seconds: int = 300,
    ) -> None:
        self.repository = repository
        self.queue = queue
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size
        self.stale_seconds = stale_seconds
        self.last_poll: float | None = None
        self.published = 0

    async def poll_once(self) -> list[str]:
        """Un sondeo: reclama y publica. Devuelve los ids publicados."""
        self.last_poll = time.monotonic()
        rows: list[Any] = await self.repository.rpc(
            "claim_pending_documents", {"p_limit": self.batch_size, "p_stale_seconds": self.stale_seconds}
        )
        # PostgREST devuelve "setof uuid" como lista de valores (o de objetos según la versión)
        ids = [row if isinstance(row, str) else next(iter(row.values())) for row in rows or []]
        for document_id in ids:
            await self.queue.publish(document_id, reason="outbox")
        if ids:
            self.published += len(ids)
            logger.info("outbox_published", documents=ids)
        return ids

    async def run(self, stop: asyncio.Event) -> None:
        """Sondea hasta que se active ``stop``. Los errores se registran y se reintenta."""
        logger.info("outbox_started", interval_s=self.interval_seconds, stale_s=self.stale_seconds)
        while not stop.is_set():
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except (AppError, OSError) as exc:
                logger.warning("outbox_poll_failed", error=str(exc))
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                pass
        logger.info("outbox_stopped", published=self.published)

    def is_alive(self) -> bool:
        return self.last_poll is not None and time.monotonic() - self.last_poll < self.interval_seconds * 3 + 30
