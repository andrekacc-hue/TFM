/** Reglas de dominio para documentos: rutas de Storage, formatos y permisos. */

import type { Profile, SourceType } from "./types.ts";

export const SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".md", ".markdown", ".txt"];
export const SOURCE_TYPES: SourceType[] = ["manual", "procedimiento", "incidente", "faq"];
const AREA = /^[a-z0-9_-]+$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface ParsedPath {
  area: string;
  documentId: string;
  filename: string;
  extension: string;
}

/**
 * Interpreta la ruta de Storage. Convención del proyecto: ``{area}/{document_id}/{archivo}``.
 * Si el segundo segmento no es un UUID (p. ej. ``operaciones/manual.pdf``) se genera un id.
 */
export function parseStoragePath(name: string, newId: () => string = () => crypto.randomUUID()): ParsedPath | null {
  const segments = name.split("/").filter(Boolean);
  if (segments.length < 2 || !AREA.test(segments[0])) return null;
  const filename = segments[segments.length - 1];
  const dot = filename.lastIndexOf(".");
  const extension = dot >= 0 ? filename.slice(dot).toLowerCase() : "";
  const documentId = segments.length >= 3 && UUID.test(segments[1]) ? segments[1].toLowerCase() : newId();
  return { area: segments[0], documentId, filename, extension };
}

/** "PROC-OPS-014_reinicio_batch.pdf" → "PROC-OPS-014 reinicio batch". */
export function titleFromFilename(filename: string): string {
  const dot = filename.lastIndexOf(".");
  const stem = dot > 0 ? filename.slice(0, dot) : filename;
  return stem.replace(/[_]+/g, " ").replace(/\s+/g, " ").trim() || "Documento";
}

export function normalizeSourceType(value: unknown): SourceType {
  return SOURCE_TYPES.includes(value as SourceType) ? (value as SourceType) : "manual";
}

/** Editores solo en su área; administradores en cualquiera. */
export function canManageArea(profile: Profile | null, area: string): boolean {
  if (!profile) return false;
  if (profile.role === "admin") return true;
  return profile.role === "editor" && profile.area === area;
}
