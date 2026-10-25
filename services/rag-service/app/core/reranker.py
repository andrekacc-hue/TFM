"""Reranking de candidatos con un cross-encoder.

El retrieval vectorial (bi-encoder) es rápido pero aproximado; el cross-encoder lee
pregunta y fragmento juntos y ordena con más precisión los ~20 candidatos para quedarse
con los 5 mejores que entran en el prompt.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, Protocol

from app.core.retriever import RetrievedChunk
from shared.logging import get_logger

logger = get_logger(__name__)


class Reranker(Protocol):
    """Interfaz de un reranker."""

    async def rerank(self, question: str, chunks: Sequence[RetrievedChunk], top_k: int) -> list[RetrievedChunk]: ...


class SimilarityReranker:
    """Reranker nulo: conserva el orden por similitud coseno (``RERANK_ENABLED=false``)."""

    async def rerank(self, question: str, chunks: Sequence[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
        return sorted(chunks, key=lambda c: c.similarity, reverse=True)[:top_k]


class CrossEncoderReranker:
    """Reranker con ``sentence_transformers.CrossEncoder``.

    Args:
        model_name: Modelo de Hugging Face.
        model: Instancia ya cargada (inyectable en tests).
    """

    def __init__(self, model_name: str, *, model: Any | None = None) -> None:
        self.model_name = model_name
        self._model = model

    def load(self) -> None:
        """Carga el modelo (descarga ~90 MB la primera vez)."""
        if self._model is not None:
            return
        from sentence_transformers import CrossEncoder

        logger.info("rerank_model_loading", model=self.model_name)
        self._model = CrossEncoder(self.model_name)
        logger.info("rerank_model_loaded", model=self.model_name)

    def _score(self, question: str, chunks: Sequence[RetrievedChunk]) -> list[float]:
        self.load()
        assert self._model is not None
        pairs = [(question, chunk.content) for chunk in chunks]
        return [float(s) for s in self._model.predict(pairs, show_progress_bar=False)]

    async def rerank(self, question: str, chunks: Sequence[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
        """Puntúa cada (pregunta, fragmento) y devuelve los ``top_k`` mejores."""
        if not chunks:
            return []
        scores = await asyncio.to_thread(self._score, question, chunks)
        scored = [chunk.model_copy(update={"rerank_score": score}) for chunk, score in zip(chunks, scores, strict=True)]
        scored.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        return scored[:top_k]
