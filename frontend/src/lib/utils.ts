import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Combina clases de Tailwind resolviendo conflictos (convención shadcn/ui). */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

const numberFormat = new Intl.NumberFormat("es-EC");
const percentFormat = new Intl.NumberFormat("es-EC", { style: "percent", maximumFractionDigits: 1 });
const dateTimeFormat = new Intl.DateTimeFormat("es-EC", { dateStyle: "medium", timeStyle: "short" });
const relativeFormat = new Intl.RelativeTimeFormat("es", { numeric: "auto" });

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : numberFormat.format(value);
}

export function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : percentFormat.format(value);
}

/** 850 → "850 ms"; 2340 → "2,3 s". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toLocaleString("es-EC", { maximumFractionDigits: 1 })} s`;
}

export function formatDateTime(iso: string | null | undefined): string {
  return iso ? dateTimeFormat.format(new Date(iso)) : "—";
}

/** "hace 5 minutos", "ayer"… */
export function formatRelative(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const seconds = Math.round((new Date(iso).getTime() - now.getTime()) / 1000);
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
  ];
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return relativeFormat.format(Math.round(seconds / size), unit);
  }
  return relativeFormat.format(seconds, "second");
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${value.toLocaleString("es-EC", { maximumFractionDigits: 1 })} ${units[unit]}`;
}

/** Etiqueta de sección de una cita: "Paso 2 (pág. 3)" o "fragmento 4". */
export function sectionLabel(section: string | null, chunkIndex: number, page: number | null): string {
  const label = section?.trim() || `fragmento ${chunkIndex + 1}`;
  return page ? `${label} (pág. ${page})` : label;
}

/** "1 usuario" / "3 usuarios" (con formato numérico local). */
export function plural(count: number | null | undefined, singular: string, pluralForm = `${singular}s`): string {
  return `${formatNumber(count ?? 0)} ${count === 1 ? singular : pluralForm}`;
}

export const SOURCE_TYPE_LABELS: Record<string, string> = {
  manual: "Manual",
  procedimiento: "Procedimiento",
  incidente: "Incidente",
  faq: "FAQ",
};

export const AREA_PATTERN = /^[a-z0-9_-]+$/;
