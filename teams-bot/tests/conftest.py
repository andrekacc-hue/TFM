"""Doble de Teams: un *connector* que recibe las respuestas del bot y resuelve miembros."""

from __future__ import annotations

from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.config import BotSettings
from app.main import create_app
from app.services.backend_client import BackendClient

GATEWAY = "http://gateway.test"
INTERNAL_KEY = "clave-interna-de-pruebas-123"
USER_EMAIL = "ana.perez@banco.test"

QUERY_RESPONSE: dict[str, Any] = {
    "query_id": "q-123",
    "answer": "### Problema\nBatch en RUNNING.\n\n1. Relanzar desde el checkpoint. [Fuente: PROC-OPS-014, Paso 3]",
    "sources": [{"index": 1, "document_id": "d1", "chunk_id": "c1", "title": "PROC-OPS-014 Reinicio del batch",
                 "source_type": "procedimiento", "chunk_index": 3, "section": "Paso 3", "page": None,
                 "similarity": 0.82, "rerank_score": 4.1, "excerpt": "Relanzar el job desde el último checkpoint."}],
    "abstained": False, "abstention_reason": None, "llm_provider": "ollama", "llm_model": "gemma4:31b",
    "usage": {}, "timings": {"total_ms": 2100}, "warnings": [], "trace_id": "abcdef1234567890",
}


class FakeTeams:
    """Implementa los endpoints del Bot Connector que usa el bot."""

    def __init__(self, member_email: str | None = USER_EMAIL) -> None:
        self.replies: list[dict[str, Any]] = []
        self.member_email = member_email
        self.member_lookups = 0

    def app(self) -> web.Application:
        app = web.Application()

        async def reply(request: web.Request) -> web.Response:
            self.replies.append(await request.json())
            return web.json_response({"id": f"r{len(self.replies)}"})

        async def member(request: web.Request) -> web.Response:
            self.member_lookups += 1
            if self.member_email is None:
                return web.json_response({"error": "not found"}, status=404)
            return web.json_response({"id": request.match_info["mid"], "name": "Ana Pérez",
                                      "email": self.member_email, "userPrincipalName": self.member_email})

        app.router.add_post("/v3/conversations/{cid}/activities", reply)
        app.router.add_post("/v3/conversations/{cid}/activities/{aid}", reply)
        app.router.add_get("/v3/conversations/{cid}/members/{mid}", member)
        return app

    @property
    def messages(self) -> list[dict[str, Any]]:
        return [r for r in self.replies if r.get("type") == "message"]

    @property
    def cards(self) -> list[dict[str, Any]]:
        return [a["content"] for r in self.messages for a in (r.get("attachments") or [])
                if a.get("contentType") == "application/vnd.microsoft.card.adaptive"]

    @property
    def texts(self) -> list[str]:
        return [r["text"] for r in self.messages if r.get("text")]


@pytest.fixture
def settings() -> BotSettings:
    return BotSettings(_env_file=None, backend_url=GATEWAY, internal_api_key=INTERNAL_KEY,
                       microsoft_app_id="", bot_default_user_email=None)


@pytest.fixture
def teams() -> FakeTeams:
    return FakeTeams()


@pytest.fixture
async def connector_url(teams):
    server = TestServer(teams.app())
    await server.start_server()
    yield str(server.make_url("")).rstrip("/") + "/"
    await server.close()


@pytest.fixture
async def bot_client(settings):
    backend = BackendClient(GATEWAY, INTERNAL_KEY)
    client = TestClient(TestServer(create_app(settings, backend)))
    await client.start_server()
    yield client
    await client.close()


def activity(service_url: str, *, text: str | None = None, value: dict | None = None, type_: str = "message",
             **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": type_, "id": "act-1", "channelId": "msteams", "serviceUrl": service_url,
        "from": {"id": "29:ana", "name": "Ana Pérez", "aadObjectId": "aad-ana"},
        "recipient": {"id": "28:bot", "name": "Asistente"},
        "conversation": {"id": "a:conv-1"},
        **extra,
    }
    if text is not None:
        payload["text"] = text
    if value is not None:
        payload["value"] = value
    return payload
