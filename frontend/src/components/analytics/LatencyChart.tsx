import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { EmptyState, Skeleton } from "@/components/ui/feedback";
import { formatDuration } from "@/lib/utils";
import type { MetricsSummary } from "@/types/api";

const STAGES = [
  { key: "retrieval", label: "Recuperación", color: "hsl(var(--chart-2))" },
  { key: "rerank", label: "Reranking", color: "hsl(var(--chart-5))" },
  { key: "generation", label: "Generación LLM", color: "hsl(var(--chart-1))" },
] as const;

/** Latencia media por etapa del pipeline RAG + percentiles. */
export function LatencyChart({ summary, loading }: { summary?: MetricsSummary; loading?: boolean }) {
  if (loading) return <Skeleton className="h-64" />;
  const stages = summary?.stage_avg_ms;
  if (!summary || !stages || STAGES.every((s) => stages[s.key] === null)) {
    return <EmptyState title="Sin datos de latencia" description="Aparecen cuando el asistente responde consultas." />;
  }

  const data = STAGES.map((s) => ({ name: s.label, ms: stages[s.key] ?? 0, color: s.color }));
  const percentiles = [
    ["p50", summary.latency_ms.p50],
    ["p90", summary.latency_ms.p90],
    ["p95", summary.latency_ms.p95],
    ["p99", summary.latency_ms.p99],
  ] as const;

  return (
    <div className="space-y-4">
      <div className="h-48" role="img" aria-label={`Latencia media por etapa: ${data.map((d) => `${d.name} ${formatDuration(d.ms)}`).join(", ")}`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 24, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" horizontal={false} />
            <XAxis type="number" tickFormatter={(v: number) => formatDuration(v)} tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
            <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} />
            <Tooltip
              formatter={(value: number) => formatDuration(value)}
              contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
            />
            <Bar dataKey="ms" name="Media" radius={[0, 4, 4, 0]}>
              {data.map((d) => (
                <Cell key={d.name} fill={d.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <dl className="grid grid-cols-4 gap-2 text-center">
        {percentiles.map(([label, value]) => (
          <div key={label} className="rounded-md bg-muted/60 px-2 py-1.5">
            <dt className="text-xs uppercase text-muted-foreground">{label}</dt>
            <dd className="text-sm font-semibold tabular-nums">{formatDuration(value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
