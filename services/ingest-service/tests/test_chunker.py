from __future__ import annotations

import pytest

from app.core.chunker import Chunk, RecursiveChunker
from app.core.embedder import BatchEmbedder, embedding_input
from app.core.loaders.base import Section
from tests.conftest import FakeEmbedder

SENTENCE = "El operador revisa el log del planificador y confirma el estado del job. "


def test_short_text_is_a_single_chunk():
    assert RecursiveChunker(700, 120).split_text("Texto corto.") == ["Texto corto."]
    assert RecursiveChunker(700, 120).split_text("   ") == []


def test_chunks_respect_size_and_overlap():
    chunker = RecursiveChunker(300, 60)
    text = SENTENCE * 30
    chunks = chunker.split_text(text)
    assert len(chunks) > 5
    assert all(len(c) <= 300 for c in chunks)
    # Cada chunk empieza con texto que ya estaba al final del anterior (solapamiento)
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current[:20] in previous


def test_prefers_paragraph_boundaries():
    # Cada párrafo mide ~200 caracteres: con 300 cabe uno por chunk y el corte cae en "\n\n"
    paragraphs = ["Párrafo A " * 20, "Párrafo B " * 20, "Párrafo C " * 20]
    chunks = RecursiveChunker(300, 0).split_text("\n\n".join(paragraphs))
    assert [c.split()[1] for c in chunks] == ["A", "B", "C"]
    assert all(c.count("Párrafo") == 20 for c in chunks)


def test_small_paragraphs_are_packed_together():
    paragraphs = ["Párrafo A " * 20, "Párrafo B " * 20, "Párrafo C " * 20]
    chunks = RecursiveChunker(450, 0).split_text("\n\n".join(paragraphs))
    assert len(chunks) == 2 and "Párrafo B" in chunks[0]


def test_hard_split_for_text_without_separators():
    chunks = RecursiveChunker(200, 20).split_text("x" * 1000)
    assert all(len(c) <= 200 for c in chunks)
    assert sum(len(c) for c in chunks) >= 1000


def test_small_remainder_is_merged_without_duplication():
    chunker = RecursiveChunker(200, 40, min_chunk_chars=80)
    text = ("a" * 95 + ". ") * 2 + "fin."
    chunks = chunker.split_text(text)
    assert chunks[-1].endswith("fin.")
    assert all(len(c) <= 200 for c in chunks)
    assert sum(c.count("fin.") for c in chunks) == 1


def test_sections_keep_page_and_heading_metadata_and_global_index():
    chunker = RecursiveChunker(300, 50)
    chunks = chunker.split_sections(
        [Section(SENTENCE * 10, page=3), Section("Escalar al N2.", heading="Escalamiento"), Section("  ")]
    )
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert chunks[0].metadata["page"] == 3 and "section" not in chunks[0].metadata
    assert chunks[-1].metadata == {"char_count": len("Escalar al N2."), "section": "Escalamiento"}
    assert chunks[-1].estimated_tokens == 4


def test_short_consecutive_sections_share_a_chunk_with_their_headings():
    chunks = RecursiveChunker(700, 120).split_sections([
        Section("El monitor muestra la alerta EDGE-1.", heading="Síntoma"),
        Section("Reiniciar el conector de notificaciones.", heading="Acción"),
    ])
    assert len(chunks) == 1
    assert chunks[0].content == "Síntoma\nEl monitor muestra la alerta EDGE-1.\n\nAcción\nReiniciar el conector de notificaciones."
    assert chunks[0].metadata["section"] == "Síntoma / Acción"


def test_sections_are_not_grouped_across_pages_or_beyond_chunk_size():
    chunker = RecursiveChunker(300, 50)
    assert len(chunker.split_sections([Section("Texto corto.", page=1), Section("Otro texto.", page=2)])) == 2
    long_a, long_b = Section("a " * 100, heading="A"), Section("b " * 100, heading="B")
    assert [c.metadata["section"] for c in chunker.split_sections([long_a, long_b])] == ["A", "B"]


def test_invalid_overlap():
    with pytest.raises(ValueError):
        RecursiveChunker(100, 100)


def test_contextual_embedding_input():
    chunk = RecursiveChunker(300, 0).split_sections([Section("Relanzar desde checkpoint.", heading="Paso 3")])[0]
    assert embedding_input(chunk, "PROC-OPS-014") == "PROC-OPS-014 · Paso 3\nRelanzar desde checkpoint."
    assert embedding_input(chunk, "PROC-OPS-014", contextual=False) == "Relanzar desde checkpoint."


async def test_batch_embedder_uses_batches_in_order():
    embedder = FakeEmbedder()
    chunks = [Chunk(index=i, content=f"Texto {i}") for i in range(5)]
    vectors = await BatchEmbedder(embedder, batch_size=2).embed_chunks(chunks, "Doc")
    assert len(vectors) == 5
    assert [len(b) for b in embedder.batches] == [2, 2, 1]
    assert embedder.batches[0][0] == "Doc\nTexto 0"
