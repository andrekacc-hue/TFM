"""Adaptador para Claude (Anthropic Messages API)."""

from __future__ import annotations

import httpx

from app.adapters.llm_base import LLMAdapter, LLMResult
from shared.exceptions import LLMProviderError

ANTHROPIC_VERSION = "2023-06-01"


class ClaudeAdapter(LLMAdapter):
    """Genera con ``POST /v1/messages`` de la API de Anthropic.

    Args:
        api_key: Clave de la API de Anthropic.
        model: Modelo, p. ej. ``claude-sonnet-5-5``.
        base_url: URL base de la API.
    """

    provider = "claude"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://api.anthropic.com",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise LLMProviderError("ANTHROPIC_API_KEY no configurada", code="llm_not_configured")
        super().__init__(model, timeout=timeout, transport=transport)
        self.base_url = base_url.rstrip("/")
        self._headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> LLMResult:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        data = await self._post_json(f"{self.base_url}/v1/messages", payload, headers=self._headers)
        text = "".join(
            block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
        )
        usage = data.get("usage", {})
        return LLMResult(
            text=self.clean_text(text),
            provider=self.provider,
            model=data.get("model", self.model),
            tokens_input=usage.get("input_tokens"),
            tokens_output=usage.get("output_tokens"),
        )

    async def health(self) -> bool:
        try:
            response = await self._client.get(f"{self.base_url}/v1/models", headers=self._headers, timeout=5.0)
            return response.is_success
        except httpx.HTTPError:
            return False
