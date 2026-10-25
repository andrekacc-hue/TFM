"""Adaptador para Ollama (local o Ollama Cloud a través del daemon local)."""

from __future__ import annotations

from typing import Any

import httpx

from app.adapters.llm_base import LLMAdapter, LLMResult


class OllamaAdapter(LLMAdapter):
    """Genera con la API ``/api/chat`` de Ollama.

    Funciona igual con modelos locales (``qwen3:4b-instruct``) y con modelos de Ollama
    Cloud (``gemma4:31b-cloud``): el daemon local enruta las peticiones ``*-cloud``.

    Args:
        host: URL del daemon, p. ej. ``http://localhost:11434``.
        model: Modelo de Ollama.
        think: Habilita/deshabilita el razonamiento en modelos que lo soportan;
            ``None`` no envía el parámetro.
    """

    provider = "ollama"

    def __init__(
        self,
        host: str,
        model: str,
        *,
        think: bool | None = None,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(model, timeout=timeout, transport=transport)
        self.host = host.rstrip("/")
        self.think = think

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> LLMResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if self.think is not None:
            payload["think"] = self.think

        data = await self._post_json(f"{self.host}/api/chat", payload)
        return LLMResult(
            text=self.clean_text(data.get("message", {}).get("content", "")),
            provider=self.provider,
            model=data.get("model", self.model),
            tokens_input=data.get("prompt_eval_count"),
            tokens_output=data.get("eval_count"),
        )

    async def health(self) -> bool:
        try:
            response = await self._client.get(f"{self.host}/api/version", timeout=5.0)
            return response.is_success
        except httpx.HTTPError:
            return False
