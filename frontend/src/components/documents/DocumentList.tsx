import { FileText, Radio, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, Skeleton, Table, Td, Th } from "@/components/ui/feedback";
import { Input, Select } from "@/components/ui/form-controls";
import { useAuth } from "@/hooks/useAuth";
import { useDocuments } from "@/hooks/useDocuments";
import { formatRelative, plural, SOURCE_TYPE_LABELS } from "@/lib/utils";
import type { DocumentStatus } from "@/types/domain";

import { DocumentStatusBadge } from "./DocumentStatusBadge";
import { ReindexButton } from "./ReindexButton";

export function DocumentList() {
  const { data, isLoading, error, refetch } = useDocuments();
  const { can, me } = useAuth();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<DocumentStatus | "all">("all");

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (data ?? []).filter(
      (d) => (status === "all" || d.status === status) && (!term || d.title.toLowerCase().includes(term) || d.area.includes(term)),
    );
  }, [data, search, status]);

  const canReindex = (area: string) => me?.role === "admin" || (can("editor") && me?.area === area);

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
          <Input className="pl-8" placeholder="Buscar por título o área…" aria-label="Buscar documentos" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <Select className="sm:w-44" aria-label="Filtrar por estado" value={status} onChange={(e) => setStatus(e.target.value as DocumentStatus | "all")}>
          <option value="all">Todos los estados</option>
          <option value="indexed">Indexados</option>
          <option value="pending">En cola</option>
          <option value="processing">Procesando</option>
          <option value="failed">Con error</option>
        </Select>
        <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground" title="Los estados se actualizan en tiempo real">
          <Radio className="size-3.5 text-success" aria-hidden /> En vivo
        </span>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
      ) : error ? (
        <ErrorState message="No se pudieron cargar los documentos." onRetry={() => void refetch()} />
      ) : filtered.length === 0 ? (
        <EmptyState icon={FileText} title={data?.length ? "Sin resultados" : "Aún no hay documentos"} description={data?.length ? "Prueba con otro filtro." : undefined} />
      ) : (
        <Table>
          <caption className="sr-only">Documentos de la base de conocimientos</caption>
          <thead>
            <tr>
              <Th>Documento</Th>
              <Th className="hidden md:table-cell">Área</Th>
              <Th>Estado</Th>
              <Th className="hidden 2xl:table-cell">Fragmentos</Th>
              <Th className="hidden sm:table-cell">Actualizado</Th>
              <Th className="w-0">
                <span className="sr-only">Acciones</span>
              </Th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((doc) => (
              <tr key={doc.id} className="hover:bg-muted/40">
                <Td className="min-w-[14rem]">
                  <p className="font-medium">{doc.title}</p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                    {SOURCE_TYPE_LABELS[doc.source_type] ?? doc.source_type}
                    {doc.metadata?.ingestion?.format && <span>· {doc.metadata.ingestion.format.toUpperCase()}</span>}
                    {doc.chunk_count ? <span className="2xl:hidden">· {plural(doc.chunk_count, "fragmento")}</span> : null}
                    {doc.metadata?.demo && <Badge variant="outline">demo</Badge>}
                  </p>
                  {doc.status === "failed" && doc.error_message && <p className="mt-1 text-xs text-destructive">{doc.error_message}</p>}
                </Td>
                <Td className="hidden md:table-cell">
                  <Badge variant="outline">{doc.area}</Badge>
                </Td>
                <Td>
                  <DocumentStatusBadge status={doc.status} />
                </Td>
                <Td className="hidden tabular-nums 2xl:table-cell">{doc.chunk_count ?? "—"}</Td>
                <Td className="hidden whitespace-nowrap text-muted-foreground sm:table-cell">{formatRelative(doc.updated_at)}</Td>
                <Td className="text-right">{canReindex(doc.area) && <ReindexButton document={doc} />}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </div>
  );
}
