"""Embeddings de texto compartidos por ingest-service (documentos) y rag-service (consultas).

Ambos servicios DEBEN usar el mismo modelo: los vectores de la consulta y de los chunks
tienen que vivir en el mismo espacio (384 dimensiones, normalizados para coseno).
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from shared.logging import get_logger

logger = get_logger(__name__)


class Embedder(Protocol):
    """Interfaz de un modelo de embeddings."""

    model_name: str
    dimension: int

    async def embed_query(self, text: str) -> list[float]: ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEmbedder:
    """Embeddings locales con ``sentence-transformers`` (CPU por defecto).

    El modelo se carga de forma diferida en el primer uso (o con :meth:`load`), y la
    inferencia se ejecuta en un hilo para no bloquear el event loop.

    Args:
        model_name: Modelo de Hugging Face.
        dimension: Dimensión esperada (se valida al cargar).
        device: ``cpu``, ``cuda`` o ``None`` (autodetección).
        batch_size: Tamaño de lote para documentos.
    """

    def __init__(
        self,
        model_name: str,
        dimension: int = 384,
        *,
        device: str | None = None,
        batch_size: int = 32,
    ) -> None:
        self.model_name = model_name
        self.dimension = dimension
        self.device = device
        self.batch_size = batch_size
        self._model: Any | None = None

    def load(self) -> None:
        """Carga el modelo (descarga la primera vez, ~470 MB) y valida la dimensión."""
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer

        logger.info("embedding_model_loading", model=self.model_name)
        model = SentenceTransformer(self.model_name, device=self.device)
        # sentence-transformers >= 5 renombró el método
        get_dim = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
        actual = get_dim()
        if actual != self.dimension:
            raise ValueError(
                f"El modelo {self.model_name} produce {actual} dimensiones; "
                f"EMBEDDING_DIM={self.dimension}. Deben coincidir con vector({self.dimension})."
            )
        self._model = model
        logger.info("embedding_model_loaded", model=self.model_name, dim=actual)

    def _encode(self, texts: list[str]) -> list[list[float]]:
        self.load()
        assert self._model is not None
        vectors = self._model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [vector.astype(float).tolist() for vector in vectors]

    async def embed_query(self, text: str) -> list[float]:
        """Vector normalizado de una consulta."""
        vectors = await asyncio.to_thread(self._encode, [text])
        return vectors[0]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Vectores normalizados de varios fragmentos."""
        if not texts:
            return []
        return await asyncio.to_thread(self._encode, texts)
