"""Consultas al asistente, feedback y sesión del usuario."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.dependencies import ContainerDep
from app.middleware.auth import SERVICE_ROLE, CurrentUser, require_role
from app.middleware.rate_limit import rate_limit
from shared.schemas import FeedbackRequest, FeedbackResponse, QueryRequest, QueryResponse

router = APIRouter(prefix="/api/v1", tags=["asistente"])


class Me(BaseModel):
    """Usuario autenticado con su rol y área vigentes."""

    user_id: str | None
    email: str | None
    role: str | None
    area: str | None


@router.get("/me", response_model=Me, summary="Usuario actual")
async def me(user: CurrentUser) -> Me:
    """Rol y área leídos de ``tfm.profiles`` (el portal los usa para mostrar u ocultar opciones)."""
    return Me(user_id=str(user.user_id) if user.user_id else None, email=user.email, role=user.role, area=user.area)


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Preguntar al asistente",
    dependencies=[Depends(require_role("viewer", allow_service=True)), Depends(rate_limit("query", "rate_limit_query"))],
    responses={401: {"description": "Sin sesión"}, 429: {"description": "Límite de consultas superado"},
               502: {"description": "Fallo del LLM"}, 503: {"description": "rag-service no disponible"}},
)
async def query(body: QueryRequest, user: CurrentUser, container: ContainerDep) -> Response:
    """Respuesta fundamentada con fuentes. Con sesión de usuario, el rag-service busca con su
    JWT y Supabase aplica RLS: cada usuario solo recupera documentos de su área y ``general``."""
    payload = body.model_dump(mode="json")
    if user.role not in (SERVICE_ROLE, "admin"):
        payload["area"] = None  # el área la determina RLS, no el cliente
    return await container.rag.forward("POST", "/v1/query", user=user, forward_jwt=True, json=payload)


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=201,
    summary="Valorar una respuesta",
    dependencies=[Depends(require_role("viewer")), Depends(rate_limit("feedback", "rate_limit_default"))],
)
async def feedback(body: FeedbackRequest, user: CurrentUser, container: ContainerDep) -> Response:
    return await container.rag.forward("POST", "/v1/feedback", user=user, json=body.model_dump(mode="json"))
