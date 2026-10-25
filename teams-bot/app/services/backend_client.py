"""Cliente HTTP del api-gateway para el bot.

El bot se autentica como servicio interno (``X-Internal-Api-Key``) y actúa en nombre del
usuario de Teams con ``X-User-Email`` (su correo corporativo de Azure AD): el gateway lo
busca en ``tfm.profiles`` y aplica su rol y su área, igual que en el portal.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class BackendError(Exception):
    """Error del gateway traducido a un mensaje para el usuario de Teams."""

    status: int
    code: str
    message: str
    trace_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def user_message(self) -> str:
        if self.code == "profile_missing":
            return ("Tu cuenta corporativa no está registrada en el sistema de soporte. "
                    "Pide a un administrador que te dé acceso desde el portal.")
        if self.status == 429:
            wait = self.details.get("retry_after")
            return f"Has hecho muchas consultas seguidas. Intenta de nuevo en {wait or 'unos'} segundos."
        if self.status in (0, 502, 503, 504):
            return "El asistente no está disponible en este momento. Intenta en unos minutos."
        return self.message


class BackendClient:
    """Llamadas del bot al api-gateway.

    Args:
        base_url: URL del gateway (``http://api-gateway:8000`` en Docker).
        internal_api_key: Clave interna compartida con el gateway.
        timeout: Segundos (la generación con el LLM puede tardar).
        transport: Transporte httpx inyectable (tests).
    """

    def __init__(self, base_url: str, internal_api_key: str, *, timeout: float = 130.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport,
            headers={"X-Internal-Api-Key": internal_api_key},
        )

    @staticmethod
    def _headers(user_email: str | None) -> dict[str, str]:
        headers = {"X-Trace-Id": uuid.uuid4().hex}
        if user_email:
            headers["X-User-Email"] = user_email
        return headers

    async def _request(self, method: str, path: str, user_email: str | None = None, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, path, headers=self._headers(user_email), **kwargs)
        except httpx.HTTPError as exc:
            raise BackendError(0, "network_error", "No se pudo conectar con el asistente") from exc
        if response.is_success:
            return response.json()
        try:
            error = response.json().get("error", {})
        except ValueError:
            error = {}
        raise BackendError(
            response.status_code,
            error.get("code", "http_error"),
            error.get("message", f"Error {response.status_code}"),
            error.get("trace_id") or response.headers.get("x-trace-id"),
            error.get("details") or {},
        )

    async def ask(self, question: str, user_email: str | None) -> dict[str, Any]:
        """Consulta RAG con canal ``teams``."""
        return await self._request("POST", "/api/v1/query", user_email, json={"question": question, "channel": "teams"})

    async def feedback(self, query_id: str, rating: int, user_email: str | None, comment: str | None = None) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/feedback", user_email,
                                   json={"query_id": query_id, "rating": rating, "comment": comment or None})

    async def me(self, user_email: str | None) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/me", user_email)

    async def ready(self) -> dict[str, Any]:
        """Salud agregada (``/ready`` devuelve 503 con cuerpo útil si algo falla)."""
        try:
            response = await self._client.get("/ready", timeout=10)
            return response.json()
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "checks": {"api-gateway": "error"}}

    async def aclose(self) -> None:
        await self._client.aclose()
