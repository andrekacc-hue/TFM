import { CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { DocumentStatus } from "@/types/domain";

const CONFIG: Record<DocumentStatus, { label: string; variant: "secondary" | "warning" | "success" | "destructive"; icon: typeof Clock }> = {
  pending: { label: "En cola", variant: "secondary", icon: Clock },
  processing: { label: "Procesando", variant: "warning", icon: Loader2 },
  indexed: { label: "Indexado", variant: "success", icon: CheckCircle2 },
  failed: { label: "Error", variant: "destructive", icon: XCircle },
};

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  const { label, variant, icon: Icon } = CONFIG[status] ?? CONFIG.pending;
  return (
    <Badge variant={variant} aria-label={`Estado: ${label}`}>
      <Icon className={status === "processing" ? "animate-spin" : undefined} aria-hidden />
      {label}
    </Badge>
  );
}
