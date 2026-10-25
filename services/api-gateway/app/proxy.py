"""Proxy hacia los microservicios internos.

Añade a cada llamada la clave interna, la traza y la identidad del usuario, y devuelve la
respuesta del servicio tal cual (código, cuerpo y cabeceras relevantes), de modo que los
errores mantienen el formato homogéneo ``{"error": {...}}``.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import Response

from app.middleware.tracing import downstream_trace_headers
from shared.exceptions import UpstreamServiceError
from shared.http import async_client
from shared.logging import get_logger
from shared.schemas import UserContext

logger = get_logger(__name__)

_RELAYED_HEADERS = ("content-type", "content-disposition", "retry-after")


class ServiceProxy:
    """Cliente de un servicio interno.

    Args:
        name: Nombre lógico (para logs y errores).
        base_url: URL base, p. ej. ``http://rag-service:8001``.
        internal_api_key: Clave interna compartida.
        timeout: Timeout por petición.
        transport: Transporte httpx inyectable (tests).
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        internal_api_key: str,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self._internal_key = internal_api_key
        self._client = async_client(base_url=self.base_url, timeout=timeout, transport=transport)

    def _headers(self, user: UserContext | None, *, forward_jwt: bool) -> dict[str, str]:
        headers = {"X-Internal-Api-Key": self._internal_key, **downstream_trace_headers()}
        if user is not None:
            if user.user_id:
                headers["X-User-Id"] = str(user.user_id)
            if user.role:
                headers["X-User-Role"] = user.role
            if user.area:
                headers["X-User-Area"] = user.area
            if forward_jwt and user.access_token:
                headers["Authorization"] = f"Bearer {user.access_token}"
        return headers

    async def request(
        self,
        method: str,
        path: str,
        *,
        user: UserContext | None = None,
        forward_jwt: bool = False,
        params: Any = None,
        json: Any = None,
        content: bytes | None = None,
        content_type: str | None = None,
    ) -> httpx.Response:
        """Envía la petición al servicio.

        Args:
            forward_jwt: Reenvía el JWT del usuario para que el servicio lea con RLS.

        Raises:
            UpstreamServiceError: El servicio no responde (503).
        """
        headers = self._headers(user, forward_jwt=forward_jwt)
        if content_type:
            headers["Content-Type"] = content_type
        try:
            response = await self._client.request(method, path, params=params, json=json, content=content, headers=headers)
        except httpx.TimeoutException as exc:
            raise UpstreamServiceError(
                f"El servicio {self.name} no respondió a tiempo", code="service_timeout", status_code=504
            ) from exc
        except httpx.HTTPError as exc:
            logger.error("service_unreachable", service=self.name, error=str(exc))
            raise UpstreamServiceError(
                f"El servicio {self.name} no está disponible", code="service_unavailable", status_code=503
            ) from exc
        logger.info("proxied", service=self.name, method=method, path=path, status=response.status_code)
        return response

    async def forward(self, method: str, path: str, **kwargs: Any) -> Response:
        """Como :meth:`request`, pero devuelve una respuesta de FastAPI lista para el cliente."""
        upstream = await self.request(method, path, **kwargs)
        headers = {k: v for k, v in upstream.headers.items() if k.lower() in _RELAYED_HEADERS}
        return Response(content=upstream.content, status_code=upstream.status_code, headers=headers)

    async def healthy(self) -> bool:
        try:
            response = await self._client.get("/health", timeout=3.0)
            return response.is_success
        except httpx.HTTPError:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
