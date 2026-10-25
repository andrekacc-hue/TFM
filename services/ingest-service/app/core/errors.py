"""Errores de la ingesta, clasificados por si tiene sentido reintentar."""

from __future__ import annotations

from shared.exceptions import AppError


class IngestError(AppError):
    """Error de ingesta. ``retryable`` indica si el worker debe reintentar."""

    retryable: bool = False
    status_code = 422
    code = "ingest_error"


class UnsupportedDocumentError(IngestError):
    """Formato no soportado."""

    status_code = 415
    code = "unsupported_document"


class EmptyDocumentError(IngestError):
    """El documento no tiene texto extraíble (p. ej. PDF escaneado sin OCR)."""

    code = "empty_document"


class CorruptDocumentError(IngestError):
    """El archivo no se puede leer con el formato declarado."""

    code = "corrupt_document"


class TransientIngestError(IngestError):
    """Fallo temporal de una dependencia (Storage, PostgREST, red): se reintenta."""

    retryable = True
    status_code = 503
    code = "ingest_transient_error"
