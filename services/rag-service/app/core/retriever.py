"""Recuperación semántica sobre ``tfm.match_chunks`` (pgvector, similitud coseno)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from shared.embeddings import Embedder
from shared.logging import get_logger
from shared.redis_client import Cache, cache_key
from shared.supabase_client import SupabaseRepository

logger = get_logger(__name__)


class RetrievedChunk(BaseModel):
    """Fragmento recuperado de la base de conocimientos."""

    chunk_id: UUID
    document_id: UUID
    content: str
    similarity: float
    document_title: str
    source_type: str
    chunk_index: int
    rerank_score: float | None = None


class Retriever:
    """Genera el embedding de la pregunta y consulta ``match_chunks``.

    Con el JWT del usuario, la función se ejecuta con sus permisos y RLS limita los
    resultados a su área + ``general`` (o todo, si es admin). Sin JWT (llamadas de
    sistema) se usa service_role y se puede acotar con ``area``.

    Args:
        repository: Repositorio de Supabase.
        embedder: Modelo de embeddings (el mismo que usó la ingesta).
        cache: Cache de embeddings de consultas.
        cache_ttl: TTL de los embeddings cacheados.
    """

    def __init__(
        self,
        repository: SupabaseRepository,
        embedder: Embedder,
        cache: Cache,
        *,
        cache_ttl: int = 86400,
    ) -> None:
        self.repository = repository
        self.embedder = embedder
        self.cache = cache
        self.cache_ttl = cache_ttl

    async def embed(self, question: str) -> list[float]:
        """Embedding de la pregunta, cacheado por (modelo, texto)."""
        key = cache_key("emb", self.embedder.model_name, question.strip().lower())
        cached = await self.cache.get_json(key)
        if cached is not None:
            return cached
        vector = await self.embedder.embed_query(question)
        await self.cache.set_json(key, vector, ttl=self.cache_ttl)
        return vector

    async def retrieve(
        self,
        question: str,
        *,
        top_k: int = 20,
        threshold: float = 0.35,
        area: str | None = None,
        user_jwt: str | None = None,
    ) -> list[RetrievedChunk]:
        """Devuelve los ``top_k`` fragmentos más similares por encima de ``threshold``.

        Args:
            question: Pregunta (ya saneada por los guardrails).
            top_k: Candidatos a recuperar (antes del reranking).
            threshold: Similitud coseno mínima.
            area: Filtro de área explícito.
            user_jwt: JWT del usuario para aplicar RLS.
        """
        vector = await self.embed(question)
        rows = await self.repository.rpc(
            "match_chunks",
            {
                "query_embedding": vector,
                "match_threshold": threshold,
                "match_count": top_k,
                "filter_area": area,
            },
            user_jwt=user_jwt,
        )
        chunks = [RetrievedChunk.model_validate(row) for row in rows]
        logger.info(
            "retrieval_done",
            candidates=len(chunks),
            best_similarity=round(chunks[0].similarity, 4) if chunks else None,
            rls=bool(user_jwt),
            area=area,
        )
        return chunks
