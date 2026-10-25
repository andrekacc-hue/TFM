"""Fragmentación recursiva de texto con solapamiento.

Estrategia (similar a ``RecursiveCharacterTextSplitter``, sin depender de LangChain):

1. Cada :class:`Section` se trocea por separado, así un chunk nunca mezcla dos páginas
   o dos secciones y su cita es exacta.
2. El texto se divide por el separador más "fuerte" posible (párrafo → línea → frase →
   palabra) hasta que cada pieza cabe en ``chunk_size``.
3. Las piezas se reagrupan de forma voraz hasta ``chunk_size`` y cada chunk nuevo arranca
   con la cola (~``chunk_overlap`` caracteres, alineada a palabra) del anterior, para no
   perder contexto en las fronteras.

Las unidades son caracteres: en español ~4 caracteres por token, así 700 caracteres son
~175 tokens, dentro de ``EMBEDDING_MAX_SEQ_LENGTH=256``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.core.loaders.base import Section

SEPARATORS = ("\n\n", "\n", ". ", "; ", ", ", " ")
CHARS_PER_TOKEN = 4.0


@dataclass(frozen=True)
class Chunk:
    """Fragmento listo para vectorizar."""

    index: int
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def estimated_tokens(self) -> int:
        return math.ceil(len(self.content) / CHARS_PER_TOKEN)


class RecursiveChunker:
    """Divide secciones en chunks de tamaño acotado con solapamiento.

    Args:
        chunk_size: Tamaño máximo en caracteres.
        chunk_overlap: Caracteres de contexto que se repiten entre chunks consecutivos.
        min_chunk_chars: Los restos más cortos se funden con el chunk anterior.
    """

    def __init__(self, chunk_size: int = 700, chunk_overlap: int = 120, *, min_chunk_chars: int = 80) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap debe ser menor que chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_chars = min_chunk_chars

    # ------------------------------------------------------------------
    def split_sections(self, sections: Iterable[Section]) -> list[Chunk]:
        """Trocea todas las secciones y numera los chunks de forma global."""
        chunks: list[Chunk] = []
        for section in sections:
            for text in self.split_text(section.text):
                metadata: dict[str, Any] = {"char_count": len(text)}
                if section.page is not None:
                    metadata["page"] = section.page
                if section.heading:
                    metadata["section"] = section.heading
                chunks.append(Chunk(index=len(chunks), content=text, metadata=metadata))
        return chunks

    def split_text(self, text: str) -> list[str]:
        """Trocea un texto en chunks de como máximo ``chunk_size`` caracteres."""
        text = text.strip()
        if not text:
            return []
        if len(text) <= self.chunk_size:
            return [text]
        pieces = self._split_recursive(text, SEPARATORS)
        return self._merge(pieces)

    # ------------------------------------------------------------------
    def _split_recursive(self, text: str, separators: tuple[str, ...]) -> list[str]:
        """Divide hasta que cada pieza cabe en ``chunk_size`` (conservando el separador)."""
        if len(text) <= self.chunk_size:
            return [text]
        if not separators:
            # Sin separadores útiles (p. ej. una URL enorme): corte duro
            return [text[i : i + self.chunk_size] for i in range(0, len(text), self.chunk_size)]

        separator, rest = separators[0], separators[1:]
        if separator not in text:
            return self._split_recursive(text, rest)

        parts = text.split(separator)
        pieces: list[str] = []
        for i, part in enumerate(parts):
            piece = part + (separator if i < len(parts) - 1 else "")
            if not piece.strip():
                continue
            pieces.extend(self._split_recursive(piece, rest) if len(piece) > self.chunk_size else [piece])
        return pieces

    def _overlap_tail(self, text: str) -> str:
        """Últimos ~``chunk_overlap`` caracteres, empezando en un límite de palabra."""
        if self.chunk_overlap == 0 or len(text) <= self.chunk_overlap:
            return "" if self.chunk_overlap == 0 else text
        tail = text[-self.chunk_overlap :]
        space = tail.find(" ")
        return tail[space + 1 :] if 0 <= space < len(tail) - 1 else tail

    def _merge(self, pieces: list[str]) -> list[str]:
        chunks: list[str] = []
        current = ""  # chunk en construcción (solapamiento + piezas nuevas)
        fresh = ""  # parte de ``current`` que no es solapamiento
        for piece in pieces:
            if fresh and len(current) + len(piece) > self.chunk_size:
                chunks.append(current)
                tail = self._overlap_tail(current)
                # El solapamiento nunca debe hacer que el siguiente chunk se pase de tamaño
                current = tail if len(tail) + len(piece) <= self.chunk_size else ""
                fresh = ""
            current += piece
            fresh += piece
        if fresh.strip():
            # Un resto muy corto se funde con el chunk anterior si cabe (sin repetir el solapamiento)
            if chunks and len(fresh.strip()) < self.min_chunk_chars and len(chunks[-1]) + len(fresh) <= self.chunk_size:
                chunks[-1] += fresh
            else:
                chunks.append(current)
        return [c.strip() for c in chunks if c.strip()]
