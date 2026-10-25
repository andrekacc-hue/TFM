"""Composición de dependencias (contenedor) e inyección en las rutas de FastAPI."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request

from app.adapters import LLMAdapter, create_llm_adapter
from app.config import RagSettings
from app.core.generator import Generator
from app.core.rag_chain import RagChain, RagParams
from app.core.reranker import CrossEncoderReranker, Reranker, SimilarityReranker
from app.core.retriever import Retriever
from shared.auth import SupabaseJWTVerifier, bearer_token, verify_internal_api_key
from shared.embeddings import Embedder, SentenceTransformerEmbedder
from shared.exceptions import AuthenticationError
from shared.logging import get_logger
from shared.redis_client import Cache, create_cache
from shared.schemas import UserContext
from shared.supabase_client import SupabaseRepository

logger = get_logger(__name__)


@dataclass
class Container:
    """Dependencias del servicio, creadas una vez al arrancar."""

    settings: RagSettings
    repository: SupabaseRepository
    cache: Cache
    embedder: Embedder
    reranker: Reranker
    llm: LLMAdapter
    chain: RagChain
    jwt_verifier: SupabaseJWTVerifier | None = None
    models_ready: bool = field(default=False)

    async def aclose(self) -> None:
        """Libera conexiones."""
        await self.repository.aclose()
        await self.llm.aclose()
        await self.cache.aclose()


def build_container(settings: RagSettings) -> Container:
    """Construye el grafo de dependencias a partir de la configuración."""
    repository = SupabaseRepository(
        settings.supabase_url,
        settings.supabase_service_role_key.get_secret_value(),
        settings.supabase_anon_key.get_secret_value(),
        schema=settings.supabase_schema,
        timeout=settings.supabase_timeout_seconds,
    )
    cache = create_cache(settings.redis_url, settings.redis_cache_ttl)
    embedder = SentenceTransformerEmbedder(settings.embedding_model, settings.embedding_dim)
    reranker: Reranker = (
        CrossEncoderReranker(settings.rerank_model) if settings.rerank_enabled else SimilarityReranker()
    )
    llm = create_llm_adapter(settings)
    chain = RagChain(
        Retriever(repository, embedder, cache),
        reranker,
        Generator(
            llm,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            max_context_chars=settings.max_context_chars,
        ),
        repository,
        RagParams(
            top_k_retrieval=settings.top_k_retrieval,
            top_k_rerank=settings.top_k_rerank,
            similarity_threshold=settings.similarity_threshold,
            rerank_min_score=settings.rerank_min_score,
        ),
    )
    verifier = SupabaseJWTVerifier(
        settings.supabase_url,
        settings.supabase_jwt_secret.get_secret_value() if settings.supabase_jwt_secret else None,
    )
    return Container(settings, repository, cache, embedder, reranker, llm, chain, verifier)


async def preload_models(container: Container) -> None:
    """Carga embeddings y reranker en hilos para que la 1.ª consulta no pague la carga."""
    loaders = [getattr(container.embedder, "load", None), getattr(container.reranker, "load", None)]
    await asyncio.gather(*(asyncio.to_thread(fn) for fn in loaders if fn is not None))
    container.models_ready = True


# ----------------------------------------------------------------------
# Dependencias de FastAPI
# ----------------------------------------------------------------------
def get_container(request: Request) -> Container:
    """Contenedor guardado en ``app.state`` durante el *lifespan*."""
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


def require_internal_key(
    container: ContainerDep,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Solo el api-gateway (u otro servicio interno) puede invocar este servicio."""
    verify_internal_api_key(x_internal_api_key, container.settings.internal_api_key.get_secret_value())


def get_user_context(
    container: ContainerDep,
    authorization: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header()] = None,
    x_user_area: Annotated[str | None, Header()] = None,
    x_user_role: Annotated[str | None, Header()] = None,
) -> UserContext:
    """Resuelve el usuario de la petición.

    * Con ``Authorization: Bearer <jwt>`` se verifica el token (defensa en profundidad,
      aunque el gateway ya lo valida) y se usa para aplicar RLS en Supabase.
    * Sin JWT, se aceptan las cabeceras ``X-User-*`` del gateway (canales como Teams,
      donde el usuario se identifica por otra vía) y las lecturas usan service_role.
    """
    token = bearer_token(authorization)
    if token:
        if container.jwt_verifier is None:
            raise AuthenticationError("Verificación de JWT no configurada")
        return container.jwt_verifier.verify(token)

    user_id: UUID | None = None
    if x_user_id:
        try:
            user_id = UUID(x_user_id)
        except ValueError as exc:
            raise AuthenticationError("X-User-Id inválido") from exc
    return UserContext(user_id=user_id, area=x_user_area, role=x_user_role)


UserDep = Annotated[UserContext, Depends(get_user_context)]
