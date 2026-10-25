"""Extracción de texto de Word (.docx) con ``python-docx``.

Agrupa los párrafos bajo el último encabezado (estilos "Heading N" / "Título N") y
convierte las tablas en filas "celda | celda", respetando el orden del documento.
"""

from __future__ import annotations

import io
import zipfile

from docx import Document
from docx.document import Document as DocumentType
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.core.errors import CorruptDocumentError
from app.core.loaders.base import LoadedDocument, Section, clean_text

_HEADING_PREFIXES = ("heading", "título", "titulo", "title")


def _is_heading(paragraph: Paragraph) -> bool:
    style = (paragraph.style.name if paragraph.style is not None else "").lower()
    return style.startswith(_HEADING_PREFIXES)


def _iter_blocks(document: DocumentType):
    """Párrafos y tablas en el orden en que aparecen en el cuerpo."""
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _table_text(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        # python-docx repite el texto de las celdas combinadas
        deduped = [c for i, c in enumerate(cells) if c and (i == 0 or c != cells[i - 1])]
        if deduped:
            rows.append(" | ".join(deduped))
    return "\n".join(rows)


def load_docx(content: bytes) -> LoadedDocument:
    """Extrae secciones de un .docx.

    Raises:
        CorruptDocumentError: Archivo que no es un .docx válido.
        EmptyDocumentError: Sin texto.
    """
    try:
        document = Document(io.BytesIO(content))
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise CorruptDocumentError("No se pudo leer el archivo Word", details={"error": str(exc)}) from exc

    sections: list[Section] = []
    heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        text = clean_text("\n\n".join(buffer))
        if text:
            sections.append(Section(text=text, heading=heading))
        buffer.clear()

    for block in _iter_blocks(document):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            if _is_heading(block):
                flush()
                heading = text
            else:
                buffer.append(text)
        else:
            table = _table_text(block)
            if table:
                buffer.append(table)
    flush()

    headings = sorted({s.heading for s in sections if s.heading})
    return LoadedDocument(sections, "docx", {"headings": len(headings)}).ensure_text()
