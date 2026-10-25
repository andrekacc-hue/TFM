from __future__ import annotations

import pytest

from app.core.errors import CorruptDocumentError, EmptyDocumentError, UnsupportedDocumentError
from app.core.loaders import clean_text, content_type_for, load_document
from app.core.loaders.markdown_loader import strip_markdown
from tests.conftest import PROCEDURE_MD, make_docx, make_pdf


def test_pdf_keeps_page_numbers():
    pdf = make_pdf(["Pagina uno: diagnostico del batch de cierre.", "Pagina dos: relanzamiento desde checkpoint."])
    doc = load_document(pdf, "manual.PDF")
    assert doc.format == "pdf"
    assert doc.metadata["pages"] == 2
    assert [s.page for s in doc.sections] == [1, 2]
    assert "relanzamiento" in doc.sections[1].text


def test_pdf_without_text_layer_is_reported_as_scanned():
    with pytest.raises(EmptyDocumentError) as exc:
        load_document(make_pdf([""]), "escaneado.pdf")
    assert "OCR" in exc.value.message


def test_corrupt_pdf():
    with pytest.raises(CorruptDocumentError):
        load_document(b"%PDF-1.4 esto no es un pdf", "roto.pdf")


def test_docx_groups_paragraphs_under_headings_and_reads_tables():
    doc = load_document(make_docx(), "manual.docx")
    by_heading = {s.heading: s.text for s in doc.sections}
    assert by_heading[None].startswith("Introducción")
    assert "código 91" in by_heading["Síntomas"]
    assert "Nivel | Contacto" in by_heading["Escalamiento"]
    assert "N2 | Proveedor switch" in by_heading["Escalamiento"]


def test_corrupt_docx():
    with pytest.raises(CorruptDocumentError):
        load_document(b"no es un zip", "roto.docx")


def test_markdown_sections_and_syntax_removal():
    doc = load_document(PROCEDURE_MD.encode(), "proc.md")
    headings = [s.heading for s in doc.sections]
    assert headings == ["Paso 1 — Diagnóstico", "Paso 2 — Relanzamiento"]
    paso1, paso2 = doc.sections[0].text, doc.sections[1].text
    assert "bloqueantes" in paso1 and "**" not in paso1
    assert "guía" in paso1 and "http://" not in paso1
    assert "restart --from-checkpoint" in paso2  # el contenido de código se conserva
    assert "CIE-201 | Timeout" in paso2
    assert "---" not in paso2


def test_markdown_cp1252_and_txt():
    doc = load_document("Ñandú y acción de contingencia en el cajero automático".encode("cp1252"), "notas.txt")
    assert doc.format == "text"
    assert doc.sections[0].text.startswith("Ñandú")


def test_empty_markdown():
    with pytest.raises(EmptyDocumentError):
        load_document(b"# Solo titulo\n\n", "vacio.md")


@pytest.mark.parametrize("name", ["foto.png", "hoja.xlsx", "sin_extension"])
def test_unsupported_formats(name):
    with pytest.raises(UnsupportedDocumentError):
        content_type_for(name)


def test_content_types():
    assert content_type_for("a.pdf") == "application/pdf"
    assert content_type_for("a.markdown") == "text/markdown"


def test_clean_text_joins_hyphenated_words_and_spaces():
    assert clean_text("transac-\nción   bancaria\n\n\n\nfin") == "transacción bancaria\n\nfin"


def test_strip_markdown_inline():
    assert strip_markdown("> **Nota**: usar `kill -9` solo con [aprobación](x)") == "Nota: usar kill -9 solo con aprobación"
