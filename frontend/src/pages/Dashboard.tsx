import { Database, Download } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { TopDocuments, UnansweredList } from "@/components/analytics/InsightLists";
import { LatencyChart } from "@/components/analytics/LatencyChart";
import { MetricsCards } from "@/components/analytics/MetricsCards";
import { UsageChart } from "@/components/analytics/UsageChart";
import { PageHeader } from "@/components/layout/AppLayout";
import { RequireRole } from "@/components/layout/ProtectedRoute";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/feedback";
import { Select } from "@/components/ui/form-controls";
import { useAuth } from "@/hooks/useAuth";
import {
  exportQueries,
  useKnowledgeBase,
  useMetricsSummary,
  useTimeseries,
  useTopDocuments,
  useUnanswered,
  type PeriodDays,
} from "@/hooks/useMetrics";
import { ApiError } from "@/lib/api-client";
import { formatNumber } from "@/lib/utils";

function KnowledgeBaseCard() {
  const { data } = useKnowledgeBase();
  const items = [
    ["Documentos indexados", data?.by_status.indexed],
    ["Fragmentos", data?.chunks],
    ["Incidentes", data?.incidents],
    ["Golden dataset", data?.golden_questions],
  ] as const;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Database className="size-4 text-primary" aria-hidden /> Base de conocimientos
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-3">
          {items.map(([label, value]) => (
            <div key={label} className="rounded-md bg-muted/60 p-3">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="mt-1 text-xl font-semibold tabular-nums">{formatNumber(value ?? null)}</dd>
            </div>
          ))}
        </dl>
        {data && Object.keys(data.by_area).length > 0 && (
          <p className="mt-3 text-xs text-muted-foreground">
            Por área: {Object.entries(data.by_area).map(([area, n]) => `${area} (${n})`).join(" · ")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function DashboardContent() {
  const { can } = useAuth();
  const [days, setDays] = useState<PeriodDays>(7);
  const [exporting, setExporting] = useState(false);
  const summary = useMetricsSummary(days);
  const series = useTimeseries(days);
  const top = useTopDocuments(days);
  const unanswered = useUnanswered(days);

  const onExport = async () => {
    setExporting(true);
    try {
      await exportQueries(days, "csv");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.userMessage : "No se pudo exportar");
    } finally {
      setExporting(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Uso, calidad y rendimiento del asistente"
        actions={
          <>
            <Select aria-label="Periodo" className="w-40" value={days} onChange={(e) => setDays(Number(e.target.value) as PeriodDays)}>
              <option value={1}>Últimas 24 horas</option>
              <option value={7}>Últimos 7 días</option>
              <option value={30}>Últimos 30 días</option>
              <option value={90}>Últimos 90 días</option>
            </Select>
            {can("admin") && (
              <Button variant="outline" onClick={() => void onExport()} loading={exporting}>
                {!exporting && <Download />} Exportar CSV
              </Button>
            )}
          </>
        }
      />

      {summary.error ? (
        <ErrorState message={summary.error instanceof ApiError ? summary.error.userMessage : "No se pudieron cargar las métricas"} onRetry={() => void summary.refetch()} />
      ) : (
        <div className="space-y-6">
          <MetricsCards summary={summary.data} loading={summary.isLoading} />
          <div className="grid gap-6 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader>
                <CardTitle>Consultas</CardTitle>
                <CardDescription>Respondidas y abstenciones por {days === 1 ? "hora" : "día"}</CardDescription>
              </CardHeader>
              <CardContent>
                <UsageChart points={series.data} loading={series.isLoading} days={days} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Latencia por etapa</CardTitle>
                <CardDescription>Media de las consultas respondidas</CardDescription>
              </CardHeader>
              <CardContent>
                <LatencyChart summary={summary.data} loading={summary.isLoading} />
              </CardContent>
            </Card>
          </div>
          <div className="grid gap-6 lg:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle>Documentos más citados</CardTitle>
              </CardHeader>
              <CardContent>
                <TopDocuments documents={top.data} loading={top.isLoading} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Preguntas sin respuesta</CardTitle>
                <CardDescription>Brechas de documentación a cubrir</CardDescription>
              </CardHeader>
              <CardContent>
                <UnansweredList questions={unanswered.data} loading={unanswered.isLoading} />
              </CardContent>
            </Card>
            <KnowledgeBaseCard />
          </div>
        </div>
      )}
    </>
  );
}

export default function Dashboard() {
  return (
    <RequireRole minimum="editor">
      <DashboardContent />
    </RequireRole>
  );
}
