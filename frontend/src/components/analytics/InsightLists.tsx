import { FileText, HelpCircle } from "lucide-react";

import { EmptyState, Skeleton } from "@/components/ui/feedback";
import { formatRelative } from "@/lib/utils";
import type { TopDocument, UnansweredQuestion } from "@/types/api";

export function TopDocuments({ documents, loading }: { documents?: TopDocument[]; loading?: boolean }) {
  if (loading) return <Skeleton className="h-48" />;
  if (!documents?.length) return <EmptyState icon={FileText} title="Aún no hay documentos citados" />;
  const max = Math.max(...documents.map((d) => d.citations));
  return (
    <ol className="space-y-3">
      {documents.map((doc) => (
        <li key={doc.document_id}>
          <div className="flex items-baseline justify-between gap-2 text-sm">
            <span className="truncate font-medium">{doc.title}</span>
            <span className="shrink-0 tabular-nums text-muted-foreground">{doc.citations} citas</span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
            <div className="h-full rounded-full bg-primary" style={{ width: `${(doc.citations / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Preguntas que terminaron en abstención: brechas de documentación a cubrir. */
export function UnansweredList({ questions, loading }: { questions?: UnansweredQuestion[]; loading?: boolean }) {
  if (loading) return <Skeleton className="h-48" />;
  if (!questions?.length) {
    return <EmptyState icon={HelpCircle} title="Sin brechas detectadas" description="Todas las consultas del periodo tuvieron evidencia." />;
  }
  return (
    <ul className="divide-y">
      {questions.map((q) => (
        <li key={q.question} className="flex items-start justify-between gap-3 py-2.5 first:pt-0">
          <span className="text-sm">{q.question}</span>
          <span className="shrink-0 text-right text-xs text-muted-foreground">
            {q.times > 1 && <span className="block font-medium text-warning">×{q.times}</span>}
            {formatRelative(q.last_asked)}
          </span>
        </li>
      ))}
    </ul>
  );
}
