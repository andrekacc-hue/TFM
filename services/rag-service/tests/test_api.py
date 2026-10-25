from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.generator import Generator
from app.core.rag_chain import RagChain
from app.core.reranker import SimilarityReranker
from app.core.retriever import Retriever
from app.dependencies import Container
from app.main import create_app
from shared.exceptions import AuthenticationError
from shared.schemas import UserContext
from tests.conftest import INTERNAL_KEY, FakeEmbedder, FakeLLM, FakeRepository, MemoryCache, chunk_row, make_chunk


class FakeVerifier:
    def verify(self, token: str) -> UserContext:
        if token != "jwt-valido":
            raise AuthenticationError("Token inválido", code="invalid_token")
        return UserContext(user_id=uuid4(), role="viewer", area="operaciones", access_token=token)


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository([chunk_row(make_chunk())])


@pytest.fixture
def client(settings, repo):
    llm = FakeLLM()

    def factory(_settings):
        chain = RagChain(Retriever(repo, FakeEmbedder(), MemoryCache()), SimilarityReranker(), Generator(llm), repo)
        container = Container(_settings, repo, MemoryCache(), FakeEmbedder(), SimilarityReranker(), llm, chain, FakeVerifier())
        container.models_ready = True
        return container

    with TestClient(create_app(settings, factory)) as test_client:
        yield test_client


HEADERS = {"X-Internal-Api-Key": INTERNAL_KEY}


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_ready_reports_dependencies(client):
    body = client.get("/ready").json()
    assert body["status"] == "ok"
    assert body["checks"]["supabase"] == "ok"
    assert body["checks"]["llm"].startswith("ok (fake:")


def test_ready_returns_503_when_supabase_down(client, repo):
    repo.healthy = False
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["supabase"] == "error"


def test_query_requires_internal_key(client):
    response = client.post("/v1/query", json={"question": "¿Cómo reinicio el batch?"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_internal_key"


def test_query_returns_answer_with_sources_and_trace(client):
    response = client.post(
        "/v1/query",
        json={"question": "¿Cómo reinicio el batch?", "channel": "web"},
        headers={**HEADERS, "X-Trace-Id": "trace-api-0001"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sources"][0]["title"] == "Manual de batch"
    assert body["trace_id"] == "trace-api-0001"
    assert response.headers["x-trace-id"] == "trace-api-0001"


def test_query_with_user_jwt_uses_rls(client, repo):
    client.post("/v1/query", json={"question": "¿Cómo reinicio el batch?"}, headers={**HEADERS, "Authorization": "Bearer jwt-valido"})
    assert repo.rpc_calls[-1][2] == "jwt-valido"


def test_query_with_invalid_jwt_is_rejected(client):
    response = client.post("/v1/query", json={"question": "¿Cómo reinicio el batch?"}, headers={**HEADERS, "Authorization": "Bearer malo"})
    assert response.status_code == 401


def test_query_validation_error(client):
    response = client.post("/v1/query", json={"question": "a"}, headers=HEADERS)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_invalid_user_id_header(client):
    response = client.post("/v1/query", json={"question": "¿Cómo reinicio?"}, headers={**HEADERS, "X-User-Id": "no-uuid"})
    assert response.status_code == 401


def test_feedback_requires_identified_user(client):
    response = client.post("/v1/feedback", json={"query_id": str(uuid4()), "rating": 1}, headers=HEADERS)
    assert response.status_code == 401


def test_feedback_on_foreign_query_is_not_found(client, repo):
    repo.select_result = []
    response = client.post(
        "/v1/feedback", json={"query_id": str(uuid4()), "rating": 1}, headers={**HEADERS, "X-User-Id": str(uuid4())}
    )
    assert response.status_code == 404


def test_feedback_is_upserted(client, repo):
    query_id = str(uuid4())
    repo.select_result = [{"id": query_id}]
    response = client.post(
        "/v1/feedback",
        json={"query_id": query_id, "rating": -1, "comment": "No aplica a mi caso"},
        headers={**HEADERS, "X-User-Id": str(uuid4())},
    )
    assert response.status_code == 201
    assert response.json()["rating"] == -1
    table, row, upsert_on = repo.inserted[-1]
    assert (table, upsert_on) == ("feedback", "query_id,user_id")
    assert row["comment"] == "No aplica a mi caso"


def test_openapi_is_published(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/v1/query", "/v1/feedback", "/health", "/ready"} <= set(paths)
