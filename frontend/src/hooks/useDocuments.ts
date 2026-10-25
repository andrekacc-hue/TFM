/**
 * Documentos de la base de conocimientos.
 *
 *  - Listado: lectura directa de tfm.documents con la sesión del usuario (RLS: su área +
 *    "general"; admin todo) y Supabase Realtime para ver el progreso de la ingesta en vivo.
 *  - Subida: api-gateway → ingest-service (validación, duplicados, cola).
 *  - Reindexación: Edge Function reindex-document (Fase 5).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { apiRequest } from "@/lib/api-client";
import { supabase } from "@/lib/supabase";
import type { SourceType, UploadAccepted } from "@/types/api";
import type { DocumentRow } from "@/types/domain";

const KEY = ["documents"] as const;
const COLUMNS = "id,title,source_type,area,status,error_message,chunk_count,version,storage_path,created_at,updated_at,metadata";

export function useDocuments() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: KEY,
    queryFn: async () => {
      const { data, error } = await supabase.from("documents").select(COLUMNS).order("updated_at", { ascending: false });
      if (error) throw new Error(error.message);
      return data as DocumentRow[];
    },
  });

  // Realtime: actualiza la fila en caché al cambiar su estado (pending → processing → indexed)
  useEffect(() => {
    const channel = supabase
      .channel("documents-status")
      .on("postgres_changes", { event: "*", schema: "tfm", table: "documents" }, (payload) => {
        queryClient.setQueryData<DocumentRow[]>(KEY, (current = []) => {
          if (payload.eventType === "DELETE") return current.filter((d) => d.id !== (payload.old as DocumentRow).id);
          const row = payload.new as DocumentRow;
          const exists = current.some((d) => d.id === row.id);
          const next = exists ? current.map((d) => (d.id === row.id ? { ...d, ...row } : d)) : [row, ...current];
          return next.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
        });
      })
      .subscribe();
    return () => {
      void supabase.removeChannel(channel);
    };
  }, [queryClient]);

  return query;
}

export interface UploadInput {
  file: File;
  title?: string;
  sourceType: SourceType;
  area: string;
}

export function useUploadDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: UploadInput) => {
      const form = new FormData();
      form.append("file", input.file);
      form.append("source_type", input.sourceType);
      form.append("area", input.area);
      if (input.title?.trim()) form.append("title", input.title.trim());
      return apiRequest<UploadAccepted>("/api/v1/documents", { method: "POST", formData: form });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

export function useReindexDocument() {
  return useMutation({
    mutationFn: async (documentId: string) => {
      const { data, error } = await supabase.functions.invoke<{ status: string; via: string }>("reindex-document", {
        body: { document_id: documentId },
      });
      if (error) {
        // FunctionsHttpError: el cuerpo trae {"error": {"message"}}
        const body = await (error as { context?: Response }).context?.json?.().catch(() => null);
        throw new Error(body?.error?.message ?? error.message);
      }
      return data;
    },
  });
}
