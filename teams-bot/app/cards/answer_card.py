"""Tarjeta de respuesta: texto citado, fuentes verificables, métricas y 👍/👎."""

from __future__ import annotations

import re
from typing import Any

from app.cards import card, header, text

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*$", re.MULTILINE)
_CITATION = re.compile(r"\[Fuente:\s*([^\]]+)\]")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}.*$", re.MULTILINE)

SOURCE_TYPES = {"manual": "Manual", "procedimiento": "Procedimiento", "incidente": "Incidente", "faq": "FAQ"}


def to_teams_markdown(answer: str) -> str:
    """Adapta el Markdown del LLM al subconjunto que renderiza Teams en un TextBlock.

    Teams admite negrita, cursiva, listas y enlaces, pero no encabezados ni tablas:
    los encabezados pasan a negrita y las citas "[Fuente: …]" a cursiva con 📄.
    """
    result = _HEADING.sub(r"**\1**", answer)
    result = _CITATION.sub(r"_📄 \1_", result)
    result = _TABLE_RULE.sub("", result)
    return re.sub(r"\n{3,}", "\n\n", result).strip()


def _section(source: dict[str, Any]) -> str:
    label = (source.get("section") or "").strip() or f"fragmento {source.get('chunk_index', 0) + 1}"
    return f"{label} (pág. {source['page']})" if source.get("page") else label


def _duration(ms: float | None) -> str:
    if not ms:
        return "—"
    return f"{ms:.0f} ms" if ms < 1000 else f"{ms / 1000:.1f} s".replace(".", ",")


def build_answer_card(response: dict[str, Any], *, can_rate: bool = True) -> dict[str, Any]:
    """Construye la tarjeta a partir de la respuesta de ``POST /api/v1/query``.

    Args:
        response: Cuerpo de la respuesta del gateway.
        can_rate: Muestra 👍/👎 (requiere un usuario identificado y ``query_id``).
    """
    sources: list[dict[str, Any]] = response.get("sources") or []
    reason = response.get("abstention_reason") or ""
    blocked = reason.startswith("guardrail:")

    body: list[dict[str, Any]] = [header("🤖 Asistente de soporte TI")]
    if response.get("abstained"):
        body.append({
            "type": "Container", "style": "attention" if blocked else "warning",
            "items": [text("🛡️ Solicitud bloqueada por política de seguridad" if blocked else "⚠️ Sin evidencia suficiente",
                           weight="Bolder", size="Small")],
        })
    body.append(text(to_teams_markdown(response.get("answer", "")), spacing="Medium"))

    if sources:
        body.append(text(f"**Fuentes ({len(sources)})**", spacing="Large", size="Small"))
        for source in sources:
            similarity = round((source.get("similarity") or 0) * 100)
            body.append({
                "type": "ColumnSet", "spacing": "Small",
                "columns": [
                    {"type": "Column", "width": "auto", "items": [text(f"**{source.get('index', '•')}**", color="Accent")]},
                    {"type": "Column", "width": "stretch", "items": [
                        text(source.get("title", ""), weight="Bolder", size="Small"),
                        text(f"{SOURCE_TYPES.get(source.get('source_type', ''), source.get('source_type', ''))} · "
                             f"{_section(source)} · similitud {similarity}%", isSubtle=True, size="Small", spacing="None"),
                    ]},
                ],
            })

    timings = response.get("timings") or {}
    meta = [f"⏱ {_duration(timings.get('total_ms'))}"]
    if response.get("llm_model"):
        meta.append(response["llm_model"])
    if response.get("trace_id"):
        meta.append(f"traza {response['trace_id'][:8]}")
    body.append(text(" · ".join(meta), isSubtle=True, size="Small", spacing="Medium"))

    actions: list[dict[str, Any]] = []
    if sources:
        actions.append({
            "type": "Action.ShowCard", "title": "📄 Ver extractos",
            "card": card([
                {"type": "Container", "separator": True, "items": [
                    text(f"**[{s.get('index')}] {s.get('title', '')}** — {_section(s)}", size="Small"),
                    text(s.get("excerpt", ""), size="Small", isSubtle=True, spacing="None"),
                ]}
                for s in sources
            ]),
        })
    query_id = response.get("query_id")
    if can_rate and query_id and not blocked:
        actions.append({"type": "Action.Submit", "title": "👍 Útil",
                        "data": {"action": "feedback", "query_id": query_id, "rating": 1}})
        actions.append({
            "type": "Action.ShowCard", "title": "👎 No útil",
            "card": card(
                [{"type": "Input.Text", "id": "comment", "isMultiline": True, "maxLength": 2000,
                  "placeholder": "¿Qué faltó o qué estaba mal? (opcional)"}],
                [{"type": "Action.Submit", "title": "Enviar valoración",
                  "data": {"action": "feedback", "query_id": query_id, "rating": -1}}],
            ),
        })
    return card(body, actions)
