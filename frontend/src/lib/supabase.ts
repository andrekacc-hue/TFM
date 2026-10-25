/**
 * Cliente de Supabase del navegador.
 *
 * Usa la clave PÚBLICA (sb_publishable_): todo acceso a datos pasa por las políticas RLS
 * con la sesión del usuario. Esquema por defecto: tfm.
 */
import { createClient } from "@supabase/supabase-js";

import { env } from "./env";

export const supabase = createClient(env.supabaseUrl, env.supabaseAnonKey, {
  db: { schema: "tfm" },
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
});

export const DOCUMENTS_BUCKET = "documents";
