/** Métricas y salud del sistema (api-gateway → analytics-service). */
import { useQuery } from "@tanstack/react-query";

import { apiRequest, downloadFile } from "@/lib/api-client";
import { env } from "@/lib/env";
import type {
  HealthResponse,
  KnowledgeBaseStats,
  MetricsSummary,
  TimeseriesPoint,
  TopDocument,
  UnansweredQuestion,
} from "@/types/api";

export type PeriodDays = 1 | 7 | 30 | 90;

export function periodParams(days: PeriodDays, now: Date = new Date()) {
  const from = new Date(now.getTime() - days * 86_400_000);
  return { from: from.toISOString(), to: now.toISOString() };
}

/**
 * Rango estable para la clave de caché: el final se redondea HACIA ARRIBA al minuto
 * siguiente. Redondearlo hacia abajo excluía las consultas del minuto en curso (el rango es
 * [from, to)) y el dashboard no mostraba lo recién preguntado.
 */
export function stablePeriod(days: PeriodDays, now: Date = new Date()) {
  const end = new Date(now);
  end.setSeconds(0, 0);
  end.setMinutes(end.getMinutes() + 1);
  return periodParams(days, end);
}

export function useMetricsSummary(days: PeriodDays, enabled = true) {
  return useQuery({
    queryKey: ["metrics", "summary", days],
    queryFn: () => apiRequest<MetricsSummary>("/api/v1/analytics/summary", { params: stablePeriod(days) }),
    enabled,
  });
}

export function useTimeseries(days: PeriodDays, enabled = true) {
  const bucket = days <= 1 ? "hour" : "day";
  return useQuery({
    queryKey: ["metrics", "timeseries", days],
    queryFn: async () =>
      (await apiRequest<{ points: TimeseriesPoint[] }>("/api/v1/analytics/timeseries", { params: { ...stablePeriod(days), bucket } }))
        .points,
    enabled,
  });
}

export function useTopDocuments(days: PeriodDays, enabled = true) {
  return useQuery({
    queryKey: ["metrics", "top-documents", days],
    queryFn: async () =>
      (await apiRequest<{ documents: TopDocument[] }>("/api/v1/analytics/top-documents", { params: { ...stablePeriod(days), limit: 5 } }))
        .documents,
    enabled,
  });
}

export function useUnanswered(days: PeriodDays, enabled = true) {
  return useQuery({
    queryKey: ["metrics", "unanswered", days],
    queryFn: async () =>
      (await apiRequest<{ questions: UnansweredQuestion[] }>("/api/v1/analytics/unanswered", { params: { ...stablePeriod(days), limit: 10 } }))
        .questions,
    enabled,
  });
}

export function useKnowledgeBase(enabled = true) {
  return useQuery({
    queryKey: ["metrics", "knowledge-base"],
    queryFn: () => apiRequest<KnowledgeBaseStats>("/api/v1/analytics/knowledge-base"),
    enabled,
  });
}

/** Salud agregada del sistema (público, sin sesión). */
export function useSystemHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const response = await fetch(`${env.gatewayUrl}/ready`);
      return (await response.json()) as HealthResponse;
    },
    refetchInterval: 60_000,
    retry: false,
  });
}

export function exportQueries(days: PeriodDays, format: "csv" | "json") {
  return downloadFile(`/api/v1/reports/queries.${format}`, periodParams(days), `consultas.${format}`);
}
