from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.chunker import RecursiveChunker
from app.core.embedder import BatchEmbedder
from app.core.pipeline import IngestionPipeline
from app.dependencies import Container
from app.main import create_app
from app.routes.ingest import safe_filename
from app.workers.stream_consumer import StreamConsumer
from tests.conftest import INTERNAL_KEY, PROCEDURE_MD


@pytest.fixture
def client(settings, repo, storage, embedder, queue, redis_client):
    def factory(_settings):
        pipeline = IngestionPipeline(repo, storage, RecursiveChunker(300, 50), BatchEmbedder(embedder))
        consumer = StreamConsumer(queue, pipeline, consumer_name="api-test", block_ms=10)
        return Container(_settings, repo, storage, redis_client, queue, embedder, pipeline, consumer, None)

    with TestClient(create_app(settings, factory)) as test_client:
        yield test_client


HEADERS = {"X-Internal-Api-Key": INTERNAL_KEY}
EDITOR = {**HEADERS, "X-User-Id": str(uuid4()), "X-User-Role": "editor", "X-User-Area": "operaciones"}


def _upload(client, *, name="Procedimiento batch.md", content=PROCEDURE_MD.encode(), area="operaciones", headers=EDITOR, **form):
    return client.post(
        "/v1/ingest",
        files={"file": (name, content, "text/markdown")},
        data={"source_type": "procedimiento", "area": area, **form},
        headers=headers,
    )


def test_upload_registers_document_and_enqueues(client, repo, storage, queue):
    response = _upload(client, title="PROC-OPS-014")
    assert response.status_code == 202, response.text
    body = response.json()

    doc = repo.documents[body["document_id"]]
    assert doc["status"] == "pending" and doc["title"] == "PROC-OPS-014"
    assert doc["storage_path"] == f"operaciones/{body['document_id']}/Procedimiento_batch.md"
    assert doc["metadata"]["sha256"] and doc["metadata"]["size_bytes"] == len(PROCEDURE_MD.encode())
    assert doc["uploaded_by"] == EDITOR["X-User-Id"]
    assert f"documents/{doc['storage_path']}" in storage.objects


async def test_uploaded_message_is_in_stream(client, queue):
    body = _upload(client).json()
    messages = await queue.client.xrange(queue.stream)
    assert messages[-1][1]["document_id"] == body["document_id"]
    assert messages[-1][1]["reason"] == "upload"


def test_default_title_is_filename_stem(client, repo):
    body = _upload(client, name="Manual ATM.md").json()
    assert repo.documents[body["document_id"]]["title"] == "Manual ATM"


def test_duplicate_upload_is_rejected(client):
    assert _upload(client).status_code == 202
    response = _upload(client, name="copia.md")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_document"


def test_unsupported_format(client):
    response = _upload(client, name="foto.png", content=b"\x89PNG")
    assert response.status_code == 415


def test_too_large_and_empty_files(client, settings):
    settings.max_upload_mb = 1
    assert _upload(client, content=b"a" * (1024 * 1024 + 10)).status_code == 413
    assert _upload(client, content=b"").status_code == 422


def test_viewer_cannot_upload_and_editor_only_in_own_area(client):
    viewer = {**EDITOR, "X-User-Role": "viewer"}
    assert _upload(client, headers=viewer).status_code == 403
    assert _upload(client, area="creditos").status_code == 403
    admin = {**EDITOR, "X-User-Role": "admin"}
    assert _upload(client, area="creditos", headers=admin).status_code == 202


def test_requires_internal_key(client):
    assert _upload(client, headers={}).status_code == 401


def test_invalid_area(client):
    assert _upload(client, area="Área Inválida").status_code == 422


def test_failed_db_insert_removes_uploaded_file(client, repo, storage):
    repo.fail_insert = True
    with pytest.raises(RuntimeError):
        _upload(client)
    assert storage.objects == {}


def test_reindex_and_status(client, repo):
    doc = repo.add_document(status="failed", error_message="boom")
    response = client.post(f"/v1/ingest/{doc['id']}/reindex", headers=EDITOR)
    assert response.status_code == 202
    assert repo.documents[doc["id"]]["status"] == "pending"
    assert repo.documents[doc["id"]]["error_message"] is None

    status = client.get(f"/v1/ingest/{doc['id']}", headers=HEADERS).json()
    assert status["status"] == "pending" and status["area"] == "operaciones"


def test_reindex_unknown_document(client):
    assert client.post(f"/v1/ingest/{uuid4()}/reindex", headers=HEADERS).status_code == 404
    assert client.get(f"/v1/ingest/{uuid4()}", headers=HEADERS).status_code == 404


def test_queue_unavailable_marks_document_failed(client, repo, queue):
    class Broken:
        async def xadd(self, *a, **k):
            from redis.exceptions import ConnectionError as RedisConnectionError

            raise RedisConnectionError("sin redis")

    queue.client = Broken()
    response = _upload(client)
    assert response.status_code == 502
    doc = next(iter(repo.documents.values()))
    assert doc["status"] == "failed" and "reindex" in doc["error_message"]


def test_queue_stats_and_health(client):
    _upload(client)
    stats = client.get("/v1/ingest/queue/stats", headers=HEADERS).json()
    assert stats["length"] == 1 and stats["worker"]["consumer"] == "api-test"
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/ready").json()
    assert ready["checks"] == {"supabase": "ok", "redis": "ok", "models": "ok", "worker": "disabled"}


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Manual Operación ATM.pdf", "Manual_Operacion_ATM.pdf"), ("..\\..\\etc/passwd.md", "passwd.md"), ("###.docx", "documento.docx")],
)
def test_safe_filename(name, expected):
    assert safe_filename(name) == expected
