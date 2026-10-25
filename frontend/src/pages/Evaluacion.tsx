import { BadgeCheck, Gauge, ShieldCheck } from "lucide-react";

import { GoldenDatasetPanel } from "@/components/analytics/GoldenDatasetPanel";
import { LatencyChart } from "@/components/analytics/LatencyChart";
import { PageHeader } from "@/components/layout/AppLayout";
import { RequireRole } from "@/components/layout/ProtectedRoute";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/feedback";
import { useMetricsSummary } from "@/hooks/useMetrics";
import { formatNumber, formatPercent, plural } from "@/lib/utils";

/** Indicadores de calidad operativos (30 días). Las métricas RAGAs se añaden en la Fase 8. */
function QualityIndicators() {
  const { data, isLoading } = useMetricsSummary(30);
  if (isLoading || !data) return <Skeleton className="h-40" />;
  const indicators = [
    {
      icon: BadgeCheck,
      label: "Satisfacción de usuarios",
      value: formatPercent(data.feedback.satisfaction_rate),
      detail: plural(data.feedback.count, "valoración", "valoraciones"),
    },
    {
      icon: Gauge,
      label: "Abstención responsable",
      value: formatPercent(data.abstention_rate),
      detail: "Consultas sin evidencia suficiente (no inventa)",
    },
    {
      icon: ShieldCheck,
      label: "Bloqueos de seguridad",
      value: formatNumber(data.blocked_by_guardrails),
      detail: "Intentos de inyección o evasión detenidos",
    },
  ];
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {indicators.map(({ icon: Icon, label, value, detail }) => (
        <Card key={label}>
          <CardContent className="p-5">
            <Icon className="size-5 text-primary" aria-hidden />
            <p className="mt-3 text-2xl font-semibold tabular-nums">{value}</p>
            <p className="text-sm font-medium">{label}</p>
            <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function EvaluacionContent() {
  const summary = useMetricsSummary(30);
  return (
    <>
      <PageHeader title="Evaluación" description="Calidad del asistente: indicadores operativos de los últimos 30 días y golden dataset" />
      <div className="space-y-6">
        <QualityIndicators />
        <div className="grid gap-6 xl:grid-cols-[1fr_24rem]">
          <GoldenDatasetPanel />
          <Card>
            <CardHeader>
              <CardTitle>Rendimiento del pipeline</CardTitle>
              <CardDescription>Latencia por etapa (30 días)</CardDescription>
            </CardHeader>
            <CardContent>
              <LatencyChart summary={summary.data} loading={summary.isLoading} />
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

export default function Evaluacion() {
  return (
    <RequireRole minimum="editor">
      <EvaluacionContent />
    </RequireRole>
  );
}
