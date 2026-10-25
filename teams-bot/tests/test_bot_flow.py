"""Pipeline real del Agents SDK: POST /api/messages → bot → gateway (simulado) → connector (simulado)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx

from app.config import BotSettings
from app.main import create_app
from app.services.backend_client import BackendClient, BackendError
from tests.conftest import GATEWAY, INTERNAL_KEY, QUERY_RESPONSE, USER_EMAIL, FakeTeams, activity


async def send(bot_client, payload) -> int:
    response = await bot_client.post("/api/messages", json=payload)
    await asyncio.sleep(0.05)  # el SDK envía las respuestas de forma asíncrona
    return response.status


@pytest.fixture
def gateway():
    with respx.mock(base_url=GATEWAY, assert_all_called=False) as router:
        router.post("/api/v1/query").mock(return_value=httpx.Response(200, json=QUERY_RESPONSE))
        router.post("/api/v1/feedback").mock(return_value=httpx.Response(201, json={"id": "f1", "query_id": "q-123", "rating": 1}))
        router.get("/ready").mock(return_value=httpx.Response(200, json={"status": "ok", "checks": {"rag-service": "ok"}}))
        router.get("/api/v1/me").mock(return_value=httpx.Response(200, json={"email": USER_EMAIL, "role": "viewer", "area": "operaciones"}))
        yield router


async def test_welcome_on_install(bot_client, connector_url, teams, gateway):
    payload = activity(connector_url, type_="conversationUpdate",
                       membersAdded=[{"id": "28:bot"}, {"id": "29:ana", "name": "Ana Pérez"}])
    assert await send(bot_client, payload) in (200, 202)
    assert len(teams.cards) == 1  # solo da la bienvenida al usuario, no a sí mismo
    assert "¡Hola, Ana!" in json.dumps(teams.cards[0], ensure_ascii=False)


async def test_question_returns_answer_card_on_behalf_of_teams_user(bot_client, connector_url, teams, gateway):
    await send(bot_client, activity(connector_url, text="<at>Asistente</at> El batch quedó en RUNNING"))

    sent = gateway.calls.last.request
    assert sent.url.path == "/api/v1/query"
    assert json.loads(sent.content) == {"question": "El batch quedó en RUNNING", "channel": "teams"}
    assert sent.headers["x-internal-api-key"] == INTERNAL_KEY
    assert sent.headers["x-user-email"] == USER_EMAIL  # resuelto vía el endpoint de miembros de Teams

    assert any(r.get("type") == "typing" for r in teams.replies), "debe mostrar 'escribiendo…'"
    card = teams.cards[-1]
    assert "PROC-OPS-014" in json.dumps(card, ensure_ascii=False)
    assert [a["title"] for a in card["actions"]][-2:] == ["👍 Útil", "👎 No útil"]


async def test_identity_is_cached_per_user(bot_client, connector_url, teams, gateway):
    await send(bot_client, activity(connector_url, text="Primera consulta"))
    await send(bot_client, activity(connector_url, text="Segunda consulta"))
    assert teams.member_lookups == 1


async def test_feedback_button(bot_client, connector_url, teams, gateway):
    await send(bot_client, activity(connector_url, value={"action": "feedback", "query_id": "q-123", "rating": -1,
                                                           "comment": "Faltó el paso 1"}))
    body = json.loads(gateway.calls.last.request.content)
    assert body == {"query_id": "q-123", "rating": -1, "comment": "Faltó el paso 1"}
    assert "revisaremos esta respuesta" in teams.texts[-1]


async def test_example_buttons_ask_the_question(bot_client, connector_url, teams, gateway):
    await send(bot_client, activity(connector_url, value={"action": "ask", "question": "Error VPN-403"}))
    assert json.loads(gateway.calls.last.request.content)["question"] == "Error VPN-403"


async def test_commands(bot_client, connector_url, teams, gateway):
    await send(bot_client, activity(connector_url, text="/ayuda"))
    assert "/reiniciar" in json.dumps(teams.cards[-1], ensure_ascii=False)

    await send(bot_client, activity(connector_url, text="/estado"))
    status = json.dumps(teams.cards[-1], ensure_ascii=False)
    assert "Sistema operativo" in status and USER_EMAIL in status

    await send(bot_client, activity(connector_url, text="/reiniciar"))
    assert "Conversación reiniciada" in teams.texts[-1]
    assert not gateway.routes[0].called  # ningún comando llegó al RAG


async def test_backend_error_becomes_error_card(bot_client, connector_url, teams, gateway):
    gateway.post("/api/v1/query").mock(return_value=httpx.Response(
        403, json={"error": {"code": "profile_missing", "message": "x", "trace_id": "t-9"}}))
    await send(bot_client, activity(connector_url, text="¿Cómo reinicio el batch?"))
    card = json.dumps(teams.cards[-1], ensure_ascii=False)
    assert "no está registrada" in card and "t-9" in card


async def test_without_teams_email_queries_as_service_without_feedback(settings, connector_url, gateway):
    teams = FakeTeams(member_email=None)
    from aiohttp.test_utils import TestClient, TestServer
    server = TestServer(teams.app()); await server.start_server()
    url = str(server.make_url("")).rstrip("/") + "/"
    client = TestClient(TestServer(create_app(settings, BackendClient(GATEWAY, INTERNAL_KEY)))); await client.start_server()
    try:
        await send(client, activity(url, text="¿Cómo reinicio el batch?"))
        assert "x-user-email" not in gateway.calls.last.request.headers
        assert [a["title"] for a in teams.cards[-1]["actions"]] == ["📄 Ver extractos"]
    finally:
        await client.close(); await server.close()


async def test_invalid_payloads_are_client_errors(bot_client):
    assert (await bot_client.post("/api/messages", json={})).status == 400
    assert (await bot_client.post("/api/messages", data="no es json", headers={"Content-Type": "application/json"})).status == 400


async def test_health_endpoint(bot_client):
    body = await (await bot_client.get("/health")).json()
    assert body["status"] == "ok" and body["mode"] == "anonymous"


async def test_azure_mode_rejects_unsigned_requests(connector_url):
    settings = BotSettings(_env_file=None, backend_url=GATEWAY, internal_api_key=INTERNAL_KEY,
                           microsoft_app_id="00000000-0000-0000-0000-000000000000", microsoft_app_password="x",
                           microsoft_app_tenant_id="tenant")
    from aiohttp.test_utils import TestClient, TestServer
    client = TestClient(TestServer(create_app(settings, BackendClient(GATEWAY, INTERNAL_KEY)))); await client.start_server()
    try:
        response = await client.post("/api/messages", json=activity(connector_url, text="hola"))
        assert response.status == 401  # sin token de Bot Service no se procesa nada
        assert (await (await client.get("/health")).json())["mode"] == "azure-bot-service"
    finally:
        await client.close()


@respx.mock
async def test_backend_client_error_messages():
    client = BackendClient(GATEWAY, INTERNAL_KEY)
    respx.post(f"{GATEWAY}/api/v1/query").mock(return_value=httpx.Response(429, json={"error": {"code": "rate_limited", "message": "x", "details": {"retry_after": 12}}}))
    with pytest.raises(BackendError) as exc:
        await client.ask("hola", None)
    assert "12 segundos" in exc.value.user_message
    respx.post(f"{GATEWAY}/api/v1/query").mock(side_effect=httpx.ConnectError("caído"))
    with pytest.raises(BackendError) as exc:
        await client.ask("hola", None)
    assert exc.value.status == 0 and "no está disponible" in exc.value.user_message
    respx.get(f"{GATEWAY}/ready").mock(side_effect=httpx.ConnectError("caído"))
    assert (await client.ready())["status"] == "error"
    await client.aclose()
