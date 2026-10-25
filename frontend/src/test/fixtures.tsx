import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

import type { QueryResponse, SourceCitation } from "@/types/api";

export function renderWithProviders(ui: ReactElement, { route = "/" }: { route?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

export function source(overrides: Partial<SourceCitation> = {}): SourceCitation {
  return {
    index: 1,
    document_id: "d1",
    chunk_id: "c1",
    title: "PROC-OPS-014 Reinicio del batch de cierre diario",
    source_type: "procedimiento",
    chunk_index: 3,
    section: "Paso 3 — Relanzamiento",
    page: null,
    similarity: 0.82,
    rerank_score: 4.1,
    excerpt: "Relanzar el job desde el último checkpoint confirmado.",
    ...overrides,
  };
}

export function queryResponse(overrides: Partial<QueryResponse> = {}): QueryResponse {
  return {
    query_id: "q-123",
    answer:
      "**Problema:** batch en RUNNING.\n\n1. Relanzar desde el checkpoint. [Fuente: PROC-OPS-014 Reinicio del batch de cierre diario, Paso 3 — Relanzamiento]",
    sources: [source()],
    abstained: false,
    abstention_reason: null,
    llm_provider: "ollama",
    llm_model: "gemma4:31b",
    usage: { tokens_input: 800, tokens_output: 200 },
    timings: { guardrails_ms: 1, retrieval_ms: 200, rerank_ms: 210, generation_ms: 1700, total_ms: 2111 },
    warnings: [],
    trace_id: "abcdef1234567890",
    ...overrides,
  };
}
