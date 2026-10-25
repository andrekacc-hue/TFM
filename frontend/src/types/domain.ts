/** Filas de las tablas del esquema tfm leídas directamente con supabase-js (RLS). */
import type { Role } from "./auth";
import type { SourceType } from "./api";

export type DocumentStatus = "pending" | "processing" | "indexed" | "failed";

export interface DocumentRow {
  id: string;
  title: string;
  source_type: SourceType;
  area: string;
  status: DocumentStatus;
  error_message: string | null;
  chunk_count: number | null;
  version: number;
  storage_path: string;
  created_at: string;
  updated_at: string;
  metadata: {
    original_filename?: string;
    size_bytes?: number;
    origin?: string;
    ingestion?: { format?: string; chunks?: number; duration_ms?: number; pages?: number; finished_at?: string };
    demo?: boolean;
  } | null;
}

export type Severity = "baja" | "media" | "alta" | "critica";

export interface Incident {
  id: string;
  code: string;
  system_affected: string;
  symptom: string;
  diagnosis: string | null;
  resolution: string | null;
  severity: Severity | null;
  resolved_at: string | null;
  created_at: string;
  created_by: string | null;
}

export type IncidentInput = Pick<Incident, "code" | "system_affected" | "symptom" | "diagnosis" | "resolution" | "severity"> & {
  resolved: boolean;
};

export type Difficulty = "facil" | "media" | "dificil";

export interface GoldenQuestion {
  id: string;
  question: string;
  expected_answer: string;
  expected_document_id: string | null;
  tags: string[] | null;
  difficulty: Difficulty | null;
  created_at: string;
}

export interface Profile {
  id: string;
  email: string | null;
  full_name: string | null;
  role: Role;
  area: string;
  created_at: string;
}
