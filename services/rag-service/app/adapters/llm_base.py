"""Contrato común de los proveedores de LLM."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from shared.exceptions import LLMProviderError

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class LLMResult:
    """Resultado normalizado de una generación.

    Attributes:
        text: Texto generado (sin bloques de razonamiento ``<think>``).
        provider: Proveedor (ollama, claude, openai).
        model: Modelo efectivamente usado.
        tokens_input: Tokens del prompt, si el proveedor los informa.
        tokens_output: Tokens generados, si el proveedor los informa.
    """

    text: str
    provider: str
    model: str
    tokens_input: int | None = None
    tokens_output: int | None = None


class LLMAdapter(ABC):
    """Interfaz que implementan Ollama, Claude y OpenAI.

    El código de negocio (generator, rag_chain) depende solo de esta clase, de modo que
    cambiar de proveedor es cambiar ``LLM_PROVIDER`` en la configuración.

    Args:
        model: Identificador del modelo.
        timeout: Timeout de la llamada en segundos.
        transport: Transporte httpx inyectable (tests).
    """

    provider: str = "base"

    def __init__(
        self,
        model: str,
        *,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> LLMResult:
        """Genera una respuesta a partir de un prompt de sistema y uno de usuario."""

    @abstractmethod
    async def health(self) -> bool:
        """Indica si el proveedor está accesible (sin consumir tokens si es posible)."""

    async def aclose(self) -> None:
        """Libera el pool de conexiones."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    @staticmethod
    def clean_text(text: str) -> str:
        """Elimina bloques ``<think>...</think>`` de modelos razonadores y espacios sobrantes."""
        return _THINK_BLOCK.sub("", text).strip()

    async def _post_json(self, url: str, payload: dict, headers: dict[str, str] | None = None) -> dict:
        """POST JSON con traducción de errores a :class:`LLMProviderError`."""
        try:
            response = await self._client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMProviderError(
                f"{self.provider}: tiempo de espera agotado", code="llm_timeout"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(
                f"{self.provider}: no se pudo conectar", code="llm_unavailable", details={"error": str(exc)}
            ) from exc

        if not response.is_success:
            raise LLMProviderError(
                f"{self.provider}: el proveedor respondió {response.status_code}",
                details={"status": response.status_code, "body": response.text[:500]},
            )
        return response.json()
