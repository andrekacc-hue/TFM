/** CRUD de incidentes directamente sobre tfm.incidents (RLS: todos leen, editor crea/edita, admin borra). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";
import type { Incident, IncidentInput } from "@/types/domain";

const KEY = ["incidents"] as const;

function toRow(input: IncidentInput, previousResolvedAt?: string | null) {
  return {
    code: input.code.trim().toUpperCase(),
    system_affected: input.system_affected.trim(),
    symptom: input.symptom.trim(),
    diagnosis: input.diagnosis?.trim() || null,
    resolution: input.resolution?.trim() || null,
    severity: input.severity,
    resolved_at: input.resolved ? (previousResolvedAt ?? new Date().toISOString()) : null,
  };
}

function friendly(message: string): string {
  if (message.includes("incidents_code_key") || message.includes("duplicate key")) return "Ya existe un incidente con ese código";
  if (message.includes("row-level security")) return "No tienes permiso para esta operación";
  return message;
}

export function useIncidents() {
  return useQuery({
    queryKey: KEY,
    queryFn: async () => {
      const { data, error } = await supabase.from("incidents").select("*").order("created_at", { ascending: false });
      if (error) throw new Error(error.message);
      return data as Incident[];
    },
  });
}

export function useSaveIncident() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ input, existing, userId }: { input: IncidentInput; existing?: Incident; userId: string }) => {
      const result = existing
        ? await supabase.from("incidents").update(toRow(input, existing.resolved_at)).eq("id", existing.id)
        : await supabase.from("incidents").insert({ ...toRow(input), created_by: userId });
      if (result.error) throw new Error(friendly(result.error.message));
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteIncident() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const { error, count } = await supabase.from("incidents").delete({ count: "exact" }).eq("id", id);
      if (error) throw new Error(friendly(error.message));
      if (count === 0) throw new Error("No tienes permiso para eliminar este incidente");
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  });
}
