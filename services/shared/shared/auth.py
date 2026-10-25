"""Autenticación: JWT de Supabase Auth y clave interna entre microservicios.

Supabase firma los access tokens con:
  * claves asimétricas (ES256/RS256) publicadas en ``/auth/v1/.well-known/jwks.json``
    — proyectos con *JWT signing keys* (caso de Supabase Cloud actual), o
  * el secreto compartido HS256 (``SUPABASE_JWT_SECRET``) — proyectos legacy/self-hosted.

:class:`SupabaseJWTVerifier` soporta ambos según la cabecera ``alg`` del token.
"""

from __future__ import annotations

import hmac
from typing import Any
from uuid import UUID

import jwt
from jwt import PyJWKClient

from shared.exceptions import AuthenticationError
from shared.schemas import UserContext

INTERNAL_KEY_HEADER = "X-Internal-Api-Key"
_ASYMMETRIC_ALGS = ("ES256", "RS256", "EdDSA")


def verify_internal_api_key(provided: str | None, expected: str) -> None:
    """Valida la clave interna que el api-gateway envía a los servicios.

    Args:
        provided: Valor recibido en ``X-Internal-Api-Key``.
        expected: Valor configurado en ``INTERNAL_API_KEY``.

    Raises:
        AuthenticationError: Si falta o no coincide (comparación en tiempo constante).
    """
    if not provided or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise AuthenticationError("Clave interna inválida o ausente", code="invalid_internal_key")


class SupabaseJWTVerifier:
    """Verifica access tokens emitidos por Supabase Auth.

    Args:
        supabase_url: URL del proyecto (se usa para el JWKS y el ``iss`` esperado).
        jwt_secret: Secreto HS256 (opcional; solo proyectos legacy/self-hosted).
        audience: Audiencia esperada (``authenticated``).
        jwks_client: Cliente JWKS inyectable (tests).
    """

    def __init__(
        self,
        supabase_url: str,
        jwt_secret: str | None = None,
        *,
        audience: str = "authenticated",
        jwks_client: PyJWKClient | None = None,
    ) -> None:
        self.issuer = f"{supabase_url.rstrip('/')}/auth/v1"
        self.jwt_secret = jwt_secret
        self.audience = audience
        self._jwks = jwks_client or PyJWKClient(
            f"{self.issuer}/.well-known/jwks.json", cache_keys=True, lifespan=3600
        )

    def decode(self, token: str) -> dict[str, Any]:
        """Valida firma, expiración, audiencia y emisor; devuelve los claims.

        Raises:
            AuthenticationError: Si el token no es válido.
        """
        try:
            header = jwt.get_unverified_header(token)
            alg = header.get("alg", "")
            if alg in _ASYMMETRIC_ALGS:
                key: Any = self._jwks.get_signing_key_from_jwt(token).key
            elif alg == "HS256" and self.jwt_secret:
                key = self.jwt_secret
            else:
                raise AuthenticationError(f"Algoritmo de firma no soportado: {alg}", code="invalid_token")

            return jwt.decode(
                token,
                key=key,
                algorithms=[alg],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "sub"]},
            )
        except AuthenticationError:
            raise
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("La sesión ha expirado", code="token_expired") from exc
        except (jwt.PyJWTError, ValueError) as exc:
            raise AuthenticationError("Token inválido", code="invalid_token") from exc

    def verify(self, token: str) -> UserContext:
        """Valida el token y construye el :class:`UserContext`.

        El rol y el área de aplicación salen de ``app_metadata`` (solo escribible por
        service_role); el valor definitivo vive en ``tfm.profiles``.
        """
        claims = self.decode(token)
        app_metadata = claims.get("app_metadata") or {}
        return UserContext(
            user_id=UUID(claims["sub"]),
            email=claims.get("email"),
            role=app_metadata.get("role"),
            area=app_metadata.get("area"),
            access_token=token,
        )


def resolve_user_context(
    *,
    authorization: str | None,
    x_user_id: str | None,
    x_user_area: str | None = None,
    x_user_role: str | None = None,
    verifier: SupabaseJWTVerifier | None,
) -> UserContext:
    """Determina el usuario de una petición interna.

    * Con ``Authorization: Bearer <jwt>`` se verifica el token (defensa en profundidad,
      aunque el gateway ya lo valida) y se usa para aplicar RLS en Supabase.
    * Sin JWT se aceptan las cabeceras ``X-User-*`` que pone el gateway (canales como Teams,
      donde el usuario se identifica por otra vía).

    Raises:
        AuthenticationError: Si el JWT o ``X-User-Id`` no son válidos.
    """
    token = bearer_token(authorization)
    if token:
        if verifier is None:
            raise AuthenticationError("Verificación de JWT no configurada")
        return verifier.verify(token)

    user_id: UUID | None = None
    if x_user_id:
        try:
            user_id = UUID(x_user_id)
        except ValueError as exc:
            raise AuthenticationError("X-User-Id inválido") from exc
    return UserContext(user_id=user_id, area=x_user_area, role=x_user_role)


def bearer_token(authorization: str | None) -> str | None:
    """Extrae el token de una cabecera ``Authorization: Bearer <token>``."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()
