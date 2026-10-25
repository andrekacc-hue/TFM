/** Contratos de la API pública del api-gateway (ver docs/api/openapi.yaml). */

export type Channel = "web" | "teams" | "api";
export type SourceType = "manual" | "procedimiento" | "incidente" | "faq";

export interface SourceCitation {
  index: number;
  document_id: string;
  chunk_id: string;
  title: string;
  source_type: SourceType | string;
  chunk_index: number;
  section: string | null;
  page: number | null;
  similarity: number;
  rerank_score: number | null;
  excerpt: string;
}

export interface Timings {
  guardrails_ms: number;
  retrieval_ms: number;
  rerank_ms: number;
  generation_ms: number;
  total_ms: number;
}

export interface QueryResponse {
  query_id: string | null;
  answer: string;
  sources: SourceCitation[];
  abstained: boolean;
  abstention_reason: string | null;
  llm_provider: string | null;
  llm_model: string | null;
  usage: { tokens_input: number | null; tokens_output: number | null };
  timings: Timings;
  warnings: string[];
  trace_id: string | null;
}

export interface FeedbackResponse {
  id: string;
  query_id: string;
  rating: number;
}

export interface UploadAccepted {
  document_id: string;
  status: string;
  storage_path: string;
  message_id: string;
}

export interface ApiErrorBody {
  error: { code: string; message: string; trace_id?: string | null; details?: Record<string, unknown> };
}

export interface MetricsSummary {
  from: string;
  to: string;
  total_queries: number;
  unique_users: number;
  answered: number;
  abstained: number;
  abstention_rate: number | null;
  blocked_by_guardrails: number;
  latency_ms: { avg: number | null; p50: number | null; p90: number | null; p95: number | null; p99: number | null };
  stage_avg_ms: { retrieval: number | null; rerank: number | null; generation: number | null };
  tokens: { input: number; output: number };
  feedback: { count: number; positive: number; negative: number; satisfaction_rate: number | null; coverage: number | null };
  by_channel: Record<string, number>;
  by_model: Record<string, number>;
}

export interface TimeseriesPoint {
  bucket: string;
  queries: number;
  abstained: number;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  positive_feedback: number;
  negative_feedback: number;
}

export interface TopDocument {
  document_id: string;
  title: string;
  citations: number;
  queries: number;
  avg_similarity: number;
}

export interface UnansweredQuestion {
  question: string;
  times: number;
  last_asked: string;
  reason: string | null;
}

export interface KnowledgeBaseStats {
  documents: number;
  by_status: Record<string, number>;
  by_area: Record<string, number>;
  by_type: Record<string, number>;
  chunks: number;
  incidents: number;
  golden_questions: number;
}

export interface HealthResponse {
  status: "ok" | "degraded" | "error";
  service: string;
  version: string;
  checks: Record<string, string>;
}
