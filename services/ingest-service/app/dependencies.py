"""Composición de dependencias del ingest-service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, Header, Request

from app.config import IngestSettings
from app.core.chunker import RecursiveChunker
from app.core.embedder import BatchEmbedder
from app.core.pipeline import IngestionPipeline
from app.core.queue import IngestQueue
from app.workers.stream_consumer import StreamConsumer
from shared.auth import SupabaseJWTVerifier, resolve_user_context, verify_internal_api_key
from shared.embeddings import SentenceTransformerEmbedder
from shared.redis_client import create_stream_client
from shared.schemas import UserContext
from shared.supabase_client import SupabaseRepository, SupabaseStorage


@dataclass
class Container:
    """Dependencias creadas al arrancar el servicio."""

    settings: IngestSettings
    repository: SupabaseRepository
    storage: SupabaseStorage
    redis: Any
    queue: IngestQueue
    embedder: Any
    pipeline: IngestionPipeline
    consumer: StreamConsumer
    jwt_verifier: SupabaseJWTVerifier | None = None
    models_ready: bool = field(default=False)

    async def aclose(self) -> None:
        await self.repository.aclose()
        await self.storage.aclose()
        await self.redis.aclose()


def build_container(settings: IngestSettings) -> Container:
    """Construye el grafo de dependencias."""
    service_key = settings.supabase_service_role_key.get_secret_value()
    repository = SupabaseRepository(
        settings.supabase_url,
        service_key,
        settings.supabase_anon_key.get_secret_value(),
        schema=settings.supabase_schema,
        timeout=settings.supabase_timeout_seconds,
    )
    storage = SupabaseStorage(settings.supabase_url, service_key)
    if not settings.redis_url:
        raise RuntimeError("El ingest-service requiere REDIS_URL (Redis Streams)")
    redis = create_stream_client(settings.redis_url, block_ms=settings.worker_block_ms)
    queue = IngestQueue(redis, settings.redis_stream_ingest, settings.redis_consumer_group, maxlen=settings.stream_maxlen)
    embedder = SentenceTransformerEmbedder(
        settings.embedding_model, settings.embedding_dim, max_seq_length=settings.embedding_max_seq_length
    )
    pipeline = IngestionPipeline(
        repository,
        storage,
        RecursiveChunker(settings.chunk_size, settings.chunk_overlap),
        BatchEmbedder(embedder, batch_size=settings.embed_batch_size, contextual=settings.contextual_embeddings),
        bucket=settings.storage_bucket,
        insert_batch_size=settings.insert_batch_size,
    )
    consumer = StreamConsumer(
        queue,
        pipeline,
        block_ms=settings.worker_block_ms,
        max_attempts=settings.worker_max_attempts,
        claim_idle_ms=settings.worker_claim_idle_ms,
    )
    verifier = SupabaseJWTVerifier(
        settings.supabase_url,
        settings.supabase_jwt_secret.get_secret_value() if settings.supabase_jwt_secret else None,
    )
    return Container(settings, repository, storage, redis, queue, embedder, pipeline, consumer, verifier)


# ----------------------------------------------------------------------
def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


def require_internal_key(container: ContainerDep, x_internal_api_key: Annotated[str | None, Header()] = None) -> None:
    """Solo el api-gateway (u otro servicio interno) puede invocar este servicio."""
    verify_internal_api_key(x_internal_api_key, container.settings.internal_api_key.get_secret_value())


def get_user_context(
    container: ContainerDep,
    authorization: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header()] = None,
    x_user_area: Annotated[str | None, Header()] = None,
    x_user_role: Annotated[str | None, Header()] = None,
) -> UserContext:
    """Usuario de la petición: JWT verificado o cabeceras ``X-User-*`` del gateway."""
    return resolve_user_context(
        authorization=authorization,
        x_user_id=x_user_id,
        x_user_area=x_user_area,
        x_user_role=x_user_role,
        verifier=container.jwt_verifier,
    )


UserDep = Annotated[UserContext, Depends(get_user_context)]
