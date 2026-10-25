"""Extracción de texto de PDF con ``pypdf`` (una sección por página)."""

from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.errors import CorruptDocumentError
from app.core.loaders.base import LoadedDocument, Section, clean_text


def load_pdf(content: bytes) -> LoadedDocument:
    """Extrae el texto página a página, conservando el número de página.

    Raises:
        CorruptDocumentError: PDF ilegible o cifrado.
        EmptyDocumentError: Sin capa de texto (escaneado).
    """
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise CorruptDocumentError("El PDF está protegido con contraseña")
        pages = [page.extract_text() or "" for page in reader.pages]
    except CorruptDocumentError:
        raise
    except (PdfReadError, ValueError, KeyError, OSError) as exc:
        raise CorruptDocumentError("No se pudo leer el PDF", details={"error": str(exc)}) from exc

    sections = [Section(text=text, page=number) for number, raw in enumerate(pages, start=1) if (text := clean_text(raw))]
    metadata = {"pages": len(pages)}
    if reader.metadata and reader.metadata.title:
        metadata["pdf_title"] = str(reader.metadata.title)
    return LoadedDocument(sections, "pdf", metadata).ensure_text()
