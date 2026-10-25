/** Consultas al asistente y feedback (api-gateway → rag-service). */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { FeedbackResponse, QueryResponse } from "@/types/api";

// Cada consulta o valoración cambia las métricas: el dashboard debe reflejarlas al volver
const METRICS_KEY = ["metrics"] as const;

export function useAskQuestion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (question: string) =>
      apiRequest<QueryResponse>("/api/v1/query", { body: { question, channel: "web" } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: METRICS_KEY }),
  });
}

export function useSendFeedback() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { queryId: string; rating: 1 | -1; comment?: string }) =>
      apiRequest<FeedbackResponse>("/api/v1/feedback", {
        body: { query_id: input.queryId, rating: input.rating, comment: input.comment || null },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: METRICS_KEY }),
  });
}
