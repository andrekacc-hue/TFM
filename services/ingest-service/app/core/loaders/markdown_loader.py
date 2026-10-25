"""Extracción de texto de Markdown y texto plano.

El Markdown se divide por encabezados (``#``); se elimina la sintaxis de formato pero se
conserva el contenido (incluido el de bloques de código, útil en procedimientos con comandos).
"""

from __future__ import annotations

import re

from app.core.errors import CorruptDocumentError
from app.core.loaders.base import LoadedDocument, Section, clean_text

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|~~)(?=\S)(.+?)(?<=\S)\1")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_HTML_TAG = re.compile(r"<[^>]+>")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_QUOTE = re.compile(r"^\s*>\s?")


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CorruptDocumentError("No se pudo decodificar el texto")  # pragma: no cover - latin-1 nunca falla


def strip_markdown(line: str) -> str:
    """Quita la sintaxis Markdown de una línea conservando el texto."""
    if _TABLE_RULE.match(line):
        return ""
    line = _QUOTE.sub("", line)
    line = _IMAGE.sub(r"\1", line)
    line = _LINK.sub(r"\1", line)
    line = _INLINE_CODE.sub(r"\1", line)
    line = _EMPHASIS.sub(r"\2", line)
    line = _HTML_TAG.sub("", line)
    if line.strip().startswith("|"):
        line = " | ".join(cell.strip() for cell in line.strip().strip("|").split("|"))
    return line


def load_markdown(content: bytes) -> LoadedDocument:
    """Divide un Markdown en secciones por encabezado."""
    sections: list[Section] = []
    heading: str | None = None
    buffer: list[str] = []
    in_code = False

    def flush() -> None:
        text = clean_text("\n".join(buffer))
        if text:
            sections.append(Section(text=text, heading=heading))
        buffer.clear()

    for line in _decode(content).splitlines():
        if _FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            buffer.append(line)
            continue
        match = _HEADING.match(line)
        if match:
            flush()
            heading = strip_markdown(match.group(2)).strip()
            continue
        buffer.append(strip_markdown(line))
    flush()

    return LoadedDocument(sections, "markdown").ensure_text()


def load_text(content: bytes) -> LoadedDocument:
    """Texto plano: una única sección."""
    text = clean_text(_decode(content))
    return LoadedDocument([Section(text=text)] if text else [], "text").ensure_text()
