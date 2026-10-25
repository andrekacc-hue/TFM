"""Servidor aiohttp del bot.

    python -m app.main            # escucha en :3978, endpoint POST /api/messages

Con MICROSOFT_APP_ID vacío funciona en modo anónimo (Bot Framework Emulator / pruebas);
con credenciales de Azure Bot Service valida los tokens que envía Teams.
"""

from __future__ import annotations

import logging

from aiohttp import web
from microsoft_agents.hosting.aiohttp import jwt_authorization_middleware, start_agent_process

from app import __version__
from app.bot import SupportBot
from app.config import BotSettings, get_settings
from app.services.backend_client import BackendClient


def create_app(settings: BotSettings | None = None, backend: BackendClient | None = None) -> web.Application:
    settings = settings or get_settings()
    backend = backend or BackendClient(
        settings.backend_url, settings.internal_api_key.get_secret_value(), timeout=settings.backend_timeout_seconds
    )
    bot = SupportBot(settings, backend)

    async def messages(request: web.Request) -> web.StreamResponse:
        # Un cuerpo que no es una actividad es un error del cliente (400), no del bot (500).
        # aiohttp guarda el cuerpo leído, así que el SDK puede volver a leerlo.
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or not body.get("type"):
            return web.json_response({"error": "Se esperaba una actividad del Bot Framework"}, status=400)
        return await start_agent_process(request, bot.app, bot.adapter)

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok", "service": "teams-bot", "version": __version__,
            "mode": "anonymous" if settings.anonymous else "azure-bot-service",
        })

    @web.middleware
    async def auth_except_health(request: web.Request, handler):
        # /health no lleva token de Bot Service; /api/messages siempre se valida
        if request.path == "/health":
            return await handler(request)
        return await jwt_authorization_middleware(request, handler)

    app = web.Application(middlewares=[auth_except_health])
    app["agent_configuration"] = bot.auth_config
    app["bot"] = bot
    app.router.add_post("/api/messages", messages)
    app.router.add_get("/health", health)

    async def close_backend(_app: web.Application) -> None:
        await backend.aclose()

    app.on_cleanup.append(close_backend)
    return app


def main() -> None:  # pragma: no cover
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    mode = "ANÓNIMO (Emulator/local)" if settings.anonymous else f"Azure Bot Service (App ID {settings.microsoft_app_id[:8]}…)"
    logging.getLogger("teams-bot").info("Bot en http://0.0.0.0:%s/api/messages · modo %s", settings.bot_port, mode)
    web.run_app(create_app(settings), host="0.0.0.0", port=settings.bot_port)


if __name__ == "__main__":  # pragma: no cover
    main()
