from __future__ import annotations

import asyncio

from app.workers.outbox_poller import OutboxPoller
from shared.exceptions import UpstreamServiceError


class OutboxRepository:
    """Simula tfm.claim_pending_documents: entrega cada id una sola vez."""

    def __init__(self, pending: list[str], *, as_objects: bool = False, fail: bool = False) -> None:
        self.pending = list(pending)
        self.as_objects = as_objects
        self.fail = fail
        self.calls: list[dict] = []

    async def rpc(self, function: str, params: dict, *, user_jwt: str | None = None):
        self.calls.append({"function": function, **params})
        if self.fail:
            raise UpstreamServiceError("Supabase no disponible")
        batch, self.pending = self.pending[: params["p_limit"]], self.pending[params["p_limit"] :]
        return [{"claim_pending_documents": i} for i in batch] if self.as_objects else batch


async def test_publishes_claimed_documents(queue):
    repo = OutboxRepository(["doc-1", "doc-2", "doc-3"])
    poller = OutboxPoller(repo, queue, batch_size=2, stale_seconds=120)

    assert await poller.poll_once() == ["doc-1", "doc-2"]
    assert await poller.poll_once() == ["doc-3"]
    assert await poller.poll_once() == []

    messages = await queue.client.xrange(queue.stream)
    assert [m[1]["document_id"] for m in messages] == ["doc-1", "doc-2", "doc-3"]
    assert {m[1]["reason"] for m in messages} == {"outbox"}
    assert repo.calls[0] == {"function": "claim_pending_documents", "p_limit": 2, "p_stale_seconds": 120}
    assert poller.published == 3 and poller.is_alive()


async def test_accepts_object_rows_from_postgrest(queue):
    poller = OutboxPoller(OutboxRepository(["doc-9"], as_objects=True), queue)
    assert await poller.poll_once() == ["doc-9"]


async def test_run_survives_errors_and_stops(queue):
    repo = OutboxRepository([], fail=True)
    poller = OutboxPoller(repo, queue, interval_seconds=0.05)
    stop = asyncio.Event()
    task = asyncio.create_task(poller.run(stop))
    await asyncio.sleep(0.2)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert len(repo.calls) >= 2  # siguió sondeando pese a los fallos


def test_not_alive_before_first_poll(queue):
    assert not OutboxPoller(OutboxRepository([]), queue).is_alive()
