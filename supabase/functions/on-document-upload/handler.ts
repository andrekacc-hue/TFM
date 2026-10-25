/**
 * on-document-upload: registra en tfm.documents los archivos que un usuario sube
 * directamente a Storage (bucket "documents") desde el portal.
 *
 * La invoca el trigger SQL tfm_on_document_object_created (migración 10) vía pg_net,
 * autenticándose con el secreto compartido ``x-webhook-secret``. El documento queda en
 * "pending" con ``enqueued_at = null``: el outbox poller del ingest-service lo publica en
 * Redis (o, si está configurado, se avisa al ingest-service al instante).
 */

import { canManageArea, normalizeSourceType, parseStoragePath, SUPPORTED_EXTENSIONS, titleFromFilename } from "../_shared/documents.ts";
import { error, json, safeEqual } from "../_shared/http.ts";
import type { Deps, StorageRecord } from "../_shared/types.ts";

export async function handleUpload(request: Request, deps: Deps): Promise<Response> {
  if (request.method !== "POST") return error(405, "method_not_allowed", "Usa POST");

  const secret = request.headers.get("x-webhook-secret") ?? "";
  if (!secret || !safeEqual(secret, deps.webhookSecret)) {
    return error(401, "invalid_webhook_secret", "Secreto de webhook inválido");
  }

  let record: StorageRecord;
  try {
    record = (await request.json()).record;
  } catch {
    return error(400, "invalid_body", "Cuerpo JSON inválido");
  }
  if (!record?.name || record.bucket_id !== "documents") {
    return json(200, { ignored: true, reason: "bucket_no_gestionado" });
  }
  if (!record.owner_id) {
    // Subidas con service_role (ingest-service): ya registran su documento
    return json(200, { ignored: true, reason: "subida_de_servicio" });
  }

  const path = parseStoragePath(record.name);
  if (!path) return error(422, "invalid_path", "La ruta debe ser {area}/{document_id}/{archivo}");

  const profile = await deps.repo.getProfile(record.owner_id);
  if (!canManageArea(profile, path.area)) {
    // Las políticas de Storage ya deberían haberlo impedido: defensa en profundidad
    deps.log?.("upload_rejected", { owner: record.owner_id, area: path.area, role: profile?.role });
    return error(403, "forbidden", "El usuario no puede cargar documentos en esta área");
  }

  const supported = SUPPORTED_EXTENSIONS.includes(path.extension);
  const userMetadata = record.user_metadata ?? {};
  await deps.repo.upsertDocument({
    id: path.documentId,
    title: (userMetadata.title ?? "").trim() || titleFromFilename(path.filename),
    source_type: normalizeSourceType(userMetadata.source_type),
    area: path.area,
    storage_path: record.name,
    // Un formato no soportado se registra como "failed" para que el usuario lo vea en el portal
    status: supported ? "pending" : "failed",
    error_message: supported ? null : `Formato '${path.extension || "sin extensión"}' no soportado. Usa PDF, DOCX, Markdown o TXT.`,
    uploaded_by: record.owner_id,
    enqueued_at: null,
    metadata: {
      original_filename: path.filename,
      content_type: record.metadata?.mimetype ?? null,
      size_bytes: record.metadata?.size ?? null,
      storage_object_id: record.id,
      origin: "storage-trigger",
    },
  });

  let via = "outbox";
  if (supported && deps.notifyIngest && await deps.notifyIngest(path.documentId)) via = "ingest-api";
  deps.log?.("document_registered", { document_id: path.documentId, area: path.area, supported, via });

  return json(202, { document_id: path.documentId, status: supported ? "pending" : "failed", via });
}
