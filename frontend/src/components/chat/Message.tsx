import { AlertTriangle, Bot, Clock, Copy, ShieldAlert, UserRound } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDuration } from "@/lib/utils";
import type { ChatMessage } from "@/stores/chat-store";

import { linkCitations } from "./citations";
import { FeedbackButtons } from "./FeedbackButtons";
import { SourceCitation } from "./SourceCitation";

const PENDING_STEPS = ["Buscando en la base de conocimientos…", "Ordenando por relevancia…", "Redactando la respuesta…"];

function PendingAnswer() {
  return (
    <div className="flex items-center gap-3 text-sm text-muted-foreground" role="status">
      <span className="flex gap-1" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span key={i} className="size-1.5 animate-bounce rounded-full bg-primary" style={{ animationDelay: `${i * 150}ms` }} />
        ))}
      </span>
      <span className="animate-pulse">{PENDING_STEPS[0]}</span>
    </div>
  );
}

function Avatar({ role }: { role: ChatMessage["role"] }) {
  return role === "user" ? (
    <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary" aria-hidden>
      <UserRound className="size-4" />
    </div>
  ) : (
    <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground" aria-hidden>
      <Bot className="size-4" />
    </div>
  );
}

export function Message({ message, onRated }: { message: ChatMessage; onRated: (rating: 1 | -1) => void }) {
  const [highlight, setHighlight] = useState<number | null>(null);

  if (message.role === "user") {
    return (
      <div className="flex justify-end gap-3 animate-fade-in">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground shadow-sm">
          <span className="sr-only">Tu pregunta: </span>
          {message.content}
        </div>
        <Avatar role="user" />
      </div>
    );
  }

  const response = message.response;
  const blocked = response?.abstention_reason?.startsWith("guardrail:");

  return (
    <div className="flex gap-3 animate-fade-in">
      <Avatar role="assistant" />
      <article className="min-w-0 flex-1 rounded-2xl rounded-tl-sm border bg-card px-4 py-3 shadow-sm" aria-label="Respuesta del asistente">
        {message.pending && <PendingAnswer />}

        {message.error && (
          <div role="alert" className="flex items-start gap-2 text-sm text-destructive">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <span>{message.error}</span>
          </div>
        )}

        {response && (
          <div className="space-y-4">
            {response.abstained && (
              <Badge variant={blocked ? "destructive" : "warning"}>
                {blocked ? <ShieldAlert /> : <AlertTriangle />}
                {blocked ? "Solicitud bloqueada por política de seguridad" : "Sin evidencia suficiente"}
              </Badge>
            )}

            <div className="prose-answer">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ href, children }) =>
                    href?.startsWith("#fuente-") ? (
                      <a
                        href={href}
                        onClick={() => setHighlight(Number(href.replace("#fuente-", "")))}
                        className="mx-0.5 inline-flex items-center rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary no-underline hover:bg-primary/20"
                      >
                        {children}
                      </a>
                    ) : (
                      <a href={href} target="_blank" rel="noreferrer" className="text-primary underline">
                        {children}
                      </a>
                    ),
                }}
              >
                {linkCitations(response.answer, response.sources)}
              </ReactMarkdown>
            </div>

            {response.sources.length > 0 && (
              <section aria-label="Fuentes consultadas">
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Fuentes ({response.sources.length})
                </h4>
                <ol className="space-y-2">
                  {response.sources.map((source) => (
                    <SourceCitation key={source.chunk_id} source={source} highlighted={highlight === source.index} />
                  ))}
                </ol>
              </section>
            )}

            <footer className="flex flex-col gap-3 border-t pt-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1" title="Latencia total">
                  <Clock className="size-3.5" aria-hidden /> {formatDuration(response.timings.total_ms)}
                </span>
                {response.llm_model && <span>{response.llm_model}</span>}
                {response.trace_id && (
                  <Button
                    variant="link"
                    size="sm"
                    className="h-auto p-0 text-xs text-muted-foreground"
                    onClick={() => {
                      void navigator.clipboard?.writeText(response.trace_id ?? "");
                      toast.success("ID de traza copiado");
                    }}
                    aria-label="Copiar ID de traza para soporte"
                  >
                    <Copy className="size-3" /> traza {response.trace_id.slice(0, 8)}
                  </Button>
                )}
              </div>
              {response.query_id && !blocked && (
                <FeedbackButtons queryId={response.query_id} rating={message.rating} onRated={onRated} />
              )}
            </footer>
          </div>
        )}
      </article>
    </div>
  );
}
