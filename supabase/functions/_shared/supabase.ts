/**
 * Dependencias reales de las Edge Functions (supabase-js con la clave secreta).
 *
 * Secretos de la función (``supabase secrets set``; los nombres SUPABASE_* están reservados):
 *   TFM_SECRET_KEY          clave sb_secret_… (service_role)
 *   TFM_WEBHOOK_SECRET      secreto compartido con el trigger de Storage (Vault)
 *   TFM_INGEST_API_URL      opcional: URL pública del ingest-service para encolar al instante
 *   TFM_INTERNAL_API_KEY    opcional: clave interna del ingest-service
 * SUPABASE_URL lo inyecta la plataforma.
 */

import { createClient } from "@supabase/supabase-js";
import type { Deps, DocumentRow, NewDocument, Profile } from "./types.ts";

function requireEnv(name: string): string {
  const value = Deno.env.get(name);
  if (!value) throw new Error(`Falta el secreto ${name} (supabase secrets set ${name}=...)`);
  return value;
}

export function createDeps(): Deps {
  const url = requireEnv("SUPABASE_URL");
  const secretKey = requireEnv("TFM_SECRET_KEY");
  const client = createClient(url, secretKey, {
    db: { schema: "tfm" },
    auth: { persistSession: false, autoRefreshToken: false },
  });

  const ingestUrl = Deno.env.get("TFM_INGEST_API_URL")?.replace(/\/$/, "");
  const internalKey = Deno.env.get("TFM_INTERNAL_API_KEY");

  return {
    webhookSecret: requireEnv("TFM_WEBHOOK_SECRET"),

    repo: {
      async getProfile(userId: string): Promise<Profile | null> {
        const { data, error } = await client.from("profiles").select("id, role, area").eq("id", userId).maybeSingle();
        if (error) throw new Error(`profiles: ${error.message}`);
        return data as Profile | null;
      },
      async getDocument(documentId: string): Promise<DocumentRow | null> {
        const { data, error } = await client
          .from("documents")
          .select("id, title, area, status, storage_path")
          .eq("id", documentId)
          .maybeSingle();
        if (error) throw new Error(`documents: ${error.message}`);
        return data as DocumentRow | null;
      },
      async upsertDocument(document: NewDocument): Promise<void> {
        const { error } = await client.from("documents").upsert(document, { onConflict: "id" });
        if (error) throw new Error(`documents upsert: ${error.message}`);
      },
      async markPending(documentId: string): Promise<void> {
        const { error } = await client
          .from("documents")
          .update({ status: "pending", error_message: null, enqueued_at: null })
          .eq("id", documentId);
        if (error) throw new Error(`documents update: ${error.message}`);
      },
    },

    async getUserId(accessToken: string): Promise<string | null> {
      const { data, error } = await client.auth.getUser(accessToken);
      return error || !data.user ? null : data.user.id;
    },

    notifyIngest: ingestUrl && internalKey
      ? async (documentId: string): Promise<boolean> => {
        try {
          const response = await fetch(`${ingestUrl}/v1/ingest/${documentId}/reindex`, {
            method: "POST",
            headers: { "X-Internal-Api-Key": internalKey },
            signal: AbortSignal.timeout(5000),
          });
          return response.ok;
        } catch {
          return false;
        }
      }
      : undefined,

    log(event: string, data: Record<string, unknown> = {}) {
      console.log(JSON.stringify({ event, ...data, ts: new Date().toISOString() }));
    },
  };
}
