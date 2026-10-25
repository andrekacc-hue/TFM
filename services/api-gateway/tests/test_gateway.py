from __future__ import annotations

import json
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import GatewaySettings
from app.dependencies import build_container
from app.main import create_app
from app.middleware.auth import ProfileCache
from shared.exceptions import AuthenticationError
from shared.schemas import UserContext

INTERNAL_KEY = "clave-interna-de-pruebas-123"
SUPABASE = "https://demo.supabase.co"
RAG, INGEST, ANALYTICS = "http://rag.test", "http://ingest.test", "http://analytics.test"

USERS = {
    "token-viewer": {"id": str(uuid4()), "email": "viewer@banco.test", "role": "viewer", "area": "operaciones"},
    "token-editor": {"id": str(uuid4()), "email": "editor@banco.test", "role": "editor", "area": "operaciones"},
    "token-admin": {"id": str(uuid4()), "email": "admin@banco.test", "role": "admin", "area": "general"},
    "token-sin-perfil": {"id": str(uuid4()), "email": "nuevo@banco.test", "role": None, "area": None},
}


class FakeVerifier:
    """Sustituye la verificación criptográfica: el 'token' identifica al usuario de USERS."""

    def verify(self, token: str) -> UserContext:
        if token not in USERS:
            raise AuthenticationError("Token inválido", code="invalid_token")
        return UserContext(user_id=UUID(USERS[token]["id"]), email=USERS[token]["email"], access_token=token)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _profiles(request: httpx.Request) -> httpx.Response:
    params = request.url.params
    for user in USERS.values():
        if user["role"] and (params.get("id") == f"eq.{user['id']}" or params.get("email") == f"eq.{user['email']}"):
            return httpx.Response(200, json=[user])
    return httpx.Response(200, json=[])


@pytest.fixture
def settings() -> GatewaySettings:
    return GatewaySettings(
        _env_file=None,
        supabase_url=SUPABASE,
        supabase_service_role_key="sb_secret_test",
        internal_api_key=INTERNAL_KEY,
        redis_url=None,
        log_format="console",
        rag_service_url=RAG,
        ingest_service_url=INGEST,
        analytics_service_url=ANALYTICS,
        rate_limit_query="3/minute",
        max_upload_mb=1,
        cors_origins="http://localhost:5173,http://localhost:3000",
    )


@pytest.fixture
def mock():
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{SUPABASE}/rest/v1/profiles").mock(side_effect=_profiles)
        router.get(f"{SUPABASE}/rest/v1/").mock(return_value=httpx.Response(200, json={}))
        for base in (RAG, INGEST, ANALYTICS):
            router.get(f"{base}/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
        yield router


@pytest.fixture
def client(settings, mock):
    def factory(_settings):
        container = build_container(_settings)
        container.authenticator.verifier = FakeVerifier()
        return container

    with TestClient(create_app(settings, factory)) as test_client:
        yield test_client


# ----------------------------------------------------------------------
# Autenticación
# ----------------------------------------------------------------------
def test_requires_credentials(client):
    response = client.post("/api/v1/query", json={"question": "¿Cómo reinicio el batch?"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_credentials"


def test_invalid_token(client):
    assert client.get("/api/v1/me", headers=auth("token-falso")).status_code == 401


def test_user_without_profile_is_forbidden(client):
    response = client.get("/api/v1/me", headers=auth("token-sin-perfil"))
    assert response.status_code == 403 and response.json()["error"]["code"] == "profile_missing"


def test_me_uses_role_from_profiles(client):
    body = client.get("/api/v1/me", headers=auth("token-editor")).json()
    assert body == {"user_id": USERS["token-editor"]["id"], "email": "editor@banco.test", "role": "editor", "area": "operaciones"}


def test_profile_lookup_is_cached(client, mock):
    for _ in range(3):
        client.get("/api/v1/me", headers=auth("token-admin"))
    calls = [c for c in mock.calls if c.request.url.path.endswith("/profiles")]
    assert len(calls) == 1


# ----------------------------------------------------------------------
# Consultas
# ----------------------------------------------------------------------
def test_query_forwards_identity_jwt_and_trace(client, mock):
    route = mock.post(f"{RAG}/v1/query").mock(return_value=httpx.Response(200, json={"answer": "ok", "abstained": False}))
    response = client.post(
        "/api/v1/query",
        json={"question": "¿Cómo reinicio el batch?", "channel": "web", "area": "creditos"},
        headers={**auth("token-viewer"), "X-Trace-Id": "trace-gateway-01"},
    )
    assert response.status_code == 200 and response.json()["answer"] == "ok"
    assert response.headers["x-trace-id"] == "trace-gateway-01"

    sent = route.calls.last.request
    assert sent.headers["x-internal-api-key"] == INTERNAL_KEY
    assert sent.headers["authorization"] == "Bearer token-viewer"
    assert sent.headers["x-user-id"] == USERS["token-viewer"]["id"]
    assert sent.headers["x-user-role"] == "viewer"
    assert sent.headers["x-trace-id"] == "trace-gateway-01"
    # Un viewer no puede elegir área: la impone RLS
    assert json.loads(sent.content)["area"] is None


def test_admin_can_filter_area(client, mock):
    route = mock.post(f"{RAG}/v1/query").mock(return_value=httpx.Response(200, json={}))
    client.post("/api/v1/query", json={"question": "¿Cómo reinicio?", "area": "creditos"}, headers=auth("token-admin"))
    assert json.loads(route.calls.last.request.content)["area"] == "creditos"


def test_query_validation_happens_at_gateway(client, mock):
    route = mock.post(f"{RAG}/v1/query")
    response = client.post("/api/v1/query", json={"question": "a"}, headers=auth("token-viewer"))
    assert response.status_code == 422 and not route.called


def test_rate_limit_per_user(client, mock):
    mock.post(f"{RAG}/v1/query").mock(return_value=httpx.Response(200, json={}))
    statuses = [client.post("/api/v1/query", json={"question": "¿Cómo reinicio?"}, headers=auth("token-viewer")).status_code
                for _ in range(4)]
    assert statuses == [200, 200, 200, 429]
    limited = client.post("/api/v1/query", json={"question": "¿Cómo reinicio?"}, headers=auth("token-viewer")).json()
    assert limited["error"]["code"] == "rate_limited" and limited["error"]["details"]["retry_after"] >= 1
    # Otro usuario tiene su propia cuota
    assert client.post("/api/v1/query", json={"question": "¿Cómo reinicio?"}, headers=auth("token-editor")).status_code == 200


def test_downstream_errors_are_relayed(client, mock):
    mock.post(f"{RAG}/v1/query").mock(
        return_value=httpx.Response(502, json={"error": {"code": "llm_provider_error", "message": "ollama: 402"}})
    )
    response = client.post("/api/v1/query", json={"question": "¿Cómo reinicio?"}, headers=auth("token-viewer"))
    assert response.status_code == 502 and response.json()["error"]["code"] == "llm_provider_error"


def test_service_down_returns_503(client, mock):
    mock.post(f"{RAG}/v1/query").mock(side_effect=httpx.ConnectError("refused"))
    response = client.post("/api/v1/query", json={"question": "¿Cómo reinicio?"}, headers=auth("token-viewer"))
    assert response.status_code == 503 and response.json()["error"]["code"] == "service_unavailable"


def test_service_timeout_returns_504(client, mock):
    mock.post(f"{RAG}/v1/query").mock(side_effect=httpx.ReadTimeout("lento"))
    assert client.post("/api/v1/query", json={"question": "¿Cómo reinicio?"}, headers=auth("token-viewer")).status_code == 504


def test_feedback_forwarded(client, mock):
    route = mock.post(f"{RAG}/v1/feedback").mock(return_value=httpx.Response(201, json={"id": "f", "query_id": "q", "rating": 1}))
    response = client.post("/api/v1/feedback", json={"query_id": str(uuid4()), "rating": 1}, headers=auth("token-viewer"))
    assert response.status_code == 201
    assert "authorization" not in route.calls.last.request.headers


# ----------------------------------------------------------------------
# Servicios internos (bot de Teams)
# ----------------------------------------------------------------------
def test_internal_service_acting_on_behalf_of_user(client, mock):
    route = mock.post(f"{RAG}/v1/query").mock(return_value=httpx.Response(200, json={}))
    headers = {"X-Internal-Api-Key": INTERNAL_KEY, "X-User-Email": "Viewer@Banco.test"}
    response = client.post("/api/v1/query", json={"question": "¿Cómo reinicio?", "channel": "teams"}, headers=headers)
    assert response.status_code == 200
    sent = route.calls.last.request.headers
    assert sent["x-user-id"] == USERS["token-viewer"]["id"] and "authorization" not in sent


def test_internal_service_errors(client):
    bad_key = {"X-Internal-Api-Key": "otra-clave"}
    assert client.get("/api/v1/me", headers=bad_key).status_code == 401
    unknown = {"X-Internal-Api-Key": INTERNAL_KEY, "X-User-Email": "nadie@banco.test"}
    assert client.get("/api/v1/me", headers=unknown).status_code == 403
    # Sin usuario, un servicio puede consultar pero no subir documentos ni dar feedback
    system = {"X-Internal-Api-Key": INTERNAL_KEY}
    assert client.post("/api/v1/feedback", json={"query_id": str(uuid4()), "rating": 1}, headers=system).status_code == 403


def test_email_lookup_is_exact_not_wildcard(client, mock):
    # "_" es comodín en ilike: con coincidencia exacta "viewer_banco" no debe resolver a nadie
    headers = {"X-Internal-Api-Key": INTERNAL_KEY, "X-User-Email": "viewer@banco_test"}
    assert client.get("/api/v1/me", headers=headers).status_code == 403
    sent = [c.request.url.params.get("email") for c in mock.calls if c.request.url.path.endswith("/profiles")]
    assert "eq.viewer@banco_test" in sent


# ----------------------------------------------------------------------
# Documentos
# ----------------------------------------------------------------------
def _upload(client, headers, content=b"# Manual\n\ncontenido"):
    return client.post("/api/v1/documents", files={"file": ("m.md", content, "text/markdown")},
                       data={"source_type": "manual", "area": "operaciones"}, headers=headers)


def test_viewer_cannot_upload(client):
    response = _upload(client, auth("token-viewer"))
    assert response.status_code == 403 and response.json()["error"]["code"] == "insufficient_role"


def test_editor_upload_is_passed_through_untouched(client, mock):
    route = mock.post(f"{INGEST}/v1/ingest").mock(return_value=httpx.Response(202, json={"document_id": "d1", "status": "pending"}))
    response = _upload(client, auth("token-editor"))
    assert response.status_code == 202
    sent = route.calls.last.request
    assert sent.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="m.md"' in sent.content and b"contenido" in sent.content
    assert sent.headers["x-user-role"] == "editor" and sent.headers["x-user-area"] == "operaciones"


def test_upload_too_large_and_wrong_content_type(client):
    assert _upload(client, auth("token-editor"), content=b"x" * (2 * 1024 * 1024 + 10)).status_code == 413
    response = client.post("/api/v1/documents", json={"file": "x"}, headers=auth("token-editor"))
    assert response.status_code == 422


def test_reindex_status_and_queue(client, mock):
    doc = uuid4()
    mock.post(f"{INGEST}/v1/ingest/{doc}/reindex").mock(return_value=httpx.Response(202, json={"status": "pending"}))
    mock.get(f"{INGEST}/v1/ingest/{doc}").mock(return_value=httpx.Response(200, json={"status": "indexed"}))
    mock.get(f"{INGEST}/v1/ingest/queue/stats").mock(return_value=httpx.Response(200, json={"pending": 0}))
    assert client.post(f"/api/v1/documents/{doc}/reindex", headers=auth("token-editor")).status_code == 202
    assert client.get(f"/api/v1/documents/{doc}/status", headers=auth("token-editor")).json()["status"] == "indexed"
    assert client.get("/api/v1/documents/queue/stats", headers=auth("token-editor")).status_code == 403
    assert client.get("/api/v1/documents/queue/stats", headers=auth("token-admin")).json() == {"pending": 0}


# ----------------------------------------------------------------------
# Analítica
# ----------------------------------------------------------------------
def test_analytics_permissions_and_params(client, mock):
    route = mock.get(f"{ANALYTICS}/v1/metrics/summary").mock(return_value=httpx.Response(200, json={"total_queries": 8}))
    assert client.get("/api/v1/analytics/summary", headers=auth("token-viewer")).status_code == 403
    response = client.get("/api/v1/analytics/summary", params={"from": "2026-10-01T00:00:00Z", "channel": "web"},
                          headers=auth("token-editor"))
    assert response.json() == {"total_queries": 8}
    assert route.calls.last.request.url.params["channel"] == "web"
    assert client.get("/api/v1/analytics/inventada", headers=auth("token-admin")).status_code == 422


def test_export_admin_only_and_headers_relayed(client, mock):
    mock.get(f"{ANALYTICS}/v1/reports/queries.csv").mock(return_value=httpx.Response(
        200, content=b"id;question\n", headers={"content-type": "text/csv; charset=utf-8",
                                                 "content-disposition": 'attachment; filename="consultas.csv"'}))
    assert client.get("/api/v1/reports/queries.csv", headers=auth("token-editor")).status_code == 403
    response = client.get("/api/v1/reports/queries.csv", headers=auth("token-admin"))
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert "consultas.csv" in response.headers["content-disposition"]


# ----------------------------------------------------------------------
# Salud, CORS y OpenAPI
# ----------------------------------------------------------------------
def test_health_and_ready(client, mock):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").json()["status"] == "ok"
    mock.get(f"{ANALYTICS}/health").mock(side_effect=httpx.ConnectError("x"))
    degraded = client.get("/ready")
    assert degraded.status_code == 200 and degraded.json()["checks"]["analytics-service"] == "error"
    mock.get(f"{RAG}/health").mock(side_effect=httpx.ConnectError("x"))
    assert client.get("/ready").status_code == 503


def test_cors_preflight(client):
    response = client.options("/api/v1/query", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                                                        "Access-Control-Request-Headers": "authorization,content-type"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    blocked = client.options("/api/v1/query", headers={"Origin": "https://malicioso.test", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in blocked.headers


def test_openapi_documents_all_routes(client):
    paths = set(client.get("/openapi.json").json()["paths"])
    assert {"/api/v1/query", "/api/v1/feedback", "/api/v1/me", "/api/v1/documents", "/api/v1/documents/{document_id}/reindex",
            "/api/v1/analytics/{metric}", "/api/v1/reports/queries.{fmt}", "/health", "/ready"} <= paths


def test_profile_cache_expiry():
    cache = ProfileCache(ttl=0)
    cache.set("k", {"role": "admin"})
    assert cache.get("k") == (False, None)
