"""Configuración del ingest-service."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from shared.config import BaseServiceSettings


class IngestSettings(BaseServiceSettings):
    """Parámetros de ingesta, chunking y del worker de Redis Streams."""

    service_name: str = "ingest-service"

    # --- Subida ---
    storage_bucket: str = "documents"
    max_upload_mb: int = Field(50, ge=1, le=50)

    # --- Chunking (en caracteres; ~4 caracteres por token en español) ---
    chunk_size: int = Field(700, ge=200, le=4000)
    chunk_overlap: int = Field(120, ge=0, le=1000)
    # Antepone "título · sección" al texto que se vectoriza (no al que se guarda)
    contextual_embeddings: bool = True

    # --- Embeddings / escritura ---
    embed_batch_size: int = Field(32, ge=1, le=256)
    insert_batch_size: int = Field(100, ge=1, le=1000)

    # --- Redis Streams ---
    redis_url: str | None = "redis://127.0.0.1:6379/0"
    redis_stream_ingest: str = "documents.ingest"
    redis_consumer_group: str = "ingest-workers"
    worker_enabled: bool = True
    worker_block_ms: int = Field(5000, ge=100, le=60000)
    worker_max_attempts: int = Field(3, ge=1, le=10)
    # Mensajes sin ACK más antiguos que esto se reclaman (worker caído a mitad de proceso)
    worker_claim_idle_ms: int = Field(300_000, ge=1000)
    stream_maxlen: int = Field(10_000, ge=100)

    # --- Outbox (documentos registrados por las Edge Functions) ---
    outbox_enabled: bool = True
    outbox_interval_seconds: float = Field(15.0, ge=1.0, le=600.0)
    outbox_batch_size: int = Field(10, ge=1, le=100)
    # Un documento "pending" ya encolado se reencola si nadie lo procesó en este tiempo
    outbox_stale_seconds: int = Field(300, ge=30)

    preload_models: bool = True


@lru_cache
def get_settings() -> IngestSettings:
    """Configuración (singleton) leída del entorno / ``.env``."""
    return IngestSettings()  # type: ignore[call-arg]
