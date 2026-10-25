import { Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Skeleton } from "@/components/ui/feedback";
import type { TimeseriesPoint } from "@/types/api";

const HOUR = 3_600_000;
const DAY = 86_400_000;

/**
 * Completa con ceros los intervalos sin consultas para que el gráfico muestre el periodo
 * entero. PostgreSQL agrupa en UTC (date_trunc), así que los intervalos se generan en UTC.
 */
export function fillBuckets(points: TimeseriesPoint[], days: number, now: Date = new Date()): TimeseriesPoint[] {
  const hourly = days <= 1;
  const step = hourly ? HOUR : DAY;
  const end = Math.floor(now.getTime() / step) * step;
  const count = hourly ? 24 : days;
  const byBucket = new Map(points.map((p) => [Math.floor(new Date(p.bucket).getTime() / step) * step, p]));
  return Array.from({ length: count }, (_, i) => {
    const time = end - (count - 1 - i) * step;
    return (
      byBucket.get(time) ?? {
        bucket: new Date(time).toISOString(),
        queries: 0,
        abstained: 0,
        avg_latency_ms: null,
        p95_latency_ms: null,
        positive_feedback: 0,
        negative_feedback: 0,
      }
    );
  });
}

export function bucketLabel(iso: string, hourly: boolean): string {
  const date = new Date(iso);
  return hourly
    ? date.toLocaleTimeString("es-EC", { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString("es-EC", { day: "2-digit", month: "short", timeZone: "UTC" });
}

/** Consultas respondidas vs. abstenciones por intervalo. */
export function UsageChart({ points, loading, days }: { points?: TimeseriesPoint[]; loading?: boolean; days: number }) {
  if (loading) return <Skeleton className="h-64" />;

  const hourly = days <= 1;
  const filled = fillBuckets(points ?? [], days);
  const total = filled.reduce((sum, p) => sum + p.queries, 0);
  const data = filled.map((p) => ({
    label: bucketLabel(p.bucket, hourly),
    Respondidas: p.queries - p.abstained,
    Abstenciones: p.abstained,
  }));

  return (
    <div className="h-64" role="img" aria-label={`Gráfico de consultas del periodo: ${total} en total`}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
          <XAxis dataKey="label" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} interval="preserveStartEnd" minTickGap={16} />
          <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} />
          <Tooltip contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Area type="monotone" dataKey="Respondidas" stackId="1" stroke="hsl(var(--chart-1))" fill="hsl(var(--chart-1))" fillOpacity={0.35} />
          <Area type="monotone" dataKey="Abstenciones" stackId="1" stroke="hsl(var(--chart-3))" fill="hsl(var(--chart-3))" fillOpacity={0.35} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
