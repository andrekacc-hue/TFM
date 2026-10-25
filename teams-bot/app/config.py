"""Configuración del bot (variables de entorno / .env de la raíz del repositorio)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env() -> Path | None:
    for directory in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        if (directory / ".env").is_file():
            return directory / ".env"
    return None


class BotSettings(BaseSettings):
    """Credenciales de Azure Bot Service y conexión con el api-gateway."""

    model_config = SettingsConfigDict(env_file=_find_env(), env_file_encoding="utf-8", extra="ignore")

    # --- Azure Bot Service (vacíos = modo anónimo para pruebas locales / Emulator) ---
    microsoft_app_id: str = ""
    microsoft_app_password: SecretStr = SecretStr("")
    microsoft_app_tenant_id: str = ""

    # --- Servidor ---
    bot_port: int = 3978
    bot_name: str = "Asistente TI Producción"

    # --- api-gateway ---
    backend_url: str = "http://api-gateway:8000"
    internal_api_key: SecretStr = Field(..., min_length=16)
    backend_timeout_seconds: float = 130.0
    # Correo con el que actuar si Teams no lo informa (Emulator / pruebas locales)
    bot_default_user_email: str | None = None

    log_level: str = "INFO"

    @field_validator("backend_url")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("bot_default_user_email", mode="before")
    @classmethod
    def _empty_none(cls, value: object) -> object:
        return value or None

    @property
    def anonymous(self) -> bool:
        """Sin App ID: solo para el Bot Framework Emulator o pruebas locales."""
        return not self.microsoft_app_id


@lru_cache
def get_settings() -> BotSettings:
    return BotSettings()  # type: ignore[call-arg]
