"""Tarjetas de error y de estado del sistema."""

from __future__ import annotations

from typing import Any

from app.cards import card, header, text

ROLE_LABELS = {"viewer": "Consulta", "editor": "Editor", "admin": "Administrador"}


def build_error_card(message: str, trace_id: str | None = None) -> dict[str, Any]:
    body = [
        {"type": "Container", "style": "attention", "items": [text("⚠️ No pude completar tu consulta", weight="Bolder")]},
        text(message),
    ]
    if trace_id:
        body.append(text(f"Referencia para soporte: `{trace_id}`", isSubtle=True, size="Small"))
    return card(body)


def build_status_card(health: dict[str, Any], me: dict[str, Any] | None, me_error: str | None = None) -> dict[str, Any]:
    status = health.get("status", "error")
    title = {"ok": "✅ Sistema operativo", "degraded": "🟡 Servicio degradado"}.get(status, "🔴 Servicio no disponible")
    checks = health.get("checks") or {}
    body = [
        header(title),
        {"type": "FactSet", "facts": [
            {"title": name, "value": "Operativo" if str(value).startswith("ok") else "Error"} for name, value in checks.items()
        ]},
        text("**Tu cuenta**", spacing="Medium"),
    ]
    if me:
        body.append({"type": "FactSet", "facts": [
            {"title": "Correo", "value": me.get("email") or "—"},
            {"title": "Rol", "value": ROLE_LABELS.get(me.get("role") or "", me.get("role") or "—")},
            {"title": "Área", "value": me.get("area") or "—"},
        ]})
    else:
        body.append(text(me_error or "No identificada", isSubtle=True))
    return card(body)
