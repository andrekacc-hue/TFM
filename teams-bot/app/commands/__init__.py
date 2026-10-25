"""Comandos del bot: /ayuda, /estado, /reiniciar."""

from __future__ import annotations

import unicodedata

COMMAND_ALIASES = {
    "/ayuda": "help", "ayuda": "help", "/help": "help", "help": "help", "/start": "help",
    "/estado": "status", "estado": "status", "/status": "status",
    "/reiniciar": "reset", "reiniciar": "reset", "/reset": "reset",
}


def parse_command(text: str) -> str | None:
    """Devuelve el comando ("help", "status", "reset") o None si es una consulta normal."""
    normalized = unicodedata.normalize("NFKD", text.strip().lower())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    return COMMAND_ALIASES.get(normalized)
