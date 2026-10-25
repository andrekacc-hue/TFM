import { CircleSlash, Gauge, MessageSquareText, ThumbsUp, type LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/feedback";
import { formatDuration, formatNumber, formatPercent, plural } from "@/lib/utils";
import type { MetricsSummary } from "@/types/api";

function Kpi({ icon: Icon, label, value, detail }: { icon: LucideIcon; label: string; value: string; detail: string }) {
  return (
    <Card>
      <CardContent className="flex items-start gap-4 p-5">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="size-5" aria-hidden />
        </div>
        <div className="min-w-0">
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="mt-0.5 text-2xl font-semibold tabular-nums tracking-tight">{value}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">{detail}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function MetricsCards({ summary, loading }: { summary?: MetricsSummary; loading?: boolean }) {
  if (loading || !summary) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-[104px]" />
        ))}
      </div>
    );
  }
  const fb = summary.feedback;
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Kpi
        icon={MessageSquareText}
        label="Consultas"
        value={formatNumber(summary.total_queries)}
        detail={`${plural(summary.unique_users, "usuario")} · ${plural(summary.answered, "respondida")}`}
      />
      <Kpi
        icon={Gauge}
        label="Latencia p95"
        value={formatDuration(summary.latency_ms.p95)}
        detail={`mediana ${formatDuration(summary.latency_ms.p50)} · media ${formatDuration(summary.latency_ms.avg)}`}
      />
      <Kpi
        icon={CircleSlash}
        label="Tasa de abstención"
        value={formatPercent(summary.abstention_rate)}
        detail={`${formatNumber(summary.abstained)} sin evidencia · ${formatNumber(summary.blocked_by_guardrails)} bloqueadas`}
      />
      <Kpi
        icon={ThumbsUp}
        label="Satisfacción"
        value={formatPercent(fb.satisfaction_rate)}
        detail={`${formatNumber(fb.positive)} 👍 · ${formatNumber(fb.negative)} 👎 · cobertura ${formatPercent(fb.coverage)}`}
      />
    </div>
  );
}
