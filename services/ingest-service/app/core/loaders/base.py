"""Tipos comunes de los loaders."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import EmptyDocumentError

MIN_TEXT_CHARS = 20

_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_SPACES = re.compile(r"[ \t ]+")
_MANY_NEWLINES = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class Section:
    """Bloque de texto con su procedencia.

    Attributes:
        text: Texto limpio.
        page: Página (1-based) en PDF; ``None`` en otros formatos.
        heading: Encabezado de la sección a la que pertenece, si existe.
    """

    text: str
    page: int | None = None
    heading: str | None = None


@dataclass
class LoadedDocument:
    """Resultado de la extracción."""

    sections: list[Section]
    format: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return sum(len(s.text) for s in self.sections)

    def ensure_text(self) -> LoadedDocument:
        """Falla si no hay texto útil (p. ej. PDF escaneado sin capa de texto)."""
        if self.char_count < MIN_TEXT_CHARS:
            hint = " El PDF parece escaneado: requiere OCR." if self.format == "pdf" else ""
            raise EmptyDocumentError(f"El documento no contiene texto extraíble.{hint}")
        return self


def clean_text(text: str) -> str:
    """Normaliza el texto extraído.

    * une palabras cortadas con guion al final de línea ("transac-\\nción");
    * colapsa espacios y tabuladores;
    * deja como máximo una línea en blanco entre párrafos.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = "\n".join(_SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return _MANY_NEWLINES.sub("\n\n", text).strip()
