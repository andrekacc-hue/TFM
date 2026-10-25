"""/reiniciar: olvida el estado de la conversación (identidad cacheada y contexto)."""

from __future__ import annotations

from microsoft_agents.hosting.core import TurnContext


async def reset_conversation(context: TurnContext, identity_cache: dict[str, str | None]) -> None:
    user = context.activity.from_property
    if user and user.id:
        identity_cache.pop(user.id, None)
    await context.send_activity(
        "🔄 Conversación reiniciada. Cada consulta se responde de forma independiente con la documentación "
        "vigente; escribe tu pregunta cuando quieras."
    )
