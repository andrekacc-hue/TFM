// Punto de entrada de la Edge Function reindex-document (Deno).
import { createDeps } from "../_shared/supabase.ts";
import { error } from "../_shared/http.ts";
import { handleReindex } from "./handler.ts";

const deps = createDeps();

Deno.serve(async (request) => {
  try {
    return await handleReindex(request, deps);
  } catch (exc) {
    deps.log?.("unexpected_error", { error: String(exc) });
    return error(500, "internal_error", "Error interno de la función");
  }
});
