"""Pipeline de ingesta de un documento.

    tfm.documents (pending) ─► processing ─► descarga de Storage ─► extracción (loader)
        ─► chunking ─► embeddings ─► reemplazo de tfm.chunks ─► indexed (+ métricas)
                                                            └─► failed (+ error_message)

Supabase Realtime publica cada cambio de ``status``, así el portal ve el progreso en vivo.
El reemplazo de chunks es idempotente: reprocesar un documento borra los anteriores.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any
from uuid import UUID

from app.core.chunker import Chunk, RecursiveChunker
from app.core.embedder import BatchEmbedder
from app.core.errors import IngestError, TransientIngestError
from app.core.loaders import load_document
from shared.exceptions import NotFoundError, UpstreamServiceError
from shared.logging import get_logger
from shared.supabase_client import SupabaseRepository, SupabaseStorage

logger = get_logger(__name__)


@dataclass(frozen=True)
class IngestResult:
    """Resumen de una ingesta correcta."""

    document_id: UUID
    chunk_count: int
    char_count: int
    duration_ms: int
    format: str


class IngestionPipeline:
    """Procesa un documento registrado en ``tfm.documents``.

    Args:
        repository: Acceso a PostgREST (service_role).
        storage: Acceso a Supabase Storage.
        chunker: Fragmentador.
        embedder: Vectorizador por lotes.
        bucket: Bucket de Storage.
        insert_batch_size: Filas por inserción en ``tfm.chunks``.
    """

    def __init__(
        self,
        repository: SupabaseRepository,
        storage: SupabaseStorage,
        chunker: RecursiveChunker,
        embedder: BatchEmbedder,
        *,
        bucket: str = "documents",
        insert_batch_size: int = 100,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.chunker = chunker
        self.embedder = embedder
        self.bucket = bucket
        self.insert_batch_size = insert_batch_size

    async def process(self, document_id: UUID | str, *, attempt: int = 1) -> IngestResult:
        """Ingesta completa de un documento.

        Args:
            document_id: Id en ``tfm.documents``.
            attempt: Intento actual (se registra en los metadatos).

        Raises:
            NotFoundError: El documento no existe (se descarta el mensaje).
            IngestError: Error del contenido (no se reintenta) o transitorio
                (``retryable=True``); en ambos casos el documento queda ``failed``.
        """
        started = time.perf_counter()
        document = await self._get_document(str(document_id))
        doc_id = str(document["id"])
        log = logger.bind(document_id=doc_id, attempt=attempt)

        try:
            await self._set_status(doc_id, "processing", error_message=None)

            filename = (document.get("metadata") or {}).get("original_filename") or PurePath(document["storage_path"]).name
            content = await self.storage.download(self.bucket, document["storage_path"])
            loaded = load_document(content, filename)
            chunks = self.chunker.split_sections(loaded.sections)
            vectors = await self.embedder.embed_chunks(chunks, document["title"])
            await self._replace_chunks(doc_id, chunks, vectors)

            duration_ms = int((time.perf_counter() - started) * 1000)
            metadata = {
                **(document.get("metadata") or {}),
                "ingestion": {
                    "format": loaded.format,
                    **loaded.metadata,
                    "chunks": len(chunks),
                    "chars": loaded.char_count,
                    "avg_chunk_chars": round(sum(len(c.content) for c in chunks) / max(len(chunks), 1)),
                    "chunk_size": self.chunker.chunk_size,
                    "chunk_overlap": self.chunker.chunk_overlap,
                    "embedding_model": self.embedder.model_name,
                    "duration_ms": duration_ms,
                    "attempt": attempt,
                    "finished_at": datetime.now(UTC).isoformat(),
                },
            }
            await self._set_status(doc_id, "indexed", chunk_count=len(chunks), metadata=metadata)
            log.info("document_indexed", chunks=len(chunks), chars=loaded.char_count, duration_ms=duration_ms)
            return IngestResult(UUID(doc_id), len(chunks), loaded.char_count, duration_ms, loaded.format)

        except IngestError as exc:
            await self._fail(doc_id, exc.message, retryable=exc.retryable)
            log.warning("document_failed", error=exc.message, retryable=exc.retryable)
            raise
        except NotFoundError as exc:
            # El archivo no está en Storage: reintentar no lo hará aparecer
            await self._fail(doc_id, "El archivo no existe en Storage", retryable=False)
            log.warning("document_file_missing", path=document["storage_path"])
            raise IngestError("El archivo no existe en Storage", code="file_missing", details=exc.details) from exc
        except UpstreamServiceError as exc:
            # Storage o PostgREST caídos: reintentable
            await self._fail(doc_id, f"Error temporal: {exc.message}", retryable=True)
            log.warning("document_failed_transient", error=exc.message)
            raise TransientIngestError(exc.message, details=exc.details) from exc
        except Exception as exc:
            # Inesperado: nunca dejar el documento en "processing" para siempre
            await self._fail(doc_id, f"Error inesperado: {type(exc).__name__}", retryable=True)
            log.exception("document_failed_unexpected")
            raise TransientIngestError(f"Error inesperado: {exc}") from exc

    # ------------------------------------------------------------------
    async def _get_document(self, document_id: str) -> dict[str, Any]:
        rows = await self.repository.select(
            "documents",
            {"select": "id,title,storage_path,area,status,metadata", "id": f"eq.{document_id}", "limit": "1"},
        )
        if not rows:
            raise NotFoundError("Documento no encontrado", details={"document_id": document_id})
        return rows[0]

    async def _set_status(self, document_id: str, status: str, **values: Any) -> None:
        await self.repository.update("documents", {"id": f"eq.{document_id}"}, {"status": status, **values})

    async def _fail(self, document_id: str, message: str, *, retryable: bool) -> None:
        suffix = " (se reintentará)" if retryable else ""
        try:
            await self._set_status(document_id, "failed", error_message=f"{message}{suffix}"[:1000])
        except Exception as exc:  # noqa: BLE001 - no ocultar el error original
            logger.error("status_update_failed", document_id=document_id, error=str(exc))

    async def _replace_chunks(self, document_id: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        await self.repository.delete("chunks", {"document_id": f"eq.{document_id}"})
        rows = [
            {
                "document_id": document_id,
                "chunk_index": chunk.index,
                "content": chunk.content,
                "embedding": vector,
                "token_count": chunk.estimated_tokens,
                "metadata": chunk.metadata,
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        for start in range(0, len(rows), self.insert_batch_size):
            await self.repository.insert("chunks", rows[start : start + self.insert_batch_size], returning=False)
