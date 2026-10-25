"""Composición de dependencias del api-gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from app.config import GatewaySettings
from app.middleware.auth import Authenticator
from app.middleware.rate_limit import RateLimiter, create_storage
from app.proxy import ServiceProxy
from shared.auth import SupabaseJWTVerifier
from shared.supabase_client import SupabaseRepository


@dataclass
class Container:
    settings: GatewaySettings
    repository: SupabaseRepository
    authenticator: Authenticator
    rate_limiter: RateLimiter
    rag: ServiceProxy
    ingest: ServiceProxy
    analytics: ServiceProxy

    async def aclose(self) -> None:
        for client in (self.repository, self.rag, self.ingest, self.analytics):
            await client.aclose()


def build_container(settings: GatewaySettings) -> Container:
    internal_key = settings.internal_api_key.get_secret_value()
    repository = SupabaseRepository(
        settings.supabase_url, settings.supabase_service_role_key.get_secret_value(), schema=settings.supabase_schema
    )
    verifier = SupabaseJWTVerifier(
        settings.supabase_url,
        settings.supabase_jwt_secret.get_secret_value() if settings.supabase_jwt_secret else None,
    )
    timeout = settings.service_timeout_seconds
    return Container(
        settings=settings,
        repository=repository,
        authenticator=Authenticator(verifier, repository, internal_key, profile_ttl=settings.profile_cache_ttl),
        rate_limiter=RateLimiter(create_storage(settings.redis_url)),
        rag=ServiceProxy("rag-service", settings.rag_service_url, internal_key, timeout=settings.rag_timeout_seconds),
        ingest=ServiceProxy("ingest-service", settings.ingest_service_url, internal_key, timeout=timeout + 60),
        analytics=ServiceProxy("analytics-service", settings.analytics_service_url, internal_key, timeout=timeout),
    )


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]
