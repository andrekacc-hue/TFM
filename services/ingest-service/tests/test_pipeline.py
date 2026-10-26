from __future__ import annotations

import pytest

from app.core.errors import IngestError, TransientIngestError
from shared.exceptions import NotFoundError, UpstreamServiceError
from tests.conftest import PROCEDURE_MD, make_pdf, store_document


async def test_markdown_document_is_indexed(pipeline, repo, storage):
    doc = store_document(repo, storage, PROCEDURE_MD.encode(), "proc.md", title="PROC-OPS-014")

    result = await pipeline.process(doc["id"])

    stored = repo.documents[doc["id"]]
    assert repo.status_history[doc["id"]] == ["processing", "indexed"]
    assert stored["chunk_count"] == result.chunk_count == len(repo.chunks) > 0
    assert stored["error_message"] is None
    ingestion = stored["metadata"]["ingestion"]
    assert ingestion["format"] == "markdown"
    assert ingestion["chunk_size"] == 300 and ingestion["embedding_model"] == "fake-embedder"
    assert stored["metadata"]["original_filename"] == "proc.md"  # no se pierden metadatos previos

    first = repo.chunks[0]
    assert first["chunk_index"] == 0
    assert first["metadata"]["section"].startswith("Paso 1 — Diagnóstico")  # secciones cortas agrupadas
    assert len(first["embedding"]) == 4
    assert first["token_count"] > 0


async def test_pdf_chunks_carry_page(pipeline, repo, storage):
    doc = store_document(repo, storage, make_pdf(["Diagnostico inicial del job de cierre.", "Relanzamiento desde checkpoint."]), "m.pdf")
    await pipeline.process(doc["id"])
    assert {c["metadata"]["page"] for c in repo.chunks} == {1, 2}


async def test_reprocessing_replaces_chunks(pipeline, repo, storage):
    doc = store_document(repo, storage, PROCEDURE_MD.encode(), "proc.md")
    await pipeline.process(doc["id"])
    first_count = len(repo.chunks)
    await pipeline.process(doc["id"], attempt=2)
    assert len(repo.chunks) == first_count
    assert repo.documents[doc["id"]]["metadata"]["ingestion"]["attempt"] == 2


async def test_unknown_document_raises_not_found(pipeline):
    with pytest.raises(NotFoundError):
        await pipeline.process("00000000-0000-0000-0000-000000000000")


async def test_content_error_marks_failed_without_retry(pipeline, repo, storage):
    doc = store_document(repo, storage, make_pdf([""]), "escaneado.pdf")
    with pytest.raises(IngestError) as exc:
        await pipeline.process(doc["id"])
    assert not exc.value.retryable
    assert repo.documents[doc["id"]]["status"] == "failed"
    assert "OCR" in repo.documents[doc["id"]]["error_message"]
    assert repo.chunks == []


async def test_missing_file_is_not_retryable(pipeline, repo):
    doc = repo.add_document(metadata={"original_filename": "x.md"})
    with pytest.raises(IngestError) as exc:
        await pipeline.process(doc["id"])
    assert not exc.value.retryable
    assert repo.documents[doc["id"]]["error_message"] == "El archivo no existe en Storage"


async def test_storage_outage_is_retryable(pipeline, repo, storage):
    doc = store_document(repo, storage, PROCEDURE_MD.encode(), "proc.md")
    storage.fail_download = UpstreamServiceError("Supabase Storage no disponible")
    with pytest.raises(TransientIngestError):
        await pipeline.process(doc["id"])
    assert repo.documents[doc["id"]]["status"] == "failed"
    assert "se reintentará" in repo.documents[doc["id"]]["error_message"]


async def test_unexpected_error_never_leaves_processing(pipeline, repo, storage):
    doc = store_document(repo, storage, PROCEDURE_MD.encode(), "proc.md")
    repo.fail_insert = True
    with pytest.raises(TransientIngestError):
        await pipeline.process(doc["id"])
    assert repo.documents[doc["id"]]["status"] == "failed"
