from __future__ import annotations

import json

from app.cards.answer_card import build_answer_card, to_teams_markdown
from app.cards.error_card import build_error_card, build_status_card
from app.cards.welcome_card import build_welcome_card
from app.commands import parse_command
from tests.conftest import QUERY_RESPONSE


def _texts(node) -> str:
    return json.dumps(node, ensure_ascii=False)


def test_markdown_is_adapted_to_teams():
    result = to_teams_markdown("## Diagnóstico\nRevisar. [Fuente: MAN-BD-003, Escalamiento]\n\n\n\n|---|---|")
    assert result == "**Diagnóstico**\nRevisar. _📄 MAN-BD-003, Escalamiento_"


def test_answer_card_has_sources_metrics_and_feedback():
    card = build_answer_card(QUERY_RESPONSE)
    assert card["type"] == "AdaptiveCard" and card["version"] == "1.5"
    content = _texts(card)
    assert "PROC-OPS-014 Reinicio del batch" in content and "Paso 3" in content and "similitud 82%" in content
    assert "2,1 s" in content and "gemma4:31b" in content and "traza abcdef12" in content
    titles = [a["title"] for a in card["actions"]]
    assert titles == ["📄 Ver extractos", "👍 Útil", "👎 No útil"]
    assert card["actions"][1]["data"] == {"action": "feedback", "query_id": "q-123", "rating": 1}
    negative = card["actions"][2]["card"]
    assert negative["body"][0]["type"] == "Input.Text"
    assert negative["actions"][0]["data"]["rating"] == -1


def test_answer_card_without_identified_user_hides_feedback():
    titles = [a["title"] for a in build_answer_card(QUERY_RESPONSE, can_rate=False)["actions"]]
    assert titles == ["📄 Ver extractos"]


def test_abstention_and_guardrail_cards():
    abstained = build_answer_card({**QUERY_RESPONSE, "abstained": True, "abstention_reason": "sin_contexto_relevante", "sources": []})
    assert "Sin evidencia suficiente" in _texts(abstained)
    blocked = build_answer_card({**QUERY_RESPONSE, "abstained": True, "abstention_reason": "guardrail:prompt_injection", "sources": []})
    assert "bloqueada por política de seguridad" in _texts(blocked)
    assert "actions" not in blocked  # sin valoración ni fuentes


def test_welcome_and_help_card():
    card = build_welcome_card("Ana Pérez")
    assert "¡Hola, Ana!" in _texts(card)
    assert all(a["data"]["action"] == "ask" for a in card["actions"])
    assert "/estado" in _texts(card)


def test_error_and_status_cards():
    assert "trace-1" in _texts(build_error_card("Fallo", "trace-1"))
    status = build_status_card({"status": "degraded", "checks": {"rag-service": "ok", "analytics-service": "error"}},
                               {"email": "ana@b.test", "role": "editor", "area": "operaciones"})
    content = _texts(status)
    assert "Servicio degradado" in content and "Editor" in content and "operaciones" in content
    assert "No registrada" in _texts(build_status_card({"status": "ok", "checks": {}}, None, "No registrada"))


def test_parse_command():
    assert parse_command(" /AYUDA ") == "help"
    assert parse_command("estado") == "status"
    assert parse_command("/Reiniciar") == "reset"
    assert parse_command("¿cómo reinicio el batch?") is None
