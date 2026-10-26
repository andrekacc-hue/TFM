import { zodResolver } from "@hookform/resolvers/zod";
import { Plus, Target, Trash2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/feedback";
import { Field, Input, Select, Textarea } from "@/components/ui/form-controls";
import { useAddGoldenQuestion, useDeleteGoldenQuestion, useGoldenDataset } from "@/hooks/useAdmin";
import { useAuth } from "@/hooks/useAuth";

const TARGET = 36;
const DIFFICULTY_LABEL = { facil: "Fácil", media: "Media", dificil: "Difícil" } as const;

const schema = z.object({
  question: z.string().trim().min(10, "Mínimo 10 caracteres").max(1000),
  expected_answer: z.string().trim().min(10, "Mínimo 10 caracteres").max(4000),
  difficulty: z.enum(["facil", "media", "dificil"]),
  tags: z.string().max(200).optional(),
});
type Values = z.infer<typeof schema>;

/** Golden dataset: preguntas con respuesta esperada para la evaluación con RAGAs. */
export function GoldenDatasetPanel() {
  const { can } = useAuth();
  const { data, isLoading, error, refetch } = useGoldenDataset();
  const add = useAddGoldenQuestion();
  const remove = useDeleteGoldenQuestion();
  const [adding, setAdding] = useState(false);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { question: "", expected_answer: "", difficulty: "media", tags: "" } });
  const isAdmin = can("admin");
  const count = data?.length ?? 0;

  const onSubmit = form.handleSubmit((values) =>
    add.mutate(
      {
        question: values.question,
        expected_answer: values.expected_answer,
        difficulty: values.difficulty,
        tags: (values.tags ?? "").split(",").map((t) => t.trim()).filter(Boolean),
      },
      {
        onSuccess: () => {
          toast.success("Pregunta añadida al golden dataset");
          form.reset();
          setAdding(false);
        },
        onError: (e) => toast.error(e.message),
      },
    ),
  );

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Target className="size-4 text-primary" aria-hidden /> Golden dataset
          </CardTitle>
          <CardDescription className="mt-1">
            {count} de {TARGET} preguntas de referencia para medir faithfulness, relevancia y recall con RAGAs.
          </CardDescription>
          <div className="mt-3 h-1.5 w-48 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={count} aria-valuemin={0} aria-valuemax={TARGET} aria-label="Progreso del golden dataset">
            <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(100, (count / TARGET) * 100)}%` }} />
          </div>
        </div>
        {isAdmin && !adding && (
          <Button size="sm" onClick={() => setAdding(true)}>
            <Plus /> Añadir
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {adding && (
          <form onSubmit={onSubmit} className="space-y-3 rounded-lg border bg-muted/30 p-4" noValidate>
            <Field id="gq-question" label="Pregunta" error={form.formState.errors.question?.message}>
              <Input placeholder="¿Qué hago si el batch de cierre queda en RUNNING?" {...form.register("question")} />
            </Field>
            <Field id="gq-answer" label="Respuesta esperada" error={form.formState.errors.expected_answer?.message}>
              <Textarea rows={3} {...form.register("expected_answer")} />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field id="gq-difficulty" label="Dificultad">
                <Select {...form.register("difficulty")}>
                  <option value="facil">Fácil</option>
                  <option value="media">Media</option>
                  <option value="dificil">Difícil</option>
                </Select>
              </Field>
              <Field id="gq-tags" label="Etiquetas" hint="Separadas por comas">
                <Input placeholder="batch, core" {...form.register("tags")} />
              </Field>
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" size="sm" onClick={() => setAdding(false)}>
                Cancelar
              </Button>
              <Button type="submit" size="sm" loading={add.isPending}>
                Guardar
              </Button>
            </div>
          </form>
        )}

        {isLoading ? (
          <Skeleton className="h-32" />
        ) : error ? (
          <ErrorState message="No se pudo cargar el golden dataset." onRetry={() => void refetch()} />
        ) : count === 0 ? (
          <EmptyState icon={Target} title="Golden dataset vacío" description="Cárgalo con scripts/run_evaluation.py (tests/golden_dataset.json)." />
        ) : (
          <ul className="divide-y rounded-lg border">
            {data?.map((q) => (
              <li key={q.id} className="flex items-start gap-3 p-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{q.question}</p>
                  <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{q.expected_answer}</p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {q.code && <Badge variant="outline">{q.code}</Badge>}
                    {q.expected_behavior === "abstain" && <Badge variant="warning">Fuera de alcance</Badge>}
                    {q.difficulty && <Badge variant="secondary">{DIFFICULTY_LABEL[q.difficulty]}</Badge>}
                    {q.tags?.map((tag) => (
                      <Badge key={tag} variant="outline">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                </div>
                {isAdmin && (
                  <Button variant="ghost" size="icon" aria-label="Eliminar pregunta" onClick={() => remove.mutate(q.id)}>
                    <Trash2 />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
