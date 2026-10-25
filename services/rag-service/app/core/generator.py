"""Generación de la respuesta fundamentada a partir del contexto."""

from __future__ import annotations

from collections.abc import Sequence

from app.adapters.llm_base import LLMAdapter, LLMResult
from app.core.prompts import SYSTEM_PROMPT, build_context, build_user_prompt
from app.core.retriever import RetrievedChunk


class Generator:
    """Construye el prompt con los fragmentos y llama al LLM configurado.

    Args:
        llm: Adaptador del proveedor (Ollama, Claude u OpenAI).
        temperature: Temperatura (baja: respuestas deterministas y fieles al contexto).
        max_tokens: Tokens máximos de la respuesta.
        max_context_chars: Presupuesto de caracteres del contexto.
    """

    def __init__(
        self,
        llm: LLMAdapter,
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        max_context_chars: int = 12000,
    ) -> None:
        self.llm = llm
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_context_chars = max_context_chars

    async def generate(self, question: str, chunks: Sequence[RetrievedChunk]) -> LLMResult:
        """Genera la respuesta citando los fragmentos.

        Args:
            question: Pregunta saneada.
            chunks: Fragmentos rerankeados, en orden de relevancia.
        """
        context = build_context(chunks, max_chars=self.max_context_chars)
        return await self.llm.generate(
            SYSTEM_PROMPT,
            build_user_prompt(question, context),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
