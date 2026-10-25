import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/form-controls";
import { useAuth } from "@/hooks/useAuth";
import { useSaveIncident } from "@/hooks/useIncidents";
import type { Incident } from "@/types/domain";

export const incidentSchema = z.object({
  code: z
    .string()
    .trim()
    .min(3, "Obligatorio")
    .max(40)
    .regex(/^[A-Za-z0-9-]+$/, "Solo letras, números y guiones (p. ej. INC-2026-0042)"),
  system_affected: z.string().trim().min(2, "Obligatorio").max(120),
  symptom: z.string().trim().min(10, "Describe el síntoma (mín. 10 caracteres)").max(2000),
  diagnosis: z.string().max(4000).optional(),
  resolution: z.string().max(4000).optional(),
  severity: z.enum(["baja", "media", "alta", "critica"]),
  resolved: z.boolean(),
});
type IncidentFormValues = z.infer<typeof incidentSchema>;

function defaults(incident?: Incident): IncidentFormValues {
  return {
    code: incident?.code ?? "",
    system_affected: incident?.system_affected ?? "",
    symptom: incident?.symptom ?? "",
    diagnosis: incident?.diagnosis ?? "",
    resolution: incident?.resolution ?? "",
    severity: incident?.severity ?? "media",
    resolved: !!incident?.resolved_at,
  };
}

export function IncidentForm({ open, onOpenChange, incident }: { open: boolean; onOpenChange: (open: boolean) => void; incident?: Incident }) {
  const { me } = useAuth();
  const save = useSaveIncident();
  const form = useForm<IncidentFormValues>({ resolver: zodResolver(incidentSchema), defaultValues: defaults(incident) });
  const { errors } = form.formState;

  useEffect(() => {
    if (open) form.reset(defaults(incident));
  }, [open, incident, form]);

  const onSubmit = form.handleSubmit((values) =>
    save.mutate(
      {
        input: { ...values, diagnosis: values.diagnosis ?? null, resolution: values.resolution ?? null },
        existing: incident,
        userId: me?.user_id ?? "",
      },
      {
        onSuccess: () => {
          toast.success(incident ? "Incidente actualizado" : "Incidente registrado");
          onOpenChange(false);
        },
        onError: (error) => toast.error(error.message),
      },
    ),
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{incident ? `Editar ${incident.code}` : "Registrar incidente"}</DialogTitle>
          <DialogDescription>Los incidentes resueltos documentan diagnósticos y soluciones reutilizables.</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field id="inc-code" label="Código" error={errors.code?.message}>
              <Input placeholder="INC-2026-0042" {...form.register("code")} />
            </Field>
            <Field id="inc-system" label="Sistema afectado" error={errors.system_affected?.message}>
              <Input placeholder="Core bancario" {...form.register("system_affected")} />
            </Field>
            <Field id="inc-severity" label="Severidad" error={errors.severity?.message}>
              <Select {...form.register("severity")}>
                <option value="baja">Baja</option>
                <option value="media">Media</option>
                <option value="alta">Alta</option>
                <option value="critica">Crítica</option>
              </Select>
            </Field>
          </div>
          <Field id="inc-symptom" label="Síntoma" error={errors.symptom?.message}>
            <Textarea rows={3} {...form.register("symptom")} />
          </Field>
          <Field id="inc-diagnosis" label="Diagnóstico" error={errors.diagnosis?.message}>
            <Textarea rows={2} {...form.register("diagnosis")} />
          </Field>
          <Field id="inc-resolution" label="Resolución" error={errors.resolution?.message}>
            <Textarea rows={3} {...form.register("resolution")} />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="size-4 accent-[hsl(var(--primary))]" {...form.register("resolved")} />
            Incidente resuelto
          </label>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancelar
            </Button>
            <Button type="submit" loading={save.isPending}>
              {incident ? "Guardar cambios" : "Registrar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
