import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./supabase", () => ({
  supabase: { auth: { getSession: vi.fn(async () => ({ data: { session: { access_token: "jwt-usuario" } } })) } },
}));

import { ApiError, apiRequest } from "./api-client";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
}

describe("apiRequest", () => {
  it("envía el JWT, la traza y el cuerpo JSON", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ok: true }));
    const result = await apiRequest<{ ok: boolean }>("/api/v1/query", { body: { question: "hola" }, params: { a: 1, b: undefined } });

    expect(result).toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.toString()).toBe("http://gateway.test/api/v1/query?a=1");
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt-usuario");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["X-Trace-Id"]).toMatch(/^[0-9a-f]{32}$/);
    expect(init.body).toBe(JSON.stringify({ question: "hola" }));
  });

  it("con FormData deja que el navegador ponga el boundary", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(202, { document_id: "d" }));
    const form = new FormData();
    form.append("file", new Blob(["x"]), "x.md");
    await apiRequest("/api/v1/documents", { method: "POST", formData: form });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
    expect(init.body).toBe(form);
  });

  it("convierte el formato de error del gateway en ApiError", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(429, { error: { code: "rate_limited", message: "Demasiadas", trace_id: "t-1", details: { retry_after: 12 } } }),
    );
    const error = await apiRequest("/api/v1/query").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect([apiError.status, apiError.code, apiError.traceId]).toEqual([429, "rate_limited", "t-1"]);
    expect(apiError.userMessage).toContain("12 s");
  });

  it("errores sin JSON y de red", async () => {
    fetchMock.mockResolvedValueOnce(new Response("Bad gateway", { status: 502, headers: { "x-trace-id": "t-2" } }));
    const httpError = (await apiRequest("/x").catch((e: unknown) => e)) as ApiError;
    expect([httpError.status, httpError.code, httpError.traceId]).toEqual([502, "http_error", "t-2"]);

    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const networkError = (await apiRequest("/x").catch((e: unknown) => e)) as ApiError;
    expect(networkError.status).toBe(0);
    expect(networkError.userMessage).toMatch(/conectar/);
  });

  it("mensajes para el usuario según el estado", () => {
    expect(new ApiError("x", 401, "unauthenticated").userMessage).toMatch(/sesión expiró/);
    expect(new ApiError("x", 503, "service_unavailable").userMessage).toMatch(/no está disponible/);
    expect(new ApiError("Formato no soportado", 415, "unsupported").userMessage).toBe("Formato no soportado");
  });
});
