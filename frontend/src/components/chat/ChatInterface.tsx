import { Eraser, SendHorizontal, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/form-controls";
import { useAskQuestion } from "@/hooks/useQuery";
import { ApiError } from "@/lib/api-client";
import { useChatStore } from "@/stores/chat-store";

import { Message } from "./Message";

const MAX_CHARS = 2000;
export const SUGGESTIONS = [
  "El batch de cierre diario quedó en RUNNING, ¿qué hago?",
  "Varios cajeros rechazan retiros con código 91",
  "¿Cómo se renueva el certificado del HSM?",
  "La VPN de guardia me da error VPN-403",
];

export function ChatInterface() {
  const { messages, ask, resolve, fail, rate, clear } = useChatStore();
  const askQuestion = useAskQuestion();
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const busy = askQuestion.isPending;

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [messages.length, busy]);

  const submit = (text: string) => {
    const question = text.trim();
    if (question.length < 3 || busy) return;
    setDraft("");
    const { answerId } = ask(question);
    askQuestion.mutate(question, {
      onSuccess: (response) => resolve(answerId, response),
      onError: (error) => fail(answerId, error instanceof ApiError ? error.userMessage : "No se pudo obtener respuesta"),
      onSettled: () => inputRef.current?.focus(),
    });
  };

  return (
    <div className="flex h-[calc(100vh-11rem)] min-h-[28rem] flex-col rounded-xl border bg-muted/30">
      <div role="log" aria-live="polite" aria-label="Conversación con el asistente" className="flex-1 space-y-5 overflow-y-auto p-4 sm:p-6">
        {messages.length === 0 ? (
          <div className="mx-auto flex max-w-xl flex-col items-center gap-4 py-8 text-center">
            <div className="flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
              <Sparkles className="size-6" aria-hidden />
            </div>
            <div>
              <h2 className="text-lg font-semibold">¿En qué te ayudo hoy?</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Respondo solo con la documentación autorizada de TI Producción y cito cada fuente. Si no hay evidencia
                suficiente, te recomendaré escalar el caso.
              </p>
            </div>
            <div className="grid w-full gap-2 sm:grid-cols-2">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => submit(suggestion)}
                  className="rounded-lg border bg-card p-3 text-left text-sm shadow-sm transition-colors hover:border-primary/40 hover:bg-accent"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((message) => <Message key={message.id} message={message} onRated={(rating) => rate(message.id, rating)} />)
        )}
        <div ref={endRef} />
      </div>

      <form
        className="border-t bg-card p-3 sm:p-4"
        onSubmit={(e) => {
          e.preventDefault();
          submit(draft);
        }}
      >
        <div className="flex items-end gap-2">
          <Textarea
            ref={inputRef}
            aria-label="Escribe tu consulta"
            placeholder="Describe el problema técnico…"
            title="Enter para enviar · Mayús+Enter para salto de línea"
            value={draft}
            maxLength={MAX_CHARS}
            rows={2}
            disabled={busy}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(draft);
              }
            }}
            className="max-h-40 min-h-12 resize-none"
          />
          <Button type="submit" size="icon" className="size-12 shrink-0" loading={busy} disabled={draft.trim().length < 3} aria-label="Enviar consulta">
            {!busy && <SendHorizontal />}
          </Button>
        </div>
        <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
          <span>No incluyas contraseñas ni datos de clientes: se enmascaran automáticamente.</span>
          <div className="flex items-center gap-3">
            <span aria-live="polite">
              {draft.length}/{MAX_CHARS}
            </span>
            {messages.length > 0 && (
              <Button type="button" variant="ghost" size="sm" className="h-7" onClick={clear} disabled={busy}>
                <Eraser /> Nueva conversación
              </Button>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}
