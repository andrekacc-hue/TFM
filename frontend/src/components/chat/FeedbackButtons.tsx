import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/form-controls";
import { useSendFeedback } from "@/hooks/useQuery";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

interface Props {
  queryId: string;
  rating?: 1 | -1;
  onRated: (rating: 1 | -1) => void;
}

/** 👍 / 👎 con comentario opcional en el voto negativo (alimenta las métricas de satisfacción). */
export function FeedbackButtons({ queryId, rating, onRated }: Props) {
  const feedback = useSendFeedback();
  const [askComment, setAskComment] = useState(false);
  const [comment, setComment] = useState("");

  const send = (value: 1 | -1, text?: string) =>
    feedback.mutate(
      { queryId, rating: value, comment: text },
      {
        onSuccess: () => {
          onRated(value);
          setAskComment(false);
          toast.success(value === 1 ? "Gracias por tu valoración" : "Gracias, revisaremos esta respuesta");
        },
        onError: (error) => toast.error(error instanceof ApiError ? error.userMessage : "No se pudo enviar la valoración"),
      },
    );

  if (rating) {
    return (
      <p className="text-xs text-muted-foreground" role="status">
        {rating === 1 ? "Marcaste esta respuesta como útil" : "Marcaste esta respuesta como no útil"}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1" role="group" aria-label="Valorar respuesta">
        <span className="mr-1 text-xs text-muted-foreground">¿Te fue útil?</span>
        <Button variant="ghost" size="icon" className="size-8" aria-label="Respuesta útil" disabled={feedback.isPending} onClick={() => send(1)}>
          <ThumbsUp />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className={cn("size-8", askComment && "bg-accent")}
          aria-label="Respuesta no útil"
          aria-expanded={askComment}
          disabled={feedback.isPending}
          onClick={() => setAskComment((v) => !v)}
        >
          <ThumbsDown />
        </Button>
      </div>
      {askComment && (
        <form
          className="flex flex-col gap-2 sm:flex-row sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            send(-1, comment);
          }}
        >
          <Textarea
            aria-label="Comentario opcional"
            placeholder="¿Qué faltó o qué estaba mal? (opcional)"
            value={comment}
            maxLength={2000}
            onChange={(e) => setComment(e.target.value)}
            className="min-h-16 text-xs"
          />
          <Button type="submit" size="sm" variant="secondary" loading={feedback.isPending}>
            Enviar
          </Button>
        </form>
      )}
    </div>
  );
}
