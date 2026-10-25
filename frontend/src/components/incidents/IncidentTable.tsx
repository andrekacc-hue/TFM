import { LifeBuoy, Pencil, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, Skeleton, Table, Td, Th } from "@/components/ui/feedback";
import { Input } from "@/components/ui/form-controls";
import { useAuth } from "@/hooks/useAuth";
import { useDeleteIncident, useIncidents } from "@/hooks/useIncidents";
import { formatDateTime } from "@/lib/utils";
import type { Incident, Severity } from "@/types/domain";

const SEVERITY: Record<Severity, { label: string; variant: "secondary" | "warning" | "destructive" | "default" }> = {
  baja: { label: "Baja", variant: "secondary" },
  media: { label: "Media", variant: "default" },
  alta: { label: "Alta", variant: "warning" },
  critica: { label: "Crítica", variant: "destructive" },
};

export function SeverityBadge({ severity }: { severity: Severity | null }) {
  if (!severity) return <span className="text-muted-foreground">—</span>;
  const { label, variant } = SEVERITY[severity];
  return <Badge variant={variant}>{label}</Badge>;
}

export function IncidentTable({ onEdit }: { onEdit: (incident: Incident) => void }) {
  const { data, isLoading, error, refetch } = useIncidents();
  const remove = useDeleteIncident();
  const { can } = useAuth();
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return data ?? [];
    return (data ?? []).filter((i) => [i.code, i.system_affected, i.symptom].some((v) => v.toLowerCase().includes(term)));
  }, [data, search]);

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
        <Input className="pl-8" placeholder="Buscar por código, sistema o síntoma…" aria-label="Buscar incidentes" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      {isLoading ? (
        <Skeleton className="h-64" />
      ) : error ? (
        <ErrorState message="No se pudieron cargar los incidentes." onRetry={() => void refetch()} />
      ) : filtered.length === 0 ? (
        <EmptyState icon={LifeBuoy} title="Sin incidentes" />
      ) : (
        <Table>
          <caption className="sr-only">Incidentes registrados</caption>
          <thead>
            <tr>
              <Th>Incidente</Th>
              <Th className="hidden md:table-cell">Síntoma</Th>
              <Th>Severidad</Th>
              <Th className="hidden sm:table-cell">Estado</Th>
              {can("editor") && (
                <Th className="w-0">
                  <span className="sr-only">Acciones</span>
                </Th>
              )}
            </tr>
          </thead>
          <tbody>
            {filtered.map((incident) => (
              <tr key={incident.id} className="align-top hover:bg-muted/40">
                <Td>
                  <p className="font-mono text-xs font-semibold">{incident.code}</p>
                  <p className="mt-0.5 text-sm">{incident.system_affected}</p>
                </Td>
                <Td className="hidden max-w-md md:table-cell">
                  <p className="line-clamp-2 text-sm">{incident.symptom}</p>
                  {incident.resolution && <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">✓ {incident.resolution}</p>}
                </Td>
                <Td>
                  <SeverityBadge severity={incident.severity} />
                </Td>
                <Td className="hidden whitespace-nowrap text-xs sm:table-cell">
                  {incident.resolved_at ? (
                    <span className="text-success">Resuelto · {formatDateTime(incident.resolved_at)}</span>
                  ) : (
                    <span className="text-warning">Abierto</span>
                  )}
                </Td>
                {can("editor") && (
                  <Td className="whitespace-nowrap text-right">
                    <Button variant="ghost" size="icon" aria-label={`Editar ${incident.code}`} onClick={() => onEdit(incident)}>
                      <Pencil />
                    </Button>
                    {can("admin") && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-destructive hover:text-destructive"
                        aria-label={`Eliminar ${incident.code}`}
                        loading={remove.isPending && remove.variables === incident.id}
                        onClick={() => {
                          if (window.confirm(`¿Eliminar el incidente ${incident.code}? Esta acción no se puede deshacer.`)) {
                            remove.mutate(incident.id, {
                              onSuccess: () => toast.success(`${incident.code} eliminado`),
                              onError: (e) => toast.error(e.message),
                            });
                          }
                        }}
                      >
                        <Trash2 />
                      </Button>
                    )}
                  </Td>
                )}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </div>
  );
}
