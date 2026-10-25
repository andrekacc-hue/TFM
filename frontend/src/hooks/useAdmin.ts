/** Administración: perfiles (rol/área) y golden dataset, directamente con RLS. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";
import type { Role } from "@/types/auth";
import type { Difficulty, GoldenQuestion, Profile } from "@/types/domain";

export function useProfiles(enabled: boolean) {
  return useQuery({
    queryKey: ["profiles"],
    queryFn: async () => {
      const { data, error } = await supabase.from("profiles").select("id,email,full_name,role,area,created_at").order("created_at");
      if (error) throw new Error(error.message);
      return data as Profile[];
    },
    enabled,
  });
}

/** Solo un admin puede cambiar rol/área (lo garantiza el trigger protect_profile_privileges). */
export function useUpdateProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, role, area }: { id: string; role: Role; area: string }) => {
      const { error } = await supabase.from("profiles").update({ role, area }).eq("id", id);
      if (error) throw new Error(error.message);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["profiles"] }),
  });
}

export function useGoldenDataset() {
  return useQuery({
    queryKey: ["golden-dataset"],
    queryFn: async () => {
      const { data, error } = await supabase.from("golden_dataset").select("*").order("code", { nullsFirst: false }).order("created_at");
      if (error) throw new Error(error.message);
      return data as GoldenQuestion[];
    },
  });
}

export function useAddGoldenQuestion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { question: string; expected_answer: string; difficulty: Difficulty; tags: string[] }) => {
      const { error } = await supabase.from("golden_dataset").insert(input);
      if (error) throw new Error(error.message.includes("row-level security") ? "Solo un administrador puede editar el golden dataset" : error.message);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["golden-dataset"] }),
  });
}

export function useDeleteGoldenQuestion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const { error } = await supabase.from("golden_dataset").delete().eq("id", id);
      if (error) throw new Error(error.message);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["golden-dataset"] }),
  });
}
