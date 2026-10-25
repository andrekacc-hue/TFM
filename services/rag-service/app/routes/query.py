"""Endpoints de consulta y feedback."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.dependencies import ContainerDep, UserDep, require_internal_key
from shared.exceptions import AuthenticationError, NotFoundError
from shared.schemas import FeedbackRequest, FeedbackResponse, QueryRequest, QueryResponse

router = APIRouter(prefix="/v1", tags=["rag"], dependencies=[Depends(require_internal_key)])


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Responder una consulta con RAG",
    responses={401: {"description": "Clave interna o JWT inválidos"}, 502: {"description": "Fallo del LLM o de Supabase"}},
)
async def query(body: QueryRequest, container: ContainerDep, user: UserDep) -> QueryResponse:
    """Recupera fragmentos relevantes, genera una respuesta citada y la registra.

    Si no hay evidencia suficiente devuelve la frase de abstención (``abstained=true``).
    """
    return await container.chain.run(body, user)


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Valorar una respuesta",
)
async def feedback(body: FeedbackRequest, container: ContainerDep, user: UserDep) -> FeedbackResponse:
    """Registra (o actualiza) la valoración 👍/👎 del usuario sobre una de sus consultas."""
    if user.user_id is None:
        raise AuthenticationError("El feedback requiere un usuario identificado")

    owned = await container.repository.select(
        "queries",
        {"select": "id", "id": f"eq.{body.query_id}", "user_id": f"eq.{user.user_id}", "limit": "1"},
    )
    if not owned:
        raise NotFoundError("La consulta no existe o no pertenece al usuario")

    rows = await container.repository.insert(
        "feedback",
        {
            "query_id": str(body.query_id),
            "user_id": str(user.user_id),
            "rating": body.rating,
            "comment": body.comment,
        },
        upsert_on="query_id,user_id",
    )
    row = rows[0]
    return FeedbackResponse(id=row["id"], query_id=row["query_id"], rating=row["rating"])
