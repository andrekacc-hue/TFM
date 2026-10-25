"""Autenticación y autorización del gateway.

Dos tipos de llamante:

* **Usuarios** (portal web): ``Authorization: Bearer <JWT de Supabase Auth>``. El token se
  verifica (ES256 vía JWKS o HS256) y el **rol y el área se leen de ``tfm.profiles``**, la
  fuente de verdad: un cambio de rol hecho por un admin se aplica en ``PROFILE_CACHE_TTL``
  segundos, sin esperar a que el usuario renueve su token.
* **Servicios internos** (bot de Teams, scripts): ``X-Internal-Api-Key`` y, opcionalmente,
  ``X-User-Email`` para actuar en nombre de un usuario identificado por su correo
  corporativo (Azure AD), que debe existir en ``tfm.profiles``.
"""

from __future__ import annotations

import asyncio
import hmac
import time
from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, Request

from shared.auth import SupabaseJWTVerifier, bearer_token
from shared.exceptions import AuthenticationError, AuthorizationError
from shared.logging import get_logger
from shared.schemas import UserContext
from shared.supabase_client import SupabaseRepository

logger = get_logger(__name__)

ROLE_RANK = {"viewer": 1, "editor": 2, "admin": 3}
SERVICE_ROLE = "service"


class ProfileCache:
    """Cache en memoria de perfiles con expiración (un proceso del gateway)."""

    def __init__(self, ttl: int = 60) -> None:
        self.ttl = ttl
        self._items: dict[str, tuple[float, dict[str, Any] | None]] = {}

    def get(self, key: str) -> tuple[bool, dict[str, Any] | None]:
        hit = self._items.get(key)
        if hit and hit[0] > time.monotonic():
            return True, hit[1]
        return False, None

    def set(self, key: str, value: dict[str, Any] | None) -> None:
        if self.ttl:
            self._items[key] = (time.monotonic() + self.ttl, value)


class Authenticator:
    """Resuelve el :class:`UserContext` de cada petición.

    Args:
        verifier: Verificador de JWT de Supabase.
        repository: PostgREST con service_role (lectura de ``tfm.profiles``).
        internal_api_key: Clave de los servicios internos.
        profile_ttl: Segundos de cache de perfiles.
    """

    def __init__(
        self,
        verifier: SupabaseJWTVerifier,
        repository: SupabaseRepository,
        internal_api_key: str,
        *,
        profile_ttl: int = 60,
    ) -> None:
        self.verifier = verifier
        self.repository = repository
        self.internal_api_key = internal_api_key
        self.cache = ProfileCache(profile_ttl)

    async def _profile(self, column: str, value: str) -> dict[str, Any] | None:
        key = f"{column}:{value.lower()}"
        hit, profile = self.cache.get(key)
        if hit:
            return profile
        # Comparación exacta: con "ilike", un "_" del correo sería un comodín y permitiría
        # suplantar a otro usuario. Supabase Auth guarda los correos en minúsculas.
        lookup = value.strip().lower() if column == "email" else value
        rows = await self.repository.select(
            "profiles", {"select": "id,email,full_name,role,area", column: f"eq.{lookup}", "limit": "1"}
        )
        profile = rows[0] if rows else None
        self.cache.set(key, profile)
        return profile

    async def authenticate(
        self,
        authorization: str | None,
        internal_key: str | None,
        on_behalf_of: str | None,
    ) -> UserContext:
        """Valida credenciales y devuelve el usuario con su rol y área vigentes.

        Raises:
            AuthenticationError: Sin credenciales o credenciales inválidas.
            AuthorizationError: Usuario autenticado sin perfil de aplicación.
        """
        token = bearer_token(authorization)
        if token:
            # PyJWKClient descarga el JWKS con E/S bloqueante la primera vez: fuera del event loop
            claims_user = await asyncio.to_thread(self.verifier.verify, token)
            profile = await self._profile("id", str(claims_user.user_id))
            if profile is None:
                raise AuthorizationError("El usuario no tiene perfil de aplicación", code="profile_missing")
            return UserContext(
                user_id=claims_user.user_id,
                email=profile.get("email") or claims_user.email,
                role=profile["role"],
                area=profile["area"],
                access_token=token,
            )

        if internal_key:
            if not hmac.compare_digest(internal_key.encode(), self.internal_api_key.encode()):
                raise AuthenticationError("Clave interna inválida", code="invalid_internal_key")
            if not on_behalf_of:
                return UserContext(role=SERVICE_ROLE)
            profile = await self._profile("email", on_behalf_of)
            if profile is None:
                raise AuthorizationError(
                    f"No existe un usuario registrado con el correo {on_behalf_of}", code="profile_missing"
                )
            return UserContext(user_id=UUID(profile["id"]), email=profile["email"], role=profile["role"], area=profile["area"])

        raise AuthenticationError("Se requiere iniciar sesión", code="missing_credentials")


# ----------------------------------------------------------------------
# Dependencias de FastAPI
# ----------------------------------------------------------------------
async def current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_internal_api_key: Annotated[str | None, Header()] = None,
    x_user_email: Annotated[str | None, Header()] = None,
) -> UserContext:
    """Usuario autenticado; queda en ``request.state.user`` para el rate limiter y los logs."""
    authenticator: Authenticator = request.app.state.container.authenticator
    user = await authenticator.authenticate(authorization, x_internal_api_key, x_user_email)
    request.state.user = user
    logger.debug("authenticated", user_id=str(user.user_id) if user.user_id else None, role=user.role)
    return user


CurrentUser = Annotated[UserContext, Depends(current_user)]


def require_role(minimum: str, *, allow_service: bool = False) -> Callable[..., Coroutine[Any, Any, UserContext]]:
    """Dependencia que exige un rol mínimo (viewer < editor < admin).

    Args:
        minimum: Rol mínimo requerido.
        allow_service: Si los servicios internos sin usuario pueden acceder.
    """

    async def dependency(user: CurrentUser) -> UserContext:
        if user.role == SERVICE_ROLE:
            if allow_service:
                return user
            raise AuthorizationError("Esta operación requiere un usuario identificado")
        if ROLE_RANK.get(user.role or "", 0) < ROLE_RANK[minimum]:
            raise AuthorizationError(f"Se requiere el rol '{minimum}' o superior", code="insufficient_role")
        return user

    return dependency
