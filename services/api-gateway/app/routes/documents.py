"""Gestión de documentos: subida, reindexación y estado (proxy al ingest-service)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.dependencies import ContainerDep
from app.middleware.auth import CurrentUser, require_role
from app.middleware.rate_limit import rate_limit
from shared.exceptions import AppError, ValidationAppError

router = APIRouter(prefix="/api/v1/documents", tags=["documentos"])


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


async def read_limited_body(request: Request, max_bytes: int) -> bytes:
    """Lee el cuerpo sin cargar más de ``max_bytes`` en memoria."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise PayloadTooLargeError(f"El archivo supera el máximo de {max_bytes // (1024 * 1024)} MB")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise PayloadTooLargeError(f"El archivo supera el máximo de {max_bytes // (1024 * 1024)} MB")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "",
    status_code=202,
    summary="Subir un documento",
    dependencies=[Depends(require_role("editor")), Depends(rate_limit("upload", "rate_limit_upload"))],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file", "source_type", "area"],
                        "properties": {
                            "file": {"type": "string", "format": "binary", "description": "PDF, DOCX, Markdown o TXT"},
                            "source_type": {"type": "string", "enum": ["manual", "procedimiento", "incidente", "faq"]},
                            "area": {"type": "string", "pattern": "^[a-z0-9_-]+$"},
                            "title": {"type": "string"},
                        },
                    }
                }
            },
        }
    },
)
async def upload(request: Request, user: CurrentUser, container: ContainerDep) -> Response:
    """Reenvía el multipart sin reinterpretarlo; el ingest-service valida formato, área y duplicados.

    Un editor solo puede subir documentos a su área; un admin, a cualquiera.
    """
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("multipart/form-data"):
        raise ValidationAppError("Se esperaba multipart/form-data con el campo 'file'")
    # Margen de 1 MB para los campos del formulario y los separadores multipart
    body = await read_limited_body(request, (container.settings.max_upload_mb + 1) * 1024 * 1024)
    return await container.ingest.forward("POST", "/v1/ingest", user=user, content=body, content_type=content_type)


@router.get("/queue/stats", summary="Estado de la cola de ingesta", dependencies=[Depends(require_role("admin"))])
async def queue_stats(user: CurrentUser, container: ContainerDep) -> Response:
    return await container.ingest.forward("GET", "/v1/ingest/queue/stats", user=user)


@router.post(
    "/{document_id}/reindex",
    status_code=202,
    summary="Reprocesar un documento",
    dependencies=[Depends(require_role("editor")), Depends(rate_limit("upload", "rate_limit_upload"))],
)
async def reindex(document_id: UUID, user: CurrentUser, container: ContainerDep) -> Response:
    return await container.ingest.forward("POST", f"/v1/ingest/{document_id}/reindex", user=user)


@router.get("/{document_id}/status", summary="Estado de ingesta", dependencies=[Depends(require_role("editor"))])
async def status(document_id: UUID, user: CurrentUser, container: ContainerDep) -> Response:
    return await container.ingest.forward("GET", f"/v1/ingest/{document_id}", user=user)
