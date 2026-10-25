// Punto de entrada de la Edge Function on-document-upload (Deno).
// La lógica vive en handler.ts para poder probarla sin desplegar.
import { createDeps } from "../_shared/supabase.ts";
import { error } from "../_shared/http.ts";
import { handleUpload } from "./handler.ts";

const deps = createDeps();

Deno.serve(async (request) => {
  try {
    return await handleUpload(request, deps);
  } catch (exc) {
    deps.log?.("unexpected_error", { error: String(exc) });
    return error(500, "internal_error", "Error interno de la función");
  }
});
