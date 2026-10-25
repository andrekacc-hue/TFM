"""Tarjeta de bienvenida y ayuda, con preguntas de ejemplo pulsables."""

from __future__ import annotations

from typing import Any

from app.cards import card, header, text

EXAMPLES = [
    "El batch de cierre diario quedó en RUNNING, ¿qué hago?",
    "Varios cajeros rechazan retiros con código 91",
    "La VPN de guardia me da error VPN-403",
]

COMMANDS = [
    ("/ayuda", "Muestra esta ayuda"),
    ("/estado", "Estado del sistema y de tu cuenta"),
    ("/reiniciar", "Reinicia la conversación"),
]


def build_welcome_card(user_name: str | None = None, *, bot_name: str = "Asistente TI Producción") -> dict[str, Any]:
    greeting = f"¡Hola, {user_name.split()[0]}!" if user_name else "¡Hola!"
    body = [
        header(f"👋 {greeting} Soy el {bot_name}"),
        text("Respondo consultas técnicas usando **solo la documentación autorizada** de TI Producción "
             "(manuales, procedimientos, incidentes y FAQ) y **cito cada fuente**. Si no hay evidencia "
             "suficiente, te recomendaré escalar el caso a un especialista."),
        text("**Prueba con una de estas consultas:**", spacing="Medium"),
    ]
    body.append({
        "type": "FactSet",
        "facts": [{"title": command, "value": description} for command, description in COMMANDS],
        "spacing": "Medium",
    })
    body.append(text("🔒 No escribas contraseñas ni datos de clientes: se enmascaran automáticamente.",
                     isSubtle=True, size="Small", spacing="Medium"))
    actions = [{"type": "Action.Submit", "title": example, "data": {"action": "ask", "question": example}}
               for example in EXAMPLES]
    return card(body, actions)
