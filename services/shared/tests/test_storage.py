from __future__ import annotations

import json

import httpx
import pytest
import respx

from shared.exceptions import AuthorizationError, NotFoundError, UpstreamServiceError
from shared.supabase_client import SupabaseStorage

URL = "https://demo.supabase.co"
OBJ = f"{URL}/storage/v1/object"
LEGACY = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.firma"


@respx.mock
async def test_upload_encodes_path_and_sets_headers():
    route = respx.post(f"{OBJ}/documents/operaciones/abc/Manual%20ATM.pdf").mock(return_value=httpx.Response(200, json={"Key": "x"}))
    storage = SupabaseStorage(URL, LEGACY)
    path = await storage.upload("documents", "operaciones/abc/Manual ATM.pdf", b"%PDF", content_type="application/pdf")
    request = route.calls.last.request
    assert path == "operaciones/abc/Manual ATM.pdf"
    assert request.headers["authorization"] == f"Bearer {LEGACY}"
    assert request.headers["content-type"] == "application/pdf"
    assert request.headers["x-upsert"] == "false"
    assert request.content == b"%PDF"
    await storage.aclose()


@respx.mock
async def test_new_secret_key_only_in_apikey_header():
    route = respx.get(f"{OBJ}/documents/a.md").mock(return_value=httpx.Response(200, content=b"# hola"))
    content = await SupabaseStorage(URL, "sb_secret_x").download("documents", "a.md")
    assert content == b"# hola"
    assert route.calls.last.request.headers["apikey"] == "sb_secret_x"
    assert "authorization" not in route.calls.last.request.headers


@respx.mock
async def test_remove_sends_prefixes():
    route = respx.delete(f"{OBJ}/documents").mock(return_value=httpx.Response(200, json=[]))
    await SupabaseStorage(URL, LEGACY).remove("documents", ["a/b.pdf"])
    assert json.loads(route.calls.last.request.content) == {"prefixes": ["a/b.pdf"]}


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (404, {"message": "not found"}, NotFoundError),
        (400, {"statusCode": "404", "error": "not_found"}, NotFoundError),
        (403, {"message": "denied"}, AuthorizationError),
        (409, {"message": "The resource already exists"}, UpstreamServiceError),
    ],
)
@respx.mock
async def test_error_mapping(status, body, error):
    respx.get(f"{OBJ}/documents/x.pdf").mock(return_value=httpx.Response(status, json=body))
    with pytest.raises(error):
        await SupabaseStorage(URL, LEGACY).download("documents", "x.pdf")


@respx.mock
async def test_connection_error_and_text_error():
    respx.get(f"{OBJ}/documents/a").mock(side_effect=httpx.ConnectError("sin red"))
    respx.get(f"{OBJ}/documents/b").mock(return_value=httpx.Response(500, text="boom"))
    storage = SupabaseStorage(URL, LEGACY)
    with pytest.raises(UpstreamServiceError) as exc:
        await storage.download("documents", "a")
    assert exc.value.code == "storage_unavailable"
    with pytest.raises(UpstreamServiceError):
        await storage.download("documents", "b")
