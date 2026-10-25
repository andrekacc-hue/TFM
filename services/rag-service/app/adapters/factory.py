"""Construye el adaptador de LLM según ``LLM_PROVIDER``."""

from __future__ import annotations

from app.adapters.claude_adapter import ClaudeAdapter
from app.adapters.llm_base import LLMAdapter
from app.adapters.ollama_adapter import OllamaAdapter
from app.adapters.openai_adapter import OpenAIAdapter
from app.config import RagSettings


def create_llm_adapter(settings: RagSettings) -> LLMAdapter:
    """Instancia el adaptador configurado.

    Args:
        settings: Configuración del servicio.

    Returns:
        Adaptador listo para usar.

    Raises:
        LLMProviderError: Si el proveedor elegido no tiene credenciales.
    """
    timeout = settings.llm_timeout_seconds
    if settings.llm_provider == "claude":
        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else ""
        return ClaudeAdapter(key, settings.anthropic_model, base_url=settings.anthropic_base_url, timeout=timeout)
    if settings.llm_provider == "openai":
        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
        return OpenAIAdapter(key, settings.openai_model, base_url=settings.openai_base_url, timeout=timeout)
    return OllamaAdapter(settings.ollama_host, settings.ollama_model, think=settings.ollama_think, timeout=timeout)
