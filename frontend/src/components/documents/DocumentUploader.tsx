import { zodResolver } from "@hookform/resolvers/zod";
import { FileUp, UploadCloud } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { useAuth } from "@/hooks/useAuth";
import { useUploadDocument } from "@/hooks/useDocuments";
import { ApiError } from "@/lib/api-client";
import { AREA_PATTERN, cn, formatBytes } from "@/lib/utils";

export const ACCEPTED = [".pdf", ".docx", ".md", ".markdown", ".txt"];
export const MAX_MB = 50;

export const uploadSchema = z.object({
  title: z.string().max(300, "Máximo 300 caracteres").optional(),
  sourceType: z.enum(["manual", "procedimiento", "incidente", "faq"]),
  area: z.string().regex(AREA_PATTERN, "Solo minúsculas, números, '-' o '_'"),
});
type UploadForm = z.infer<typeof uploadSchema>;

export function validateFile(file: File): string | null {
  const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!ACCEPTED.includes(extension)) return `Formato no soportado. Usa ${ACCEPTED.join(", ")}`;
  if (file.size > MAX_MB * 1024 * 1024) return `El archivo supera ${MAX_MB} MB`;
  if (file.size === 0) return "El archivo está vacío";
  return null;
}

export function DocumentUploader() {
  const { me } = useAuth();
  const upload = useUploadDocument();
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const isAdmin = me?.role === "admin";

  const form = useForm<UploadForm>({
    resolver: zodResolver(uploadSchema),
    defaultValues: { title: "", sourceType: "procedimiento", area: me?.area ?? "general" },
  });

  const pick = (candidate: File | undefined) => {
    if (!candidate) return;
    const error = validateFile(candidate);
    setFileError(error);
    setFile(error ? null : candidate);
  };

  const onSubmit = form.handleSubmit((values) => {
    if (!file) {
      setFileError("Selecciona un archivo");
      return;
    }
    upload.mutate(
      { file, title: values.title, sourceType: values.sourceType, area: values.area },
      {
        onSuccess: () => {
          toast.success(`"${values.title || file.name}" se subió y está en cola para procesarse`);
          setFile(null);
          form.reset({ ...values, title: "" });
        },
        onError: (error) => {
          if (error instanceof ApiError && error.code === "duplicate_document") {
            toast.error(`Ya existe: "${String(error.details.title ?? "documento idéntico")}"`);
          } else {
            toast.error(error instanceof ApiError ? error.userMessage : error.message);
          }
        },
      },
    );
  });

  const { errors } = form.formState;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Subir documento</CardTitle>
        <CardDescription>PDF, Word, Markdown o texto (máx. {MAX_MB} MB). Se indexa en segundos.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <label
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              pick(e.dataTransfer.files[0]);
            }}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 text-center transition-colors focus-within:ring-2 focus-within:ring-ring",
              dragging ? "border-primary bg-accent" : "border-input hover:border-primary/50 hover:bg-accent/40",
              fileError && "border-destructive",
            )}
          >
            <input
              type="file"
              className="sr-only"
              accept={ACCEPTED.join(",")}
              onChange={(e) => pick(e.target.files?.[0])}
              aria-describedby="file-help"
              data-testid="file-input"
            />
            {file ? (
              <>
                <FileUp className="size-6 text-primary" aria-hidden />
                <span className="text-sm font-medium">{file.name}</span>
                <span className="text-xs text-muted-foreground">{formatBytes(file.size)} · haz clic para cambiar</span>
              </>
            ) : (
              <>
                <UploadCloud className="size-6 text-muted-foreground" aria-hidden />
                <span className="text-sm font-medium">Arrastra un archivo o haz clic para seleccionarlo</span>
                <span id="file-help" className="text-xs text-muted-foreground">{ACCEPTED.join(" · ")}</span>
              </>
            )}
          </label>
          {fileError && (
            <p role="alert" className="text-xs font-medium text-destructive">
              {fileError}
            </p>
          )}

          <Field id="doc-title" label="Título (opcional)" error={errors.title?.message} hint="Por defecto, el nombre del archivo">
            <Input placeholder="Ej.: Manual de contingencia ATM" {...form.register("title")} />
          </Field>

          <div className="grid gap-4">
            <Field id="doc-type" label="Tipo" error={errors.sourceType?.message}>
              <Select {...form.register("sourceType")}>
                <option value="procedimiento">Procedimiento</option>
                <option value="manual">Manual</option>
                <option value="incidente">Incidente</option>
                <option value="faq">FAQ</option>
              </Select>
            </Field>
            <Field
              id="doc-area"
              label="Área"
              error={errors.area?.message}
              hint={isAdmin ? "Como administrador puedes elegir cualquier área" : "Solo puedes subir a tu área"}
            >
              <Input readOnly={!isAdmin} {...form.register("area")} />
            </Field>
          </div>

          <Button type="submit" className="w-full" loading={upload.isPending}>
            Subir e indexar
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
