from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from shared.exceptions import NotFoundError, register_exception_handlers
from shared.logging import configure_logging, get_trace_id
from shared.middleware import RequestContextMiddleware


class Body(BaseModel):
    n: int


def _app() -> FastAPI:
    configure_logging("test", "DEBUG", "console")
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    @app.get("/trace")
    async def trace():
        return {"trace_id": get_trace_id()}

    @app.get("/missing")
    async def missing():
        raise NotFoundError("No existe", details={"id": "x"})

    @app.get("/boom")
    async def boom():
        raise RuntimeError("fallo inesperado")

    @app.post("/body")
    async def body(payload: Body):
        return payload

    return app


client = TestClient(_app(), raise_server_exceptions=False)


def test_generates_trace_id_and_returns_header():
    response = client.get("/trace")
    trace_id = response.json()["trace_id"]
    assert len(trace_id) == 32
    assert response.headers["x-trace-id"] == trace_id


def test_propagates_incoming_trace_id():
    response = client.get("/trace", headers={"X-Trace-Id": "abc123def456"})
    assert response.json()["trace_id"] == "abc123def456"
    assert response.headers["x-trace-id"] == "abc123def456"


def test_rejects_malformed_trace_id():
    response = client.get("/trace", headers={"X-Trace-Id": "<script>"})
    assert response.json()["trace_id"] != "<script>"


def test_app_error_format_includes_trace_id():
    response = client.get("/missing", headers={"X-Trace-Id": "trace-0001"})
    assert response.status_code == 404
    error = response.json()["error"]
    assert error == {"code": "not_found", "message": "No existe", "trace_id": "trace-0001", "details": {"id": "x"}}


def test_unhandled_error_is_generic_500():
    response = client.get("/boom")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "fallo inesperado" not in response.text


def test_validation_error_format():
    response = client.post("/body", json={"n": "no-numero"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"]["errors"]
