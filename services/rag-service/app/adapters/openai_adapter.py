"""Adaptador para OpenAI (y APIs compatibles con Chat Completions)."""

from __future__ import annotations

import httpx

from app.adapters.llm_base import LLMAdapter, LLMResult
from shared.exceptions import LLMProviderError


class OpenAIAdapter(LLMAdapter):
    """Genera con ``POST /chat/completions``.

    Args:
        api_key: Clave de la API.
        model: Modelo, p. ej. ``gpt-4o-mini``.
        base_url: URL base (permite proveedores compatibles con la API de OpenAI).
    """

    provider = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise LLMProviderError("OPENAI_API_KEY no configurada", code="llm_not_configured")
        super().__init__(model, timeout=timeout, transport=transport)
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}

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
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        data = await self._post_json(f"{self.base_url}/chat/completions", payload, headers=self._headers)
        choices = data.get("choices") or [{}]
        usage = data.get("usage", {})
        return LLMResult(
            text=self.clean_text(choices[0].get("message", {}).get("content") or ""),
            provider=self.provider,
            model=data.get("model", self.model),
            tokens_input=usage.get("prompt_tokens"),
            tokens_output=usage.get("completion_tokens"),
        )

    async def health(self) -> bool:
        try:
            response = await self._client.get(f"{self.base_url}/models", headers=self._headers, timeout=5.0)
            return response.is_success
        except httpx.HTTPError:
            return False
