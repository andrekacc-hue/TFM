"""Lógica del bot sobre Microsoft 365 Agents SDK (sucesor del Bot Framework SDK).

Flujo de un mensaje en Teams:
    texto / botón ──► ¿comando? (/ayuda, /estado, /reiniciar)
                  └─► ¿valoración? (Action.Submit con query_id) ──► POST /api/v1/feedback
                  └─► consulta ──► "escribiendo…" ──► POST /api/v1/query ──► Adaptive Card con fuentes
"""

from __future__ import annotations

import logging
import re
from typing import Any

from microsoft_agents.activity import Activity, ActivityTypes
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.aiohttp import CloudAdapter
from microsoft_agents.hosting.core import (
    AgentApplication,
    AgentAuthConfiguration,
    CardFactory,
    MemoryStorage,
    MessageFactory,
    TurnContext,
    TurnState,
)

from app.cards.answer_card import build_answer_card
from app.cards.error_card import build_error_card
from app.commands import parse_command
from app.commands.help import send_help
from app.commands.reset import reset_conversation
from app.commands.status import send_status
from app.config import BotSettings
from app.services.backend_client import BackendClient, BackendError

logger = logging.getLogger("teams-bot")
_MENTION = re.compile(r"<at>.*?</at>", re.IGNORECASE)
CONNECTOR_CLIENT_KEY = "ConnectorClient"  # ChannelServiceAdapter._AGENT_CONNECTOR_CLIENT_KEY


def auth_configuration(settings: BotSettings) -> AgentAuthConfiguration:
    """Credenciales de Azure Bot Service, o modo anónimo si no hay App ID (Emulator/local)."""
    if settings.anonymous:
        return AgentAuthConfiguration(anonymous_allowed=True)
    return AgentAuthConfiguration(
        client_id=settings.microsoft_app_id,
        client_secret=settings.microsoft_app_password.get_secret_value(),
        tenant_id=settings.microsoft_app_tenant_id or None,
    )


class SupportBot:
    """Ensambla el AgentApplication con sus manejadores.

    Args:
        settings: Configuración.
        backend: Cliente del api-gateway.
    """

    def __init__(self, settings: BotSettings, backend: BackendClient) -> None:
        self.settings = settings
        self.backend = backend
        self.auth_config = auth_configuration(settings)
        self.connection_manager = MsalConnectionManager(connections_configurations={"SERVICE_CONNECTION": self.auth_config})
        self.adapter = CloudAdapter(connection_manager=self.connection_manager)
        self.app = AgentApplication[TurnState](
            storage=MemoryStorage(), adapter=self.adapter, connection_manager=self.connection_manager
        )
        # id de usuario de Teams -> correo corporativo (o None si no se pudo resolver)
        self.identity_cache: dict[str, str | None] = {}
        self._register()

    # ------------------------------------------------------------------
    def _register(self) -> None:
        @self.app.conversation_update("membersAdded")
        async def on_members_added(context: TurnContext, _state: TurnState) -> None:
            bot_id = context.activity.recipient.id if context.activity.recipient else None
            for member in context.activity.members_added or []:
                if member.id != bot_id:
                    await send_help(context, self.settings.bot_name)

        @self.app.activity(ActivityTypes.message)
        async def on_message(context: TurnContext, _state: TurnState) -> None:
            await self.handle_message(context)

        @self.app.error
        async def on_error(context: TurnContext, error: Exception) -> None:
            logger.exception("error no controlado en el bot", exc_info=error)
            await context.send_activity("Ocurrió un error inesperado. Intenta de nuevo en unos segundos.")

    # ------------------------------------------------------------------
    async def handle_message(self, context: TurnContext) -> None:
        value = context.activity.value if isinstance(context.activity.value, dict) else {}
        action = value.get("action")

        if action == "feedback":
            await self.handle_feedback(context, value)
            return

        question = value.get("question") if action == "ask" else _MENTION.sub("", context.activity.text or "").strip()
        command = parse_command(question or "")
        if command == "help" or not question:
            await send_help(context, self.settings.bot_name)
        elif command == "status":
            await send_status(context, self.backend, await self.resolve_email(context))
        elif command == "reset":
            await reset_conversation(context, self.identity_cache)
        elif len(question) < 3:
            await context.send_activity("Escribe una consulta un poco más detallada, por favor.")
        else:
            await self.answer(context, question)

    async def answer(self, context: TurnContext, question: str) -> None:
        email = await self.resolve_email(context)
        await context.send_activity(Activity(type=ActivityTypes.typing))
        try:
            response = await self.backend.ask(question, email)
        except BackendError as exc:
            logger.warning("consulta fallida: %s %s", exc.status, exc.code)
            await self._send_card(context, build_error_card(exc.user_message, exc.trace_id))
            return
        await self._send_card(context, build_answer_card(response, can_rate=email is not None))

    async def handle_feedback(self, context: TurnContext, value: dict[str, Any]) -> None:
        email = await self.resolve_email(context)
        try:
            rating = 1 if int(value.get("rating", 0)) > 0 else -1
            await self.backend.feedback(str(value["query_id"]), rating, email, value.get("comment"))
        except (KeyError, ValueError):
            await context.send_activity("No se pudo registrar la valoración (datos incompletos).")
            return
        except BackendError as exc:
            await context.send_activity(f"No se pudo registrar la valoración: {exc.user_message}")
            return
        await context.send_activity("¡Gracias por tu valoración! 🙌" if rating == 1 else
                                    "Gracias, revisaremos esta respuesta para mejorar la documentación. 📝")

    async def resolve_email(self, context: TurnContext) -> str | None:
        """Correo corporativo del usuario: miembro de la conversación en Teams (cacheado)."""
        user = context.activity.from_property
        if user is None or not user.id:
            return self.settings.bot_default_user_email
        if user.id in self.identity_cache:
            return self.identity_cache[user.id]

        email: str | None = None
        connector = context.turn_state.get(CONNECTOR_CLIENT_KEY)
        conversation = context.activity.conversation
        if connector is not None and conversation is not None:
            try:
                member = await connector.conversations.get_conversation_member(conversation.id, user.id)
                extra = member.model_extra or {}
                email = extra.get("email") or extra.get("userPrincipalName")
            except Exception as exc:  # noqa: BLE001 - el Emulator no implementa este endpoint
                logger.info("no se pudo obtener el miembro de la conversación: %s", type(exc).__name__)
        email = (email or self.settings.bot_default_user_email or "").strip().lower() or None
        self.identity_cache[user.id] = email
        return email

    async def _send_card(self, context: TurnContext, card: dict[str, Any]) -> None:
        await context.send_activity(MessageFactory.attachment(CardFactory.adaptive_card(card)))
