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
  code: string | null;
  question: string;
  expected_answer: string;
  expected_document_id: string | null;
  expected_behavior: "answer" | "abstain";
  tags: string[] | null;
  difficulty: Difficulty | null;
  created_at: string;
}

export const RAGAS_METRICS = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"] as const;
export type RagasMetric = (typeof RAGAS_METRICS)[number];

export type EvaluationOutcome =
  | "respondida"
  | "abstencion_correcta"
  | "falsa_abstencion_llm"
  | "falsa_abstencion_recuperacion"
  | "respuesta_indebida"
  | "error";

/** Agregados que calcula scripts/run_evaluation.py. */
export interface EvaluationMetrics {
  ragas: Record<RagasMetric, number | null>;
  ragas_n: Record<RagasMetric, number>;
  answer_rate: number | null;
  false_abstention_rate: number | null;
  false_abstention_llm_rate: number | null;
  false_abstention_retrieval_rate: number | null;
  correct_abstention_rate: number | null;
  hit_rate: number | null;
  mrr: number | null;
  latency_ms: { p50: number | null; p95: number | null; mean: number | null };
  outcomes: Partial<Record<EvaluationOutcome, number>>;
  attempts: number;
  errors: number;
  unstable_questions: string[];
}

export interface EvaluationQuestionResult {
  id: string;
  question: string;
  expected_answer: string;
  expected_behavior: "answer" | "abstain";
  expected_document: string | null;
  attempts: { outcome: EvaluationOutcome; answer: string; abstention_reason: string | null; contexts: string[] }[];
  scores: Partial<Record<RagasMetric, number | null>>;
}

export interface EvaluationRun {
  id: string;
  created_at: string;
  label: string | null;
  llm_model: string | null;
  judge_model: string | null;
  questions: number;
  metrics: EvaluationMetrics;
  config: { repeat?: number };
  duration_s: number | null;
}

export interface Profile {
  id: string;
  email: string | null;
  full_name: string | null;
  role: Role;
  area: string;
  created_at: string;
}
