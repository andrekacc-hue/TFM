import { AlertTriangle, CheckCircle2, CircleSlash, FlaskConical, XCircle } from "lucide-react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/feedback";
import { useEvaluationResults, useEvaluationRuns } from "@/hooks/useEvaluation";
import { formatDateTime, formatDuration, formatPercent } from "@/lib/utils";
import { RAGAS_METRICS, type EvaluationOutcome, type EvaluationQuestionResult, type EvaluationRun, type RagasMetric } from "@/types/domain";

export const METRIC_INFO: Record<RagasMetric, { label: string; description: string; target: number; color: string }> = {
  faithfulness: { label: "Faithfulness", description: "Respuestas respaldadas por las fuentes", target: 0.85, color: "hsl(var(--chart-1))" },
  answer_relevancy: { label: "Answer relevancy", description: "Responde a lo que se preguntó", target: 0.8, color: "hsl(var(--chart-2))" },
  context_precision: { label: "Context precision", description: "Fragmentos útiles primero", target: 0.75, color: "hsl(var(--chart-3))" },
  context_recall: { label: "Context recall", description: "El contexto cubre la respuesta", target: 0.8, color: "hsl(var(--chart-4))" },
};

const OUTCOME_INFO: Record<EvaluationOutcome, { label: string; variant: "success" | "warning" | "destructive" }> = {
  respondida: { label: "Respondida", variant: "success" },
  abstencion_correcta: { label: "Abstención correcta", variant: "success" },
  falsa_abstencion_llm: { label: "Falsa abstención (LLM)", variant: "warning" },
  falsa_abstencion_recuperacion: { label: "Falsa abstención (recuperación)", variant: "warning" },
  respuesta_indebida: { label: "Respuesta indebida", variant: "destructive" },
  error: { label: "Error", variant: "destructive" },
};

export type MetricStatus = "ok" | "near" | "low" | "none";

/** Estado frente al objetivo: cumple, a menos de 0,15, o por debajo. */
export function metricStatus(metric: RagasMetric, value: number | null | undefined): MetricStatus {
  if (value === null || value === undefined) return "none";
  const { target } = METRIC_INFO[metric];
  return value >= target ? "ok" : value >= target - 0.15 ? "near" : "low";
}

const STATUS_ICON = {
  ok: { icon: CheckCircle2, className: "text-success", label: "Cumple el objetivo" },
  near: { icon: AlertTriangle, className: "text-warning", label: "Cerca del objetivo" },
  low: { icon: XCircle, className: "text-destructive", label: "Por debajo del objetivo" },
  none: { icon: CircleSlash, className: "text-muted-foreground", label: "Sin datos" },
} as const;

/** Preguntas a revisar: alguna repetición no terminó en el resultado esperado. */
export function questionsToReview(results: EvaluationQuestionResult[]): EvaluationQuestionResult[] {
  return results.filter((r) => r.attempts.some((a) => a.outcome !== "respondida" && a.outcome !== "abstencion_correcta"));
}

function score(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toFixed(2);
}

function LatestRun({ run }: { run: EvaluationRun }) {
  const m = run.metrics;
  const extra = [
    { label: "Falsa abstención", value: formatPercent(m.false_abstention_rate), detail: `LLM ${formatPercent(m.false_abstention_llm_rate)} · recuperación ${formatPercent(m.false_abstention_retrieval_rate)}` },
    { label: "Abstención correcta", value: formatPercent(m.correct_abstention_rate), detail: "Preguntas fuera de alcance" },
    { label: "Hit rate de recuperación", value: formatPercent(m.hit_rate), detail: `MRR ${score(m.mrr)}` },
    { label: "Latencia p50", value: formatDuration(m.latency_ms.p50), detail: `p95 ${formatDuration(m.latency_ms.p95)}` },
  ];
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {RAGAS_METRICS.map((metric) => {
          const value = m.ragas[metric];
          const status = STATUS_ICON[metricStatus(metric, value)];
          const info = METRIC_INFO[metric];
          return (
            <div key={metric} className="rounded-lg border p-4">
              <div className="flex items-center gap-1.5 text-sm font-medium">
                <status.icon className={`size-4 ${status.className}`} aria-label={status.label} />
                {info.label}
              </div>
              <p className="mt-2 text-2xl font-semibold tabular-nums">{score(value)}</p>
              <p className="text-xs text-muted-foreground">
                {info.description} · objetivo ≥ {info.target.toFixed(2)} · n={m.ragas_n[metric]}
              </p>
            </div>
          );
        })}
      </div>
      <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {extra.map((item) => (
          <div key={item.label} className="rounded-md bg-muted/60 px-3 py-2">
            <dt className="text-xs text-muted-foreground">{item.label}</dt>
            <dd className="text-lg font-semibold tabular-nums">{item.value}</dd>
            <dd className="text-xs text-muted-foreground">{item.detail}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function Trend({ runs }: { runs: EvaluationRun[] }) {
  const data = [...runs].reverse().map((run) => ({
    name: formatDateTime(run.created_at),
    ...Object.fromEntries(RAGAS_METRICS.map((metric) => [metric, run.metrics.ragas[metric]])),
  }));
  return (
    <div className="h-56" role="img" aria-label="Evolución de las métricas RAGAs por ejecución">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
          <XAxis dataKey="name" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
          <YAxis domain={[0, 1]} tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
          <Tooltip
            formatter={(value: number) => score(value)}
            contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {RAGAS_METRICS.map((metric) => (
            <Line key={metric} type="monotone" dataKey={metric} name={METRIC_INFO[metric].label} stroke={METRIC_INFO[metric].color} strokeWidth={2} dot={{ r: 4 }} connectNulls />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function ReviewList({ runId }: { runId: string }) {
  const { data, isLoading } = useEvaluationResults(runId);
  if (isLoading) return <Skeleton className="h-24" />;
  const review = questionsToReview(data ?? []);
  if (review.length === 0) {
    return <p className="text-sm text-muted-foreground">Todas las preguntas terminaron con el comportamiento esperado.</p>;
  }
  return (
    <ul className="divide-y rounded-lg border">
      {review.map((r) => (
        <li key={r.id} className="space-y-1.5 p-3">
          <p className="text-sm">
            <span className="font-medium">{r.id}</span> · {r.question}
          </p>
          <div className="flex flex-wrap gap-1">
            {r.attempts.map((a, i) => (
              <Badge key={i} variant={OUTCOME_INFO[a.outcome].variant}>
                {OUTCOME_INFO[a.outcome].label}
              </Badge>
            ))}
          </div>
          {r.expected_document && <p className="text-xs text-muted-foreground">Fuente esperada: {r.expected_document}</p>}
        </li>
      ))}
    </ul>
  );
}

/** Resultados de scripts/run_evaluation.py: última ejecución, evolución y preguntas a revisar. */
export function EvaluationPanel() {
  const { data: runs, isLoading, error, refetch } = useEvaluationRuns();
  const latest = runs?.[0];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FlaskConical className="size-4 text-primary" aria-hidden /> Evaluación con RAGAs
        </CardTitle>
        <CardDescription>
          {latest
            ? `Última ejecución ${formatDateTime(latest.created_at)} · ${latest.questions} preguntas × ${latest.config.repeat ?? 1} · LLM ${latest.llm_model ?? "—"} · juez ${latest.judge_model ?? "—"}`
            : "Métricas de calidad sobre el golden dataset"}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {isLoading ? (
          <Skeleton className="h-48" />
        ) : error ? (
          <ErrorState message="No se pudieron cargar las evaluaciones." onRetry={() => void refetch()} />
        ) : !latest ? (
          <EmptyState icon={FlaskConical} title="Sin evaluaciones" description="Ejecuta scripts/run_evaluation.py para medir el asistente con RAGAs." />
        ) : (
          <>
            <LatestRun run={latest} />
            {runs.length > 1 && (
              <section>
                <h3 className="mb-2 text-sm font-medium">Evolución por ejecución</h3>
                <Trend runs={runs} />
              </section>
            )}
            <section>
              <h3 className="mb-2 text-sm font-medium">Preguntas a revisar (última ejecución)</h3>
              <ReviewList runId={latest.id} />
            </section>
          </>
        )}
      </CardContent>
    </Card>
  );
}
