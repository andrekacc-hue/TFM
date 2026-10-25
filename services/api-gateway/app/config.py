"""Configuración del api-gateway."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator

from shared.config import BaseServiceSettings


class GatewaySettings(BaseServiceSettings):
    """URLs de los servicios internos, CORS y límites de uso."""

    service_name: str = "api-gateway"

    rag_service_url: str = "http://rag-service:8001"
    ingest_service_url: str = "http://ingest-service:8002"
    analytics_service_url: str = "http://analytics-service:8003"

    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"],
        description="Orígenes del portal web (lista separada por comas en el .env)",
    )

    # Límites por usuario (sintaxis de la librería `limits`: "N/second|minute|hour|day")
    rate_limit_default: str = "120/minute"
    rate_limit_query: str = "20/minute"
    rate_limit_upload: str = "10/minute"
    rate_limit_export: str = "5/minute"

    profile_cache_ttl: int = Field(60, ge=0, description="Segundos de cache del perfil (rol/área) de cada usuario")
    max_upload_mb: int = Field(50, ge=1, le=50)
    rag_timeout_seconds: float = 120.0
    service_timeout_seconds: float = 30.0

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip().startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("rag_service_url", "ingest_service_url", "analytics_service_url")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        return value.rstrip("/")


@lru_cache
def get_settings() -> GatewaySettings:
    return GatewaySettings()  # type: ignore[call-arg]
