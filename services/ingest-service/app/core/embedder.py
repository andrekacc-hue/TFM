"""Vectorización de chunks por lotes.

Usa el mismo :class:`~shared.embeddings.SentenceTransformerEmbedder` que el rag-service:
consultas y documentos deben compartir modelo, dimensión y ``max_seq_length``.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.chunker import Chunk
from shared.embeddings import Embedder


def embedding_input(chunk: Chunk, title: str, *, contextual: bool = True) -> str:
    """Texto que se vectoriza para un chunk.

    Con ``contextual=True`` se antepone "título · sección" (*contextual chunk headers*):
    un fragmento como "Paso 3 — relanzar desde el checkpoint" no dice de qué sistema habla;
    con la cabecera, su vector queda cerca de preguntas sobre ese documento. El contenido
    que se guarda y se muestra al usuario no cambia.
    """
    if not contextual:
        return chunk.content
    header = " · ".join(part for part in (title, chunk.metadata.get("section")) if part)
    return f"{header}\n{chunk.content}" if header else chunk.content


class BatchEmbedder:
    """Genera embeddings en lotes para acotar memoria y latencia.

    Args:
        embedder: Modelo de embeddings compartido.
        batch_size: Chunks por lote.
        contextual: Activa las cabeceras contextuales.
    """

    def __init__(self, embedder: Embedder, *, batch_size: int = 32, contextual: bool = True) -> None:
        self.embedder = embedder
        self.batch_size = batch_size
        self.contextual = contextual

    @property
    def model_name(self) -> str:
        return self.embedder.model_name

    async def embed_chunks(self, chunks: Sequence[Chunk], title: str) -> list[list[float]]:
        """Vectores normalizados, en el mismo orden que ``chunks``."""
        texts = [embedding_input(c, title, contextual=self.contextual) for c in chunks]
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(await self.embedder.embed_documents(texts[start : start + self.batch_size]))
        if len(vectors) != len(chunks):
            raise RuntimeError(f"Se esperaban {len(chunks)} embeddings y se obtuvieron {len(vectors)}")
        return vectors
