/**
 * reindex-document: reprocesa un documento a petición de un usuario del portal.
 *
 *   supabase.functions.invoke("reindex-document", { body: { document_id } })
 *
 * Requiere la sesión del usuario (Authorization: Bearer <access_token>). Solo editores de
 * su área o administradores. Deja el documento en "pending" con ``enqueued_at = null`` para
 * que el outbox poller lo publique (o avisa al ingest-service si está configurado).
 */

import { canManageArea } from "../_shared/documents.ts";
import { bearerToken, CORS_HEADERS, error, json } from "../_shared/http.ts";
import type { Deps } from "../_shared/types.ts";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function handleReindex(request: Request, deps: Deps): Promise<Response> {
  if (request.method === "OPTIONS") return new Response("ok", { headers: CORS_HEADERS });
  if (request.method !== "POST") return error(405, "method_not_allowed", "Usa POST");

  const token = bearerToken(request);
  const userId = token ? await deps.getUserId(token) : null;
  if (!userId) return error(401, "unauthenticated", "Se requiere iniciar sesión");

  let documentId: unknown;
  try {
    documentId = (await request.json()).document_id;
  } catch {
    return error(400, "invalid_body", "Cuerpo JSON inválido");
  }
  if (typeof documentId !== "string" || !UUID.test(documentId)) {
    return error(422, "validation_error", "document_id debe ser un UUID");
  }

  const [profile, document] = await Promise.all([deps.repo.getProfile(userId), deps.repo.getDocument(documentId)]);
  if (!document) return error(404, "not_found", "Documento no encontrado");
  if (!canManageArea(profile, document.area)) {
    return error(403, "forbidden", "Solo un editor del área o un administrador puede reindexar este documento");
  }
  if (document.status === "processing") {
    return error(409, "already_processing", "El documento se está procesando; espera a que termine");
  }

  await deps.repo.markPending(documentId);
  let via = "outbox";
  if (deps.notifyIngest && await deps.notifyIngest(documentId)) via = "ingest-api";
  deps.log?.("reindex_requested", { document_id: documentId, user_id: userId, via });

  return json(202, { document_id: documentId, status: "pending", via });
}
