import type { SourceCitation } from "@/types/api";

const CITATION = /\[Fuente:\s*([^\]]+)\]/g;

function normalize(text: string): string {
  return text.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/\s+/g, " ").trim();
}

/** Fuente citada por el texto "[Fuente: <título>, <sección>]" (coincidencia por título). */
export function findSource(citation: string, sources: SourceCitation[]): SourceCitation | undefined {
  const text = normalize(citation);
  return sources
    .filter((s) => text.includes(normalize(s.title)) || normalize(s.title).includes(text.split(",")[0] ?? ""))
    .sort((a, b) => b.title.length - a.title.length)[0];
}

/**
 * Convierte cada "[Fuente: …]" en un enlace Markdown "#fuente-<n>" para mostrarlo como
 * chip que lleva a la fuente correspondiente. Las citas sin fuente identificable se
 * mantienen como texto.
 */
export function linkCitations(answer: string, sources: SourceCitation[]): string {
  return answer.replace(CITATION, (match, inner: string) => {
    const source = findSource(inner, sources);
    return source ? `[${inner.trim()}](#fuente-${source.index})` : match;
  });
}
