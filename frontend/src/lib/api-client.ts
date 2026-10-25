/**
 * Cliente del api-gateway.
 *
 * Añade el access token de la sesión de Supabase, propaga X-Trace-Id y convierte las
 * respuestas de error ({"error": {code, message, trace_id}}) en {@link ApiError}.
 */
import { env } from "./env";
import { supabase } from "./supabase";
import type { ApiErrorBody } from "@/types/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly traceId: string | null = null,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Mensaje para mostrar al usuario según el tipo de error. */
  get userMessage(): string {
    if (this.status === 0) return "No se pudo conectar con el servidor. Revisa tu conexión.";
    if (this.status === 401) return "Tu sesión expiró. Vuelve a iniciar sesión.";
    if (this.status === 429) {
      const wait = this.details.retry_after;
      return `Has hecho demasiadas solicitudes. Intenta de nuevo${wait ? ` en ${wait} s` : " en unos segundos"}.`;
    }
    if (this.status === 503 || this.status === 504) return "El servicio no está disponible en este momento. Intenta en unos minutos.";
    return this.message;
  }
}

export interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  formData?: FormData;
  params?: Record<string, string | number | undefined | null>;
  signal?: AbortSignal;
  /** Devuelve el Response sin parsear (descargas). */
  raw?: boolean;
}

async function accessToken(): Promise<string | null> {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

export function newTraceId(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = new URL(`${env.gatewayUrl}${path}`);
  for (const [key, value] of Object.entries(options.params ?? {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
  }

  const headers: Record<string, string> = { "X-Trace-Id": newTraceId() };
  const token = await accessToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let body: BodyInit | undefined;
  if (options.formData) {
    body = options.formData; // el navegador pone el boundary multipart
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  let response: Response;
  try {
    response = await fetch(url, { method: options.method ?? (body ? "POST" : "GET"), headers, body, signal: options.signal });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError("Error de red", 0, "network_error");
  }

  if (!response.ok) {
    let parsed: Partial<ApiErrorBody> = {};
    try {
      parsed = (await response.json()) as ApiErrorBody;
    } catch {
      /* cuerpo no JSON */
    }
    const err = parsed.error;
    throw new ApiError(
      err?.message ?? `Error ${response.status}`,
      response.status,
      err?.code ?? "http_error",
      err?.trace_id ?? response.headers.get("x-trace-id"),
      err?.details ?? {},
    );
  }

  if (options.raw) return response as unknown as T;
  return (await response.json()) as T;
}

/** Descarga un archivo del gateway (p. ej. exportación CSV) respetando el nombre sugerido. */
export async function downloadFile(path: string, params: RequestOptions["params"], fallbackName: string): Promise<void> {
  const response = await apiRequest<Response>(path, { params, raw: true });
  const disposition = response.headers.get("content-disposition") ?? "";
  const name = /filename="?([^"]+)"?/.exec(disposition)?.[1] ?? fallbackName;
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  link.click();
  URL.revokeObjectURL(link.href);
}
