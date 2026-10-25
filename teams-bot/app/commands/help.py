"""/ayuda: tarjeta de bienvenida con ejemplos y comandos."""

from __future__ import annotations

from microsoft_agents.hosting.core import CardFactory, MessageFactory, TurnContext

from app.cards.welcome_card import build_welcome_card


async def send_help(context: TurnContext, bot_name: str) -> None:
    user = context.activity.from_property
    card = build_welcome_card(user.name if user else None, bot_name=bot_name)
    await context.send_activity(MessageFactory.attachment(CardFactory.adaptive_card(card)))
