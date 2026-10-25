from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import AnalyticsSettings
from app.core.aggregator import DateRange, MetricsAggregator
from app.core.reporter import QueryReporter, flatten
from app.dependencies import Container
from app.main import create_app
from shared.exceptions import ValidationAppError

INTERNAL_KEY = "clave-interna-de-pruebas-123"
HEADERS = {"X-Internal-Api-Key": INTERNAL_KEY}

ROW = {
    "id": "q1",
    "created_at": "2026-10-20T10:00:00+00:00",
    "channel": "web",
    "user_id": "u1",
    "question": "¿Cómo reinicio el batch?",
    "abstained": False,
    "abstention_reason": None,
    "latency_ms": 2100,
    "timings": {"retrieval_ms": 200.5, "rerank_ms": 210.0, "generation_ms": 1690.2},
    "tokens_input": 800,
    "tokens_output": 250,
    "llm_provider": "ollama",
    "llm_model": "gemma4:31b",
    "sources": [{"title": "PROC-OPS-014", "section": "Paso 3", "chunk_index": 3},
                {"title": "FAQ", "section": None, "chunk_index": 0}],
    "trace_id": "t1",
    "feedback": [{"rating": 1, "comment": "útil"}],
}


class FakeRepository:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.rpc_calls: list[tuple[str, dict[str, Any]]] = []
        self.select_calls: list[dict[str, str]] = []
        self.healthy = True

    async def rpc(self, function: str, params: dict[str, Any], *, user_jwt: str | None = None) -> Any:
        self.rpc_calls.append((function, params))
        if function == "metrics_summary":
            return {"total_queries": 8, "abstention_rate": 0.25, "latency_ms": {"p95": 2500}}
        if function == "metrics_knowledge_base":
            return {"documents": 6, "chunks": 24}
        return [{"function": function}]

    async def select(self, table: str, params: dict[str, str] | None = None, *, user_jwt: str | None = None):
        params = params or {}
        self.select_calls.append(params)
        offset, limit = int(params.get("offset", 0)), int(params.get("limit", 1000))
        return self.rows[offset : offset + limit]

    async def health(self) -> bool:
        return self.healthy

    async def aclose(self) -> None:
        return None


class MemoryCache:
    enabled = True

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    async def get_json(self, key):
        return self.store.get(key)

    async def set_json(self, key, value, ttl=None):
        self.store[key] = value

    async def ping(self):
        return True

    async def aclose(self):
        return None


@pytest.fixture
def settings() -> AnalyticsSettings:
    return AnalyticsSettings(
        _env_file=None,
        supabase_url="https://demo.supabase.co",
        supabase_service_role_key="sb_secret_test",
        internal_api_key=INTERNAL_KEY,
        redis_url=None,
        log_format="console",
        export_page_size=100,
    )


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository([ROW])


@pytest.fixture
def client(settings, repo):
    def factory(_settings):
        cache = MemoryCache()
        return Container(_settings, repo, cache, MetricsAggregator(repo, cache, ttl=60),
                         QueryReporter(repo, page_size=_settings.export_page_size, max_rows=_settings.export_max_rows))

    with TestClient(create_app(settings, factory)) as test_client:
        yield test_client


# ----------------------------------------------------------------------
def test_date_range_defaults_and_validation():
    period = DateRange.resolve(None, None, default_days=7)
    assert timedelta(days=6, hours=23) < period.end - period.start <= timedelta(days=7)
    naive = DateRange.resolve(datetime(2026, 1, 1), datetime(2026, 1, 2))
    assert naive.start.tzinfo is UTC
    with pytest.raises(ValidationAppError):
        DateRange.resolve(datetime(2026, 1, 2), datetime(2026, 1, 1))
    with pytest.raises(ValidationAppError):
        DateRange.resolve(datetime(2024, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC), max_days=366)


async def test_aggregator_caches_results():
    repo, cache = FakeRepository(), MemoryCache()
    aggregator = MetricsAggregator(repo, cache, ttl=60)
    period = DateRange.resolve(datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 8, tzinfo=UTC))
    first = await aggregator.summary(period, "web")
    second = await aggregator.summary(period, "web")
    assert first == second and len(repo.rpc_calls) == 1
    function, params = repo.rpc_calls[0]
    assert function == "metrics_summary"
    assert params == {"p_from": "2026-10-01T00:00:00+00:00", "p_to": "2026-10-08T00:00:00+00:00", "p_channel": "web"}
    await aggregator.summary(period, "teams")
    assert len(repo.rpc_calls) == 2


async def test_aggregator_without_cache_always_queries():
    repo = FakeRepository()
    aggregator = MetricsAggregator(repo, MemoryCache(), ttl=0)
    period = DateRange.resolve(None, None)
    await aggregator.knowledge_base()
    await aggregator.knowledge_base()
    assert len(repo.rpc_calls) == 2


def test_flatten_row():
    flat = flatten(ROW)
    assert flat["generation_ms"] == 1690.2
    assert flat["sources"] == "PROC-OPS-014 (Paso 3) | FAQ (fragmento 1)"
    assert (flat["feedback_rating"], flat["feedback_comment"]) == (1, "útil")
    assert flatten({**ROW, "feedback": [], "timings": None})["feedback_rating"] is None


async def test_reporter_paginates_and_limits():
    repo = FakeRepository([{**ROW, "id": f"q{i}"} for i in range(250)])
    reporter = QueryReporter(repo, page_size=100, max_rows=230)
    period = DateRange.resolve(None, None)
    rows = [row async for row in reporter.rows(period, channel="web")]
    assert len(rows) == 230
    assert [c["offset"] for c in repo.select_calls] == ["0", "100", "200"]
    assert repo.select_calls[-1]["limit"] == "30"
    assert repo.select_calls[0]["channel"] == "eq.web"
    assert repo.select_calls[0]["and"].startswith("(created_at.gte.")
    assert "feedback(rating,comment)" in repo.select_calls[0]["select"]


# ----------------------------------------------------------------------
def test_endpoints_require_internal_key(client):
    assert client.get("/v1/metrics/summary").status_code == 401


def test_summary_endpoint(client, repo):
    body = client.get("/v1/metrics/summary", params={"from": "2026-10-01T00:00:00Z", "to": "2026-10-08T00:00:00Z",
                                                      "channel": "web"}, headers=HEADERS).json()
    assert body["total_queries"] == 8 and body["channel"] == "web"
    assert body["from"].startswith("2026-10-01")


def test_other_metric_endpoints(client):
    assert client.get("/v1/metrics/timeseries", params={"bucket": "hour"}, headers=HEADERS).json()["bucket"] == "hour"
    assert client.get("/v1/metrics/top-documents", headers=HEADERS).json()["documents"]
    assert client.get("/v1/metrics/unanswered", headers=HEADERS).json()["questions"]
    assert client.get("/v1/metrics/knowledge-base", headers=HEADERS).json()["chunks"] == 24


def test_invalid_inputs(client):
    assert client.get("/v1/metrics/timeseries", params={"bucket": "minute"}, headers=HEADERS).status_code == 422
    assert client.get("/v1/metrics/summary", params={"channel": "fax"}, headers=HEADERS).status_code == 422
    inverted = client.get("/v1/metrics/summary", params={"from": "2026-10-08T00:00:00Z", "to": "2026-10-01T00:00:00Z"},
                          headers=HEADERS)
    assert inverted.status_code == 422


def test_csv_export(client):
    response = client.get("/v1/reports/queries.csv", params={"from": "2026-10-01T00:00:00Z", "to": "2026-10-31T00:00:00Z"},
                          headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="consultas_20261001-20261031.csv"' in response.headers["content-disposition"]
    text = response.content.decode("utf-8-sig")
    header, row = text.splitlines()[:2]
    assert header.startswith("id;created_at;channel")
    assert "¿Cómo reinicio el batch?" in row and "PROC-OPS-014 (Paso 3)" in row


def test_json_export(client):
    body = json.loads(client.get("/v1/reports/queries.json", headers=HEADERS).content)
    assert body["count"] == 1 and body["rows"][0]["retrieval_ms"] == 200.5


def test_health_and_ready(client, repo):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").json()["checks"]["supabase"] == "ok"
    repo.healthy = False
    assert client.get("/ready").status_code == 503
