"""Repositorio de acceso a Supabase (PostgREST) sobre ``httpx``.

Decisión de diseño: se habla con PostgREST por HTTP en vez de usar ``supabase-py``
porque el cliente oficial guarda la sesión como estado global del cliente. Aquí cada
llamada puede ir:

* con **service_role** (operaciones internas; Supabase omite RLS), o
* con el **JWT del usuario** (lecturas en su nombre; Supabase aplica RLS por área/rol),

sin crear un cliente por petición ni compartir estado entre peticiones concurrentes.
Es la misma API REST que ``supabase-py`` envuelve internamente.

Soporta las claves legacy (JWT ``eyJ...``) y las nuevas (``sb_secret_...`` /
``sb_publishable_...``), que no son JWT y solo se envían en la cabecera ``apikey``.
"""

from __future__ import annotations

from typing import Any

import httpx

from shared.exceptions import AuthenticationError, AuthorizationError, UpstreamServiceError
from shared.logging import get_logger, get_trace_id

logger = get_logger(__name__)


def _is_jwt(key: str) -> bool:
    return key.count(".") == 2 and key.startswith("eyJ")


class SupabaseRepository:
    """Cliente asíncrono de PostgREST para un esquema concreto.

    Args:
        url: URL del proyecto Supabase.
        service_key: Clave service_role (JWT legacy) o ``sb_secret_...``.
        anon_key: Clave anon (JWT legacy) o ``sb_publishable_...``; necesaria para
            llamadas con JWT de usuario.
        schema: Esquema expuesto en la Data API (``tfm``).
        timeout: Timeout por petición, en segundos.
        transport: Transporte httpx inyectable (tests).
    """

    def __init__(
        self,
        url: str,
        service_key: str,
        anon_key: str = "",
        *,
        schema: str = "tfm",
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = f"{url.rstrip('/')}/rest/v1"
        self.schema = schema
        self._service_key = service_key
        self._anon_key = anon_key
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    # ------------------------------------------------------------------
    # Cabeceras
    # ------------------------------------------------------------------
    def _headers(self, user_jwt: str | None = None, *, write: bool = False) -> dict[str, str]:
        if user_jwt:
            if not self._anon_key:
                raise UpstreamServiceError("SUPABASE_ANON_KEY no configurada para llamadas con usuario")
            headers = {"apikey": self._anon_key, "Authorization": f"Bearer {user_jwt}"}
        else:
            headers = {"apikey": self._service_key}
            if _is_jwt(self._service_key):
                headers["Authorization"] = f"Bearer {self._service_key}"

        profile = "Content-Profile" if write else "Accept-Profile"
        headers[profile] = self.schema
        if write:
            headers["Accept-Profile"] = self.schema
        if trace_id := get_trace_id():
            headers["X-Trace-Id"] = trace_id
        return headers

    # ------------------------------------------------------------------
    # Operaciones
    # ------------------------------------------------------------------
    async def rpc(self, function: str, params: dict[str, Any], *, user_jwt: str | None = None) -> Any:
        """Invoca una función SQL expuesta (``POST /rpc/<function>``).

        Args:
            function: Nombre de la función en el esquema (p. ej. ``match_chunks``).
            params: Argumentos nombrados.
            user_jwt: JWT del usuario para aplicar RLS; ``None`` usa service_role.

        Returns:
            El JSON devuelto por la función.
        """
        response = await self._request(
            "POST", f"/rpc/{function}", json=params, headers=self._headers(user_jwt, write=True)
        )
        return response.json()

    async def select(
        self,
        table: str,
        params: dict[str, str] | None = None,
        *,
        user_jwt: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lee filas con la sintaxis de filtros de PostgREST (``{"id": "eq.<uuid>"}``)."""
        response = await self._request(
            "GET", f"/{table}", params=params or {}, headers=self._headers(user_jwt)
        )
        return response.json()

    async def insert(
        self,
        table: str,
        rows: dict[str, Any] | list[dict[str, Any]],
        *,
        upsert_on: str | None = None,
        returning: bool = True,
    ) -> list[dict[str, Any]]:
        """Inserta (o hace upsert de) filas con service_role.

        Args:
            table: Tabla destino.
            rows: Fila o lista de filas.
            upsert_on: Columnas de la restricción única para ``ON CONFLICT DO UPDATE``.
            returning: Si ``True`` devuelve las filas creadas.
        """
        headers = self._headers(write=True)
        prefer = ["return=representation" if returning else "return=minimal"]
        params: dict[str, str] = {}
        if upsert_on:
            prefer.append("resolution=merge-duplicates")
            params["on_conflict"] = upsert_on
        headers["Prefer"] = ",".join(prefer)
        response = await self._request("POST", f"/{table}", json=rows, params=params, headers=headers)
        return response.json() if returning and response.content else []

    async def update(
        self,
        table: str,
        filters: dict[str, str],
        values: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Actualiza filas que cumplan ``filters`` (sintaxis PostgREST) con service_role."""
        headers = self._headers(write=True)
        headers["Prefer"] = "return=representation"
        response = await self._request("PATCH", f"/{table}", params=filters, json=values, headers=headers)
        return response.json() if response.content else []

    async def delete(self, table: str, filters: dict[str, str]) -> None:
        """Borra filas que cumplan ``filters`` con service_role."""
        if not filters:
            raise ValueError("delete() requiere filtros para evitar borrar toda la tabla")
        await self._request("DELETE", f"/{table}", params=filters, headers=self._headers(write=True))

    async def health(self) -> bool:
        """Comprueba que PostgREST responde y que el esquema está expuesto."""
        try:
            await self._request("GET", "/", headers=self._headers())
            return True
        except UpstreamServiceError:
            return False

    async def aclose(self) -> None:
        """Cierra el pool de conexiones."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, f"{self.base_url}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise UpstreamServiceError(
                "Supabase no disponible", code="supabase_unavailable", details={"error": str(exc)}
            ) from exc

        if response.is_success:
            return response

        try:
            body = response.json()
        except ValueError:
            body = {"message": response.text[:300]}
        details = {"status": response.status_code, "path": path, "postgrest": body}
        logger.warning("supabase_error", method=method, **details)

        if response.status_code == 401:
            raise AuthenticationError("Credenciales de Supabase rechazadas", details=details)
        if response.status_code == 403 or body.get("code") == "42501":
            raise AuthorizationError("Operación no permitida por las políticas RLS", details=details)
        raise UpstreamServiceError("Error en Supabase", code="supabase_error", details=details)
