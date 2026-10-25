"""/estado: salud del sistema y cuenta con la que el bot actúa en nombre del usuario."""

from __future__ import annotations

from microsoft_agents.hosting.core import CardFactory, MessageFactory, TurnContext

from app.cards.error_card import build_status_card
from app.services.backend_client import BackendClient, BackendError


async def send_status(context: TurnContext, backend: BackendClient, user_email: str | None) -> None:
    health = await backend.ready()
    me, me_error = None, None
    if user_email:
        try:
            me = await backend.me(user_email)
        except BackendError as exc:
            me_error = exc.user_message
    else:
        me_error = "Teams no informó tu correo corporativo: las consultas se hacen sin perfil de usuario."
    card = build_status_card(health, me, me_error)
    await context.send_activity(MessageFactory.attachment(CardFactory.adaptive_card(card)))
