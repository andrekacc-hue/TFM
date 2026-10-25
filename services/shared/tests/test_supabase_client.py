from __future__ import annotations

import httpx
import pytest
import respx

from shared.exceptions import AuthenticationError, AuthorizationError, UpstreamServiceError
from shared.supabase_client import SupabaseRepository

URL = "https://demo.supabase.co"
REST = f"{URL}/rest/v1"
LEGACY_SERVICE = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.firma"
LEGACY_ANON = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.firma"


@pytest.fixture
def repo():
    return SupabaseRepository(URL, LEGACY_SERVICE, LEGACY_ANON, schema="tfm")


@respx.mock
async def test_rpc_with_service_role_sends_bearer_and_profile(repo):
    route = respx.post(f"{REST}/rpc/match_chunks").mock(return_value=httpx.Response(200, json=[{"x": 1}]))
    assert await repo.rpc("match_chunks", {"a": 1}) == [{"x": 1}]
    headers = route.calls.last.request.headers
    assert headers["apikey"] == LEGACY_SERVICE
    assert headers["authorization"] == f"Bearer {LEGACY_SERVICE}"
    assert headers["content-profile"] == "tfm"
    assert headers["accept-profile"] == "tfm"


@respx.mock
async def test_rpc_with_user_jwt_uses_anon_key_for_rls(repo):
    route = respx.post(f"{REST}/rpc/match_chunks").mock(return_value=httpx.Response(200, json=[]))
    await repo.rpc("match_chunks", {}, user_jwt="user.jwt.token")
    headers = route.calls.last.request.headers
    assert headers["apikey"] == LEGACY_ANON
    assert headers["authorization"] == "Bearer user.jwt.token"


@respx.mock
async def test_new_secret_keys_are_not_sent_as_bearer():
    repo = SupabaseRepository(URL, "sb_secret_abc123", "sb_publishable_xyz", schema="tfm")
    route = respx.get(f"{REST}/queries").mock(return_value=httpx.Response(200, json=[]))
    await repo.select("queries", {"id": "eq.1"})
    headers = route.calls.last.request.headers
    assert headers["apikey"] == "sb_secret_abc123"
    assert "authorization" not in headers
    assert route.calls.last.request.url.params["id"] == "eq.1"


async def test_user_call_without_anon_key_fails():
    repo = SupabaseRepository(URL, LEGACY_SERVICE, "", schema="tfm")
    with pytest.raises(UpstreamServiceError):
        await repo.rpc("match_chunks", {}, user_jwt="t")


@respx.mock
async def test_insert_with_upsert(repo):
    route = respx.post(f"{REST}/feedback").mock(return_value=httpx.Response(201, json=[{"id": "1"}]))
    rows = await repo.insert("feedback", {"rating": 1}, upsert_on="query_id,user_id")
    request = route.calls.last.request
    assert rows == [{"id": "1"}]
    assert request.url.params["on_conflict"] == "query_id,user_id"
    assert "resolution=merge-duplicates" in request.headers["prefer"]
    assert "return=representation" in request.headers["prefer"]


@respx.mock
async def test_insert_minimal_returns_empty(repo):
    respx.post(f"{REST}/queries").mock(return_value=httpx.Response(201))
    assert await repo.insert("queries", {"a": 1}, returning=False) == []


@respx.mock
async def test_update_and_delete(repo):
    respx.patch(f"{REST}/documents").mock(return_value=httpx.Response(200, json=[{"id": "d"}]))
    delete = respx.delete(f"{REST}/documents").mock(return_value=httpx.Response(204))
    assert await repo.update("documents", {"id": "eq.d"}, {"status": "indexed"}) == [{"id": "d"}]
    await repo.delete("documents", {"id": "eq.d"})
    assert delete.called
    with pytest.raises(ValueError):
        await repo.delete("documents", {})


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (401, {"message": "Invalid API key"}, AuthenticationError),
        (403, {"message": "denied"}, AuthorizationError),
        (400, {"code": "42501", "message": "RLS"}, AuthorizationError),
        (500, {"message": "boom"}, UpstreamServiceError),
    ],
)
@respx.mock
async def test_error_mapping(repo, status, body, error):
    respx.get(f"{REST}/queries").mock(return_value=httpx.Response(status, json=body))
    with pytest.raises(error):
        await repo.select("queries")


@respx.mock
async def test_non_json_error_and_connection_error(repo):
    respx.get(f"{REST}/a").mock(return_value=httpx.Response(502, text="Bad gateway"))
    respx.get(f"{REST}/b").mock(side_effect=httpx.ConnectError("sin red"))
    with pytest.raises(UpstreamServiceError):
        await repo.select("a")
    with pytest.raises(UpstreamServiceError) as exc:
        await repo.select("b")
    assert exc.value.code == "supabase_unavailable"


@respx.mock
async def test_health(repo):
    route = respx.get(f"{REST}/").mock(return_value=httpx.Response(200, json={}))
    assert await repo.health() is True
    route.mock(return_value=httpx.Response(500, json={}))
    assert await repo.health() is False
    await repo.aclose()
