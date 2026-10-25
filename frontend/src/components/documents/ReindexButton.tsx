import { RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useReindexDocument } from "@/hooks/useDocuments";
import type { DocumentRow } from "@/types/domain";

/** Reprocesa el documento vía la Edge Function reindex-document (Fase 5). */
export function ReindexButton({ document }: { document: DocumentRow }) {
  const reindex = useReindexDocument();
  return (
    <Button
      variant="ghost"
      size="sm"
      loading={reindex.isPending}
      disabled={document.status === "processing" || document.status === "pending"}
      aria-label={`Reindexar ${document.title}`}
      title="Reindexar"
      onClick={() =>
        reindex.mutate(document.id, {
          onSuccess: () => toast.success(`"${document.title}" se volverá a procesar`),
          onError: (error) => toast.error(error.message),
        })
      }
    >
      {!reindex.isPending && <RefreshCw />}
      <span className="hidden 2xl:inline">Reindexar</span>
    </Button>
  );
}
