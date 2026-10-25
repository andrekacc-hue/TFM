/**
 * Tipos y contratos compartidos por las Edge Functions.
 *
 * Los handlers reciben sus dependencias (base de datos, autenticación, aviso al
 * ingest-service) por parámetro: se prueban con dobles sin desplegar nada.
 */

export type Role = "viewer" | "editor" | "admin";
export type SourceType = "manual" | "procedimiento" | "incidente" | "faq";

export interface Profile {
  id: string;
  role: Role;
  area: string;
}

export interface DocumentRow {
  id: string;
  title: string;
  area: string;
  status: "pending" | "processing" | "indexed" | "failed";
  storage_path: string;
}

export interface NewDocument {
  id: string;
  title: string;
  source_type: SourceType;
  area: string;
  storage_path: string;
  status: "pending" | "failed";
  error_message: string | null;
  uploaded_by: string;
  enqueued_at: null;
  metadata: Record<string, unknown>;
}

/** Acceso a datos (implementado con supabase-js y service_role en index.ts). */
export interface Repository {
  getProfile(userId: string): Promise<Profile | null>;
  getDocument(documentId: string): Promise<DocumentRow | null>;
  upsertDocument(document: NewDocument): Promise<void>;
  markPending(documentId: string): Promise<void>;
}

export interface Deps {
  repo: Repository;
  /** Valida un access token de Supabase Auth y devuelve el id de usuario (o null). */
  getUserId(accessToken: string): Promise<string | null>;
  /** Aviso opcional e inmediato al ingest-service; si falla, el outbox poller lo recoge. */
  notifyIngest?(documentId: string): Promise<boolean>;
  webhookSecret: string;
  log?(event: string, data?: Record<string, unknown>): void;
}

/** Fila de storage.objects que envía el trigger SQL (migración 10). */
export interface StorageRecord {
  id: string;
  bucket_id: string;
  name: string;
  owner_id: string | null;
  metadata?: { mimetype?: string; size?: number } | null;
  user_metadata?: { title?: string; source_type?: string } | null;
}
