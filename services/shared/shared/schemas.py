"""Esquemas Pydantic compartidos entre microservicios (contratos de la API)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Channel = Literal["web", "teams", "api"]
SourceType = Literal["manual", "procedimiento", "incidente", "faq"]


class UserContext(BaseModel):
    """Identidad del usuario que origina la petición (la resuelve el api-gateway).

    Attributes:
        user_id: ``sub`` del JWT de Supabase; ``None`` para llamadas de sistema.
        email: Correo del usuario.
        role: Rol de aplicación (viewer/editor/admin).
        area: Área funcional del usuario.
        access_token: JWT del usuario. Si existe, las lecturas se hacen con él para que
            Supabase aplique RLS; si no, con service_role.
    """

    model_config = ConfigDict(frozen=True)

    user_id: UUID | None = None
    email: str | None = None
    role: str | None = None
    area: str | None = None
    access_token: str | None = Field(default=None, repr=False)


class QueryRequest(BaseModel):
    """Consulta en lenguaje natural al asistente."""

    question: str = Field(..., min_length=3, max_length=2000, description="Pregunta del usuario")
    channel: Channel = "api"
    area: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9_-]+$",
        description="Filtra la búsqueda a un área (solo aplica a llamadas de sistema)",
    )
    top_k: int | None = Field(default=None, ge=1, le=10, description="Fuentes a usar tras el reranking")


class SourceCitation(BaseModel):
    """Fragmento documental usado para fundamentar la respuesta."""

    index: int = Field(..., description="Número de la fuente en el contexto ([1], [2], ...)")
    document_id: UUID
    chunk_id: UUID
    title: str
    source_type: SourceType | str
    chunk_index: int
    similarity: float
    rerank_score: float | None = None
    excerpt: str


class Usage(BaseModel):
    """Consumo de tokens del LLM."""

    tokens_input: int | None = None
    tokens_output: int | None = None


class Timings(BaseModel):
    """Latencia por etapa del pipeline RAG, en milisegundos."""

    guardrails_ms: float = 0.0
    retrieval_ms: float = 0.0
    rerank_ms: float = 0.0
    generation_ms: float = 0.0
    total_ms: float = 0.0


class QueryResponse(BaseModel):
    """Respuesta del asistente con fuentes verificables."""

    query_id: UUID | None = Field(None, description="Id en tfm.queries; necesario para el feedback")
    answer: str
    sources: list[SourceCitation] = Field(default_factory=list)
    abstained: bool = False
    abstention_reason: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    usage: Usage = Field(default_factory=Usage)
    timings: Timings = Field(default_factory=Timings)
    warnings: list[str] = Field(default_factory=list)
    trace_id: str | None = None


class FeedbackRequest(BaseModel):
    """Valoración de una respuesta (👍 = 1, 👎 = -1)."""

    query_id: UUID
    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    """Feedback registrado."""

    id: UUID
    query_id: UUID
    rating: int


class HealthResponse(BaseModel):
    """Estado de un servicio y de sus dependencias."""

    status: Literal["ok", "degraded", "error"]
    service: str
    version: str
    checks: dict[str, str] = Field(default_factory=dict)
