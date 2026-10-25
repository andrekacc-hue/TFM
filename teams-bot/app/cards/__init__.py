"""Adaptive Cards (esquema 1.5, el máximo que admite Teams)."""

from __future__ import annotations

from typing import Any

SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
VERSION = "1.5"


def card(body: list[dict[str, Any]], actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Estructura base de una Adaptive Card (ancho completo en Teams)."""
    result: dict[str, Any] = {"type": "AdaptiveCard", "$schema": SCHEMA, "version": VERSION, "body": body,
                              "msteams": {"width": "Full"}}
    if actions:
        result["actions"] = actions
    return result


def text(value: str, **props: Any) -> dict[str, Any]:
    return {"type": "TextBlock", "text": value, "wrap": True, **props}


def header(title: str, subtitle: str | None = None, *, style: str = "accent") -> dict[str, Any]:
    items = [text(title, weight="Bolder", size="Medium", color=style)]
    if subtitle:
        items.append(text(subtitle, isSubtle=True, spacing="None", size="Small"))
    return {"type": "Container", "items": items}
