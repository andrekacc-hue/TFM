"""Configuración del rag-service."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator

from shared.config import BaseServiceSettings


class RagSettings(BaseServiceSettings):
    """Parámetros del pipeline RAG y del proveedor de LLM."""

    service_name: str = "rag-service"

    # --- LLM ---
    llm_provider: Literal["ollama", "claude", "openai"] = "ollama"
    llm_temperature: float = Field(0.1, ge=0.0, le=1.0)
    llm_max_tokens: int = Field(1024, ge=64, le=8192)
    llm_timeout_seconds: float = 120.0

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "gemma4:31b-cloud"
    # None = no enviar el parámetro "think" (no todos los modelos lo soportan)
    ollama_think: bool | None = None

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_base_url: str = "https://api.anthropic.com"

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"

    # --- Retrieval / reranking ---
    top_k_retrieval: int = Field(20, ge=1, le=100)
    top_k_rerank: int = Field(5, ge=1, le=20)
    similarity_threshold: float = Field(0.35, ge=0.0, le=1.0)
    rerank_enabled: bool = True
    rerank_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    # Abstención adicional si la mejor puntuación del reranker no alcanza este valor
    rerank_min_score: float | None = None
    max_context_chars: int = Field(12000, ge=1000)

    # Carga los modelos de embeddings/reranking al arrancar (evita latencia en la 1.ª consulta)
    preload_models: bool = True

    @field_validator("ollama_think", "rerank_min_score", "anthropic_api_key", "openai_api_key", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        return None if value == "" else value


@lru_cache
def get_settings() -> RagSettings:
    """Configuración (singleton) leída del entorno / ``.env``."""
    return RagSettings()  # type: ignore[call-arg]
