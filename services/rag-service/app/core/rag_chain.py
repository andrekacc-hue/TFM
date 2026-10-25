"""Orquestación del pipeline RAG.

    pregunta ─► guardrails de entrada ─► embedding + match_chunks (pgvector)
             ─► reranking (cross-encoder) ─► umbrales de abstención
             ─► prompt + LLM (adapter) ─► guardrails de salida
             ─► persistencia en tfm.queries ─► respuesta con fuentes

Se implementa como una cadena explícita (sin LangChain): cada etapa es una clase con una
interfaz pequeña, inyectable y medible por separado, lo que simplifica los tests y la
trazabilidad de latencias por etapa que exige la evaluación.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.generator import Generator
from app.core.guardrails import check_input, check_output
from app.core.prompts import ABSTENTION_MESSAGE, SECURITY_REFUSAL_MESSAGE
from app.core.reranker import Reranker
from app.core.retriever import RetrievedChunk, Retriever
from shared.logging import get_logger, get_trace_id
from shared.schemas import QueryRequest, QueryResponse, SourceCitation, Timings, Usage, UserContext
from shared.supabase_client import SupabaseRepository

logger = get_logger(__name__)

EXCERPT_CHARS = 400


@dataclass(frozen=True)
class RagParams:
    """Parámetros de recuperación y abstención."""

    top_k_retrieval: int = 20
    top_k_rerank: int = 5
    similarity_threshold: float = 0.35
    rerank_min_score: float | None = None


class _Stopwatch:
    def __init__(self) -> None:
        self.start = time.perf_counter()
        self._last = self.start

    def lap(self) -> float:
        now = time.perf_counter()
        elapsed, self._last = (now - self._last) * 1000, now
        return round(elapsed, 1)

    def total(self) -> float:
        return round((time.perf_counter() - self.start) * 1000, 1)


class RagChain:
    """Pipeline RAG completo.

    Args:
        retriever: Recuperación vectorial.
        reranker: Reordenación de candidatos.
        generator: Generación con el LLM.
        repository: Persistencia de consultas (service_role).
        params: Umbrales y tamaños.
    """

    def __init__(
        self,
        retriever: Retriever,
        reranker: Reranker,
        generator: Generator,
        repository: SupabaseRepository,
        params: RagParams | None = None,
    ) -> None:
        self.retriever = retriever
        self.reranker = reranker
        self.generator = generator
        self.repository = repository
        self.params = params or RagParams()

    async def run(self, request: QueryRequest, user: UserContext | None = None) -> QueryResponse:
        """Responde una consulta.

        Args:
            request: Pregunta, canal y filtros.
            user: Usuario autenticado (resuelto por el api-gateway) o ``None``.

        Returns:
            Respuesta con fuentes, métricas y ``query_id``.
        """
        user = user or UserContext()
        watch = _Stopwatch()
        timings = Timings()
        warnings: list[str] = []

        # 1. Guardrails de entrada
        guard = check_input(request.question)
        timings.guardrails_ms = watch.lap()
        if guard.masked:
            warnings.append("datos_sensibles_enmascarados:" + ",".join(guard.masked))
        if not guard.allowed:
            logger.warning("query_blocked", reason=guard.reason)
            return await self._finish(
                request, user, guard.question, timings, watch, warnings,
                answer=SECURITY_REFUSAL_MESSAGE, abstention_reason=f"guardrail:{guard.reason}",
            )

        # 2. Recuperación (RLS si hay JWT de usuario; filtro de área explícito si no)
        candidates = await self.retriever.retrieve(
            guard.question,
            top_k=self.params.top_k_retrieval,
            threshold=self.params.similarity_threshold,
            area=request.area,
            user_jwt=user.access_token,
        )
        timings.retrieval_ms = watch.lap()
        if not candidates:
            return await self._finish(
                request, user, guard.question, timings, watch, warnings,
                answer=ABSTENTION_MESSAGE, abstention_reason="sin_contexto_relevante",
            )

        # 3. Reranking
        top_k = request.top_k or self.params.top_k_rerank
        chunks = await self.reranker.rerank(guard.question, candidates, top_k)
        timings.rerank_ms = watch.lap()
        best = chunks[0].rerank_score if chunks else None
        if self.params.rerank_min_score is not None and (best is None or best < self.params.rerank_min_score):
            return await self._finish(
                request, user, guard.question, timings, watch, warnings,
                answer=ABSTENTION_MESSAGE, abstention_reason="relevancia_insuficiente",
            )

        # 4. Generación
        result = await self.generator.generate(guard.question, chunks)
        timings.generation_ms = watch.lap()

        # 5. Guardrails de salida
        output = check_output(result.text)
        warnings.extend(output.warnings)

        return await self._finish(
            request, user, guard.question, timings, watch, warnings,
            answer=output.answer,
            abstention_reason="modelo_sin_evidencia" if output.abstained else None,
            chunks=[] if output.abstained else chunks,
            llm=(result.provider, result.model),
            usage=Usage(tokens_input=result.tokens_input, tokens_output=result.tokens_output),
        )

    # ------------------------------------------------------------------
    async def _finish(
        self,
        request: QueryRequest,
        user: UserContext,
        question: str,
        timings: Timings,
        watch: _Stopwatch,
        warnings: list[str],
        *,
        answer: str,
        abstention_reason: str | None = None,
        chunks: list[RetrievedChunk] | None = None,
        llm: tuple[str, str] | None = None,
        usage: Usage | None = None,
    ) -> QueryResponse:
        timings.total_ms = watch.total()
        sources = [_to_citation(i, chunk) for i, chunk in enumerate(chunks or [], start=1)]
        response = QueryResponse(
            answer=answer,
            sources=sources,
            abstained=abstention_reason is not None,
            abstention_reason=abstention_reason,
            llm_provider=llm[0] if llm else None,
            llm_model=llm[1] if llm else None,
            usage=usage or Usage(),
            timings=timings,
            warnings=warnings,
            trace_id=get_trace_id(),
        )
        response.query_id = await self._persist(request, user, question, response)
        logger.info(
            "query_answered",
            query_id=str(response.query_id) if response.query_id else None,
            abstained=response.abstained,
            reason=abstention_reason,
            sources=len(sources),
            total_ms=timings.total_ms,
            generation_ms=timings.generation_ms,
            warnings=warnings or None,
        )
        return response

    async def _persist(
        self, request: QueryRequest, user: UserContext, question: str, response: QueryResponse
    ) -> UUID | None:
        """Registra la consulta en ``tfm.queries``. Un fallo aquí no invalida la respuesta."""
        row: dict[str, Any] = {
            "user_id": str(user.user_id) if user.user_id else None,
            "channel": request.channel,
            "question": question,
            "answer": response.answer,
            "sources": [s.model_dump(mode="json", exclude={"excerpt"}) for s in response.sources],
            "latency_ms": int(response.timings.total_ms),
            "tokens_input": response.usage.tokens_input,
            "tokens_output": response.usage.tokens_output,
            "abstained": response.abstained,
            "abstention_reason": response.abstention_reason,
            "timings": response.timings.model_dump(),
            "llm_provider": response.llm_provider,
            "llm_model": response.llm_model,
            "trace_id": response.trace_id,
        }
        try:
            created = await self.repository.insert("queries", row)
            return UUID(created[0]["id"]) if created else None
        except Exception as exc:  # noqa: BLE001 - la respuesta ya está generada
            logger.error("query_persist_failed", error=str(exc))
            response.warnings.append("consulta_no_registrada")
            return None


def _to_citation(index: int, chunk: RetrievedChunk) -> SourceCitation:
    excerpt = chunk.content.strip()
    if len(excerpt) > EXCERPT_CHARS:
        excerpt = excerpt[:EXCERPT_CHARS].rstrip() + "…"
    return SourceCitation(
        index=index,
        document_id=chunk.document_id,
        chunk_id=chunk.chunk_id,
        title=chunk.document_title,
        source_type=chunk.source_type,
        chunk_index=chunk.chunk_index,
        section=chunk.section,
        page=chunk.page,
        similarity=round(chunk.similarity, 4),
        rerank_score=round(chunk.rerank_score, 4) if chunk.rerank_score is not None else None,
        excerpt=excerpt,
    )
