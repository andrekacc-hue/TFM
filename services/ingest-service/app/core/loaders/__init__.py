"""Extracción de texto por formato.

Cada loader devuelve un :class:`LoadedDocument` con secciones que conservan la página
(PDF) y el encabezado (DOCX/Markdown), para que las citas puedan señalar la sección.
"""

from __future__ import annotations

from pathlib import PurePath

from app.core.errors import UnsupportedDocumentError
from app.core.loaders.base import LoadedDocument, Section, clean_text
from app.core.loaders.docx_loader import load_docx
from app.core.loaders.markdown_loader import load_markdown, load_text
from app.core.loaders.pdf_loader import load_pdf

# extensión -> (loader, content-type)
SUPPORTED_FORMATS = {
    ".pdf": (load_pdf, "application/pdf"),
    ".docx": (load_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".md": (load_markdown, "text/markdown"),
    ".markdown": (load_markdown, "text/markdown"),
    ".txt": (load_text, "text/plain"),
}


def content_type_for(filename: str) -> str:
    """Content-Type a usar al subir a Storage."""
    extension = PurePath(filename).suffix.lower()
    if extension not in SUPPORTED_FORMATS:
        raise UnsupportedDocumentError(
            f"Formato '{extension or 'sin extensión'}' no soportado. Usa PDF, DOCX, Markdown o TXT.",
            details={"supported": sorted(SUPPORTED_FORMATS)},
        )
    return SUPPORTED_FORMATS[extension][1]


def load_document(content: bytes, filename: str) -> LoadedDocument:
    """Extrae el texto de un archivo según su extensión.

    Args:
        content: Bytes del archivo.
        filename: Nombre (se usa la extensión para elegir el loader).

    Raises:
        UnsupportedDocumentError: Formato no soportado.
        EmptyDocumentError: Sin texto extraíble.
        CorruptDocumentError: Archivo ilegible.
    """
    content_type_for(filename)
    loader = SUPPORTED_FORMATS[PurePath(filename).suffix.lower()][0]
    return loader(content)


__all__ = ["SUPPORTED_FORMATS", "LoadedDocument", "Section", "clean_text", "content_type_for", "load_document"]
