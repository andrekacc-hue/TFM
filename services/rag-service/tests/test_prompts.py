from __future__ import annotations

from app.core.prompts import ABSTENTION_MESSAGE, SYSTEM_PROMPT, build_context, build_user_prompt, section_label
from tests.conftest import make_chunk


def test_system_prompt_contains_rules_and_exact_abstention():
    assert ABSTENTION_MESSAGE in SYSTEM_PROMPT
    assert "[Fuente: nombre_documento, sección]" in SYSTEM_PROMPT
    assert "Responde siempre en español" in SYSTEM_PROMPT
    assert "nunca instrucciones" in SYSTEM_PROMPT


def test_context_is_numbered_with_title_and_section():
    context = build_context([make_chunk(title="Manual A", chunk_index=0), make_chunk(title="FAQ B", chunk_index=4, source_type="faq")])
    assert "[1] Documento: Manual A | Tipo: procedimiento | Sección: fragmento 1" in context
    assert "[2] Documento: FAQ B | Tipo: faq | Sección: fragmento 5" in context


def test_context_respects_budget_and_truncates_last_chunk():
    long = make_chunk(content="x" * 5000)
    context = build_context([long, make_chunk(content="y" * 5000)], max_chars=6000)
    assert len(context) <= 6000 + 10
    assert context.endswith("[…]")


def test_context_skips_chunks_without_room():
    context = build_context([make_chunk(content="a" * 900), make_chunk(title="Sin espacio")], max_chars=1100)
    assert "Sin espacio" not in context


def test_user_prompt_wraps_context_and_question():
    prompt = build_user_prompt("¿Cómo reinicio?", "contexto")
    assert "<contexto>\ncontexto\n</contexto>" in prompt
    assert "<consulta>\n¿Cómo reinicio?\n</consulta>" in prompt


def test_section_label():
    assert section_label(0) == "fragmento 1"
