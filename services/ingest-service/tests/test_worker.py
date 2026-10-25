from __future__ import annotations

import asyncio

import pytest

from app.core.errors import IngestError, TransientIngestError
from app.workers.stream_consumer import StreamConsumer
from shared.exceptions import NotFoundError, UpstreamServiceError
from tests.conftest import PROCEDURE_MD, store_document


class ScriptedPipeline:
    """Pipeline que falla según un guion de excepciones."""

    def __init__(self, *outcomes: Exception | None) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, int]] = []

    async def process(self, document_id: str, *, attempt: int = 1):
        self.calls.append((document_id, attempt))
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome:
            raise outcome


async def _drain(consumer: StreamConsumer, rounds: int = 5) -> None:
    for _ in range(rounds):
        await consumer.poll_once()


async def _pending(queue) -> int:
    return (await queue.client.xpending(queue.stream, queue.group))["pending"]


async def test_publish_and_consume_with_real_pipeline(queue, pipeline, repo, storage):
    doc = store_document(repo, storage, PROCEDURE_MD.encode(), "proc.md")
    await queue.ensure_group()
    await queue.publish(doc["id"])

    consumer = StreamConsumer(queue, pipeline, consumer_name="w1", block_ms=10)
    assert await consumer.poll_once() == 1

    assert repo.documents[doc["id"]]["status"] == "indexed"
    assert consumer.processed == 1
    assert await _pending(queue) == 0
    assert consumer.is_alive()


async def test_transient_errors_are_retried_then_succeed(queue):
    pipeline = ScriptedPipeline(TransientIngestError("Storage caído"), None)
    await queue.ensure_group()
    await queue.publish("doc-1")
    consumer = StreamConsumer(queue, pipeline, consumer_name="w1", block_ms=10, max_attempts=3)

    await _drain(consumer, 3)

    assert pipeline.calls == [("doc-1", 1), ("doc-1", 2)]
    assert await _pending(queue) == 0
    assert await queue.client.xlen(queue.dlq) == 0


async def test_exhausted_retries_go_to_dead_letter(queue):
    pipeline = ScriptedPipeline(*[TransientIngestError("caído")] * 3)
    await queue.ensure_group()
    await queue.publish("doc-2")
    consumer = StreamConsumer(queue, pipeline, consumer_name="w1", block_ms=10, max_attempts=3)

    await _drain(consumer, 5)

    assert [attempt for _, attempt in pipeline.calls] == [1, 2, 3]
    dead = await queue.client.xrange(queue.dlq)
    assert len(dead) == 1 and dead[0][1]["document_id"] == "doc-2" and dead[0][1]["error"] == "caído"
    stats = await queue.stats()
    assert stats["dead_letter"] == 1 and stats["pending"] == 0


@pytest.mark.parametrize("error", [IngestError("PDF escaneado"), NotFoundError("no existe")])
async def test_non_retryable_errors_are_acked_once(queue, error):
    pipeline = ScriptedPipeline(error)
    await queue.ensure_group()
    await queue.publish("doc-3")
    consumer = StreamConsumer(queue, pipeline, consumer_name="w1", block_ms=10)
    await _drain(consumer, 3)
    assert len(pipeline.calls) == 1
    assert await _pending(queue) == 0
    assert await queue.client.xlen(queue.dlq) == 0


async def test_unexpected_error_goes_to_dead_letter(queue):
    pipeline = ScriptedPipeline(ZeroDivisionError("bug"))
    await queue.ensure_group()
    await queue.publish("doc-4")
    consumer = StreamConsumer(queue, pipeline, consumer_name="w1", block_ms=10)
    await _drain(consumer, 2)
    assert await queue.client.xlen(queue.dlq) == 1


async def test_stale_messages_from_crashed_worker_are_reclaimed(queue):
    await queue.ensure_group()
    await queue.publish("doc-5")
    # Un worker lee el mensaje y "muere" sin hacer ACK
    await queue.client.xreadgroup(queue.group, "worker-caido", {queue.stream: ">"}, count=1)
    assert await _pending(queue) == 1

    pipeline = ScriptedPipeline(None)
    rescuer = StreamConsumer(queue, pipeline, consumer_name="w2", block_ms=10, claim_idle_ms=1)
    await asyncio.sleep(0.01)
    await rescuer.poll_once()

    assert pipeline.calls == [("doc-5", 1)]
    assert await _pending(queue) == 0


async def test_ensure_group_is_idempotent_and_publish_fails_cleanly(queue):
    await queue.ensure_group()
    await queue.ensure_group()
    assert await queue.ping()

    class Broken:
        async def xadd(self, *a, **k):
            from redis.exceptions import ConnectionError as RedisConnectionError

            raise RedisConnectionError("sin redis")

    queue.client = Broken()
    with pytest.raises(UpstreamServiceError) as exc:
        await queue.publish("doc")
    assert exc.value.code == "queue_unavailable"


async def test_run_loop_stops_on_event(queue):
    pipeline = ScriptedPipeline()
    consumer = StreamConsumer(queue, pipeline, consumer_name="w1", block_ms=10)
    stop = asyncio.Event()
    task = asyncio.create_task(consumer.run(stop))
    await asyncio.sleep(0.1)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert consumer.last_poll is not None
