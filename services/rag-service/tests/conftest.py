from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.adapters.llm_base import LLMResult
from app.config import RagSettings
from app.core.retriever import RetrievedChunk

INTERNAL_KEY = "clave-interna-de-pruebas-123"


@pytest.fixture
def settings() -> RagSettings:
    return RagSettings(
        _env_file=None,
        supabase_url="https://demo.supabase.co",
        supabase_service_role_key="sb_secret_test",
        supabase_anon_key="sb_publishable_test",
        internal_api_key=INTERNAL_KEY,
        redis_url=None,
        preload_models=False,
        log_format="console",
        llm_provider="ollama",
        ollama_host="http://ollama.test",
        ollama_model="modelo-test",
    )


def make_chunk(
    title: str = "Manual de batch",
    content: str = "Para reiniciar el batch de cierre, verificar bloqueos y relanzar desde el checkpoint.",
    similarity: float = 0.8,
    chunk_index: int = 0,
    source_type: str = "procedimiento",
    rerank_score: float | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        content=content,
        similarity=similarity,
        document_title=title,
        source_type=source_type,
        chunk_index=chunk_index,
        rerank_score=rerank_score,
    )


class FakeEmbedder:
    model_name = "fake-embedder"
    dimension = 4

    def __init__(self) -> None:
        self.calls = 0

    async def embed_query(self, text: str) -> list[float]:
        self.calls += 1
        return [0.1, 0.2, 0.3, float(len(text) % 10) / 10]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_query(t) for t in texts]


class FakeLLM:
    provider = "fake"
    model = "fake-model"

    def __init__(self, text: str = "1. Reiniciar el batch. [Fuente: Manual de batch, fragmento 1]") -> None:
        self.text = text
        self.prompts: list[tuple[str, str]] = []
        self.healthy = True

    async def generate(self, system_prompt: str, user_prompt: str, *, temperature: float = 0.1, max_tokens: int = 1024) -> LLMResult:
        self.prompts.append((system_prompt, user_prompt))
        return LLMResult(text=self.text, provider=self.provider, model=self.model, tokens_input=100, tokens_output=20)

    async def health(self) -> bool:
        return self.healthy

    async def aclose(self) -> None:
        return None


class FakeRepository:
    """Doble de SupabaseRepository que registra las llamadas."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.rpc_calls: list[tuple[str, dict[str, Any], str | None]] = []
        self.inserted: list[tuple[str, Any, str | None]] = []
        self.select_result: list[dict[str, Any]] = []
        self.fail_insert = False
        self.healthy = True
        self.query_id: UUID = uuid4()

    async def rpc(self, function: str, params: dict[str, Any], *, user_jwt: str | None = None) -> Any:
        self.rpc_calls.append((function, params, user_jwt))
        return self.rows

    async def select(self, table: str, params: dict[str, str] | None = None, *, user_jwt: str | None = None):
        return self.select_result

    async def insert(self, table: str, rows: Any, *, upsert_on: str | None = None, returning: bool = True):
        if self.fail_insert:
            raise RuntimeError("Supabase caído")
        self.inserted.append((table, rows, upsert_on))
        if table == "queries":
            return [{"id": str(self.query_id)}]
        return [{"id": str(uuid4()), **rows}]

    async def health(self) -> bool:
        return self.healthy

    async def aclose(self) -> None:
        return None


class MemoryCache:
    enabled = True

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    async def get_json(self, key: str) -> Any | None:
        return self.store.get(key)

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        self.store[key] = value

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


def chunk_row(chunk: RetrievedChunk) -> dict[str, Any]:
    """Fila tal como la devuelve tfm.match_chunks vía PostgREST."""
    return chunk.model_dump(mode="json", exclude={"rerank_score"})
