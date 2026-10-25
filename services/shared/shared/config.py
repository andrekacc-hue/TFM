"""Configuración base de los microservicios (pydantic-settings).

Cada servicio extiende :class:`BaseServiceSettings` con sus propios campos. Los valores se
leen de variables de entorno y, en desarrollo, del ``.env`` en la raíz del repositorio.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def find_env_file(start: Path | None = None) -> Path | None:
    """Busca el ``.env`` subiendo desde ``start`` hasta la raíz del sistema de archivos.

    Args:
        start: Directorio desde el que empezar. Por defecto, el de este módulo.

    Returns:
        Ruta del ``.env`` encontrado o ``None`` (p. ej. dentro de un contenedor, donde las
        variables llegan por el entorno).
    """
    current = (start or Path(__file__)).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


class BaseServiceSettings(BaseSettings):
    """Configuración común a todos los microservicios."""

    model_config = SettingsConfigDict(
        env_file=find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = "soporte-service"
    environment: Literal["development", "test", "production"] = "development"

    # --- Supabase ---
    supabase_url: str = Field(..., description="URL del proyecto, p. ej. https://<ref>.supabase.co")
    supabase_anon_key: SecretStr = SecretStr("")
    supabase_service_role_key: SecretStr = Field(..., description="Clave service_role o sb_secret_")
    supabase_jwt_secret: SecretStr | None = None
    supabase_schema: str = "tfm"
    supabase_timeout_seconds: float = 15.0

    # --- Redis ---
    redis_url: str | None = None
    redis_cache_ttl: int = 3600

    # --- Seguridad entre servicios ---
    internal_api_key: SecretStr = Field(..., min_length=16)

    # --- Embeddings ---
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384

    # --- Observabilidad ---
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    @field_validator("supabase_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("redis_url", mode="before")
    @classmethod
    def _empty_redis_is_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("supabase_jwt_secret", mode="before")
    @classmethod
    def _empty_secret_is_none(cls, value: str | None) -> str | None:
        return value or None
