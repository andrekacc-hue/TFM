"""Adaptadores de LLM (patrón Adapter): el núcleo RAG solo depende de ``LLMAdapter``."""

from app.adapters.factory import create_llm_adapter
from app.adapters.llm_base import LLMAdapter, LLMResult

__all__ = ["LLMAdapter", "LLMResult", "create_llm_adapter"]
