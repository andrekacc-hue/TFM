/** Ejecuciones de la evaluación con RAGAs (tfm.evaluation_runs; RLS: editor y admin). */
import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";
import type { EvaluationQuestionResult, EvaluationRun } from "@/types/domain";

const RUN_COLUMNS = "id,created_at,label,llm_model,judge_model,questions,metrics,config,duration_s";

/** Últimas ejecuciones (sin el detalle por pregunta, que es lo pesado). */
export function useEvaluationRuns(limit = 10) {
  return useQuery({
    queryKey: ["evaluation-runs", limit],
    queryFn: async () => {
      const { data, error } = await supabase
        .from("evaluation_runs")
        .select(RUN_COLUMNS)
        .order("created_at", { ascending: false })
        .limit(limit);
      if (error) throw new Error(error.message);
      return data as EvaluationRun[];
    },
  });
}

/** Detalle por pregunta de una ejecución. */
export function useEvaluationResults(runId: string | undefined) {
  return useQuery({
    queryKey: ["evaluation-results", runId],
    queryFn: async () => {
      const { data, error } = await supabase.from("evaluation_runs").select("results").eq("id", runId!).single();
      if (error) throw new Error(error.message);
      return (data as { results: EvaluationQuestionResult[] }).results;
    },
    enabled: Boolean(runId),
  });
}
