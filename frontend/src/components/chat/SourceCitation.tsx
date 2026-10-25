import { ChevronDown, FileText } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { cn, sectionLabel, SOURCE_TYPE_LABELS as TYPE_LABELS } from "@/lib/utils";
import type { SourceCitation as Source } from "@/types/api";

/** Fuente documental de una respuesta: título, sección, relevancia y extracto desplegable. */
export function SourceCitation({ source, highlighted = false }: { source: Source; highlighted?: boolean }) {
  const [open, setOpen] = useState(false);
  const relevance = Math.round(source.similarity * 100);
  const panelId = `fuente-panel-${source.chunk_id}`;

  return (
    <li
      id={`fuente-${source.index}`}
      className={cn("rounded-md border bg-background transition-shadow", highlighted && "ring-2 ring-primary")}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex w-full items-start gap-3 rounded-md p-3 text-left hover:bg-accent/50"
      >
        <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded bg-primary/10 text-xs font-semibold text-primary">
          {source.index}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5 text-sm font-medium">
            <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
            <span className="truncate">{source.title}</span>
          </span>
          <span className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <Badge variant="secondary">{TYPE_LABELS[source.source_type] ?? source.source_type}</Badge>
            <span>{sectionLabel(source.section, source.chunk_index, source.page)}</span>
            <span aria-label={`Similitud ${relevance} por ciento`}>· similitud {relevance}%</span>
          </span>
        </span>
        <ChevronDown className={cn("mt-1 size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open && (
        <p id={panelId} className="border-t px-3 py-2.5 text-sm leading-relaxed text-muted-foreground">
          {source.excerpt}
        </p>
      )}
    </li>
  );
}
