"""Endpoints de ingesta: subida, reindexación manual, estado y cola."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from pydantic import BaseModel

from app.core.loaders import content_type_for
from app.dependencies import ContainerDep, UserDep, require_internal_key
from shared.exceptions import AppError, AuthorizationError, NotFoundError, UpstreamServiceError, ValidationAppError
from shared.logging import get_logger
from shared.schemas import SourceType, UserContext

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/ingest", tags=["ingesta"], dependencies=[Depends(require_internal_key)])

AREA_PATTERN = r"^[a-z0-9_-]+$"


class IngestAccepted(BaseModel):
    """Documento registrado y encolado."""

    document_id: UUID
    status: str
    storage_path: str
    message_id: str


class DocumentStatus(BaseModel):
    """Estado de ingesta de un documento."""

    document_id: UUID
    title: str
    area: str
    status: Literal["pending", "processing", "indexed", "failed"]
    chunk_count: int | None
    error_message: str | None
    updated_at: datetime | None
    ingestion: dict[str, Any] | None = None


class DuplicateDocumentError(AppError):
    status_code = 409
    code = "duplicate_document"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


def safe_filename(filename: str) -> str:
    """Nombre de archivo seguro para Storage: ASCII, sin rutas ni caracteres especiales."""
    name = PurePath(filename.replace("\\", "/")).name
    stem, suffix = PurePath(name).stem, PurePath(name).suffix.lower()
    ascii_stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    ascii_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_stem).strip("._-")[:100] or "documento"
    return f"{ascii_stem}{suffix}"


def authorize_area(user: UserContext, area: str) -> None:
    """Solo editores/admin suben; un editor solo en su área (defensa en profundidad del gateway)."""
    if user.role is None:
        return  # llamada de sistema sin usuario (scripts de carga, evaluación)
    if user.role not in ("editor", "admin"):
        raise AuthorizationError("Solo editores o administradores pueden cargar documentos")
    if user.role == "editor" and user.area and area != user.area:
        raise AuthorizationError(f"Un editor solo puede cargar documentos en su área ({user.area})")


@router.post(
    "",
    response_model=IngestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Subir un documento y encolar su ingesta",
    responses={409: {"description": "Documento duplicado"}, 413: {"description": "Archivo demasiado grande"},
               415: {"description": "Formato no soportado"}, 503: {"description": "Cola no disponible"}},
)
async def upload_document(
    container: ContainerDep,
    user: UserDep,
    file: Annotated[UploadFile, File(description="PDF, DOCX, Markdown o TXT")],
    source_type: Annotated[SourceType, Form()],
    area: Annotated[str, Form(pattern=AREA_PATTERN)],
    title: Annotated[str | None, Form(max_length=300)] = None,
) -> IngestAccepted:
    """Sube el archivo a Storage, registra el documento (``pending``) y publica el evento.

    El procesamiento (extracción, chunking, embeddings) lo hace el worker de forma
    asíncrona; el estado se sigue con Supabase Realtime o ``GET /v1/ingest/{id}``.
    """
    settings = container.settings
    authorize_area(user, area)
    filename = file.filename or "documento"
    content_type = content_type_for(filename)

    max_bytes = settings.max_upload_mb * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise PayloadTooLargeError(f"El archivo supera el máximo de {settings.max_upload_mb} MB")
    if not content:
        raise ValidationAppError("El archivo está vacío")

    sha256 = hashlib.sha256(content).hexdigest()
    existing = await container.repository.select(
        "documents", {"select": "id,title,status", "area": f"eq.{area}", "metadata->>sha256": f"eq.{sha256}", "limit": "1"}
    )
    if existing:
        raise DuplicateDocumentError(
            "Ya existe un documento idéntico en esta área",
            details={"document_id": existing[0]["id"], "title": existing[0]["title"], "status": existing[0]["status"]},
        )

    document_id = uuid4()
    storage_path = f"{area}/{document_id}/{safe_filename(filename)}"
    await container.storage.upload(settings.storage_bucket, storage_path, content, content_type=content_type)

    try:
        await container.repository.insert(
            "documents",
            {
                "id": str(document_id),
                "title": (title or PurePath(filename).stem).strip(),
                "source_type": source_type,
                "area": area,
                "storage_path": storage_path,
                "status": "pending",
                # Lo encola esta misma petición: el outbox poller no debe volver a publicarlo
                "enqueued_at": datetime.now(UTC).isoformat(),
                "uploaded_by": str(user.user_id) if user.user_id else None,
                "metadata": {
                    "original_filename": filename,
                    "content_type": content_type,
                    "size_bytes": len(content),
                    "sha256": sha256,
                },
            },
            returning=False,
        )
    except Exception:
        # Sin registro en la BD el archivo quedaría huérfano en Storage
        await container.storage.remove(settings.storage_bucket, [storage_path])
        raise

    message_id = await _enqueue(container, document_id, reason="upload")
    logger.info("document_uploaded", document_id=str(document_id), area=area, bytes=len(content), format=content_type)
    return IngestAccepted(document_id=document_id, status="pending", storage_path=storage_path, message_id=message_id)


@router.post(
    "/{document_id}/reindex",
    response_model=IngestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Reprocesar un documento (ingesta manual)",
)
async def reindex_document(document_id: UUID, container: ContainerDep, user: UserDep) -> IngestAccepted:
    """Vuelve a encolar un documento existente (p. ej. tras cambiar el chunking o un fallo)."""
    document = await _get_document(container, document_id)
    authorize_area(user, document["area"])
    await container.repository.update(
        "documents",
        {"id": f"eq.{document_id}"},
        {"status": "pending", "error_message": None, "enqueued_at": datetime.now(UTC).isoformat()},
    )
    message_id = await _enqueue(container, document_id, reason="reindex")
    return IngestAccepted(document_id=document_id, status="pending", storage_path=document["storage_path"], message_id=message_id)


@router.get("/queue/stats", summary="Estado de la cola de ingesta")
async def queue_stats(container: ContainerDep) -> dict[str, Any]:
    """Mensajes en el stream, pendientes de ACK y en la DLQ; contadores del worker."""
    stats = await container.queue.stats()
    consumer = container.consumer
    stats["worker"] = {
        "consumer": consumer.consumer_name,
        "alive": consumer.is_alive(),
        "processed": consumer.processed,
        "failed": consumer.failed,
    }
    return stats


@router.get("/{document_id}", response_model=DocumentStatus, summary="Estado de ingesta de un documento")
async def document_status(document_id: UUID, container: ContainerDep) -> DocumentStatus:
    document = await _get_document(container, document_id)
    return DocumentStatus(
        document_id=document["id"],
        title=document["title"],
        area=document["area"],
        status=document["status"],
        chunk_count=document.get("chunk_count"),
        error_message=document.get("error_message"),
        updated_at=document.get("updated_at"),
        ingestion=(document.get("metadata") or {}).get("ingestion"),
    )


# ----------------------------------------------------------------------
async def _get_document(container: ContainerDep, document_id: UUID) -> dict[str, Any]:
    rows = await container.repository.select(
        "documents",
        {"select": "id,title,area,status,chunk_count,error_message,updated_at,storage_path,metadata",
         "id": f"eq.{document_id}", "limit": "1"},
    )
    if not rows:
        raise NotFoundError("Documento no encontrado")
    return rows[0]


async def _enqueue(container: ContainerDep, document_id: UUID, *, reason: str) -> str:
    try:
        return await container.queue.publish(str(document_id), reason=reason)
    except UpstreamServiceError:
        await container.repository.update(
            "documents",
            {"id": f"eq.{document_id}"},
            {"status": "failed", "error_message": "Cola de ingesta no disponible; usa 'reindex' cuando se restablezca"},
        )
        raise
