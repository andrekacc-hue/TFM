from __future__ import annotations

import json

import httpx
import respx

from app.core.reranker import CrossEncoderReranker, SimilarityReranker
from app.core.retriever import Retriever
from shared.supabase_client import SupabaseRepository
from tests.conftest import FakeEmbedder, MemoryCache, chunk_row, make_chunk

RPC = "https://demo.supabase.co/rest/v1/rpc/match_chunks"


def _repo() -> SupabaseRepository:
    return SupabaseRepository("https://demo.supabase.co", "sb_secret_test", "sb_publishable_test", schema="tfm")


@respx.mock
async def test_retrieve_calls_match_chunks_with_service_role():
    chunk = make_chunk(similarity=0.91)
    route = respx.post(RPC).mock(return_value=httpx.Response(200, json=[chunk_row(chunk)]))
    retriever = Retriever(_repo(), FakeEmbedder(), MemoryCache())

    result = await retriever.retrieve("batch en RUNNING", top_k=7, threshold=0.4, area="operaciones")

    assert [c.chunk_id for c in result] == [chunk.chunk_id]
    request = route.calls.last.request
    body = json.loads(request.content)
    assert body["match_count"] == 7
    assert body["match_threshold"] == 0.4
    assert body["filter_area"] == "operaciones"
    assert len(body["query_embedding"]) == 4
    assert request.headers["apikey"] == "sb_secret_test"
    assert request.headers["content-profile"] == "tfm"


@respx.mock
async def test_retrieve_with_user_jwt_applies_rls():
    route = respx.post(RPC).mock(return_value=httpx.Response(200, json=[]))
    retriever = Retriever(_repo(), FakeEmbedder(), MemoryCache())
    assert await retriever.retrieve("pregunta", user_jwt="jwt.del.usuario") == []
    headers = route.calls.last.request.headers
    assert headers["apikey"] == "sb_publishable_test"
    assert headers["authorization"] == "Bearer jwt.del.usuario"


async def test_query_embeddings_are_cached():
    embedder = FakeEmbedder()
    retriever = Retriever(_repo(), embedder, MemoryCache())
    first = await retriever.embed("¿Cómo reinicio el batch?")
    second = await retriever.embed("  ¿cómo reinicio el BATCH?  ")
    assert first == second
    assert embedder.calls == 1


async def test_similarity_reranker_orders_and_truncates():
    chunks = [make_chunk(similarity=s) for s in (0.4, 0.9, 0.6)]
    result = await SimilarityReranker().rerank("q", chunks, top_k=2)
    assert [c.similarity for c in result] == [0.9, 0.6]


class FakeCrossEncoder:
    def predict(self, pairs, show_progress_bar=False):
        # Puntúa por presencia de la palabra "checkpoint"
        return [5.0 if "checkpoint" in text else -2.0 for _, text in pairs]


async def test_cross_encoder_reranker_uses_scores():
    relevant = make_chunk(content="Relanzar desde el último checkpoint", similarity=0.5)
    noise = make_chunk(content="Horario de atención", similarity=0.9)
    reranker = CrossEncoderReranker("fake", model=FakeCrossEncoder())
    result = await reranker.rerank("¿Cómo relanzo el batch?", [noise, relevant], top_k=1)
    assert result[0].chunk_id == relevant.chunk_id
    assert result[0].rerank_score == 5.0
    assert await reranker.rerank("q", [], top_k=3) == []
