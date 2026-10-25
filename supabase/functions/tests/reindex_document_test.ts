import { assertEquals } from "@std/assert";
import { handleReindex } from "../reindex-document/handler.ts";
import { DOC_ID, FakeDeps, reindexRequest } from "./helpers.ts";

function withDocument(area = "operaciones", status: "pending" | "processing" | "indexed" | "failed" = "failed") {
  const deps = new FakeDeps();
  deps.documents.set(DOC_ID, { id: DOC_ID, title: "Manual", area, status, storage_path: `${area}/${DOC_ID}/m.pdf` });
  return deps;
}

Deno.test("editor de su área reindexa → pending vía outbox", async () => {
  const deps = withDocument();
  const response = await handleReindex(reindexRequest({ document_id: DOC_ID }, "token-editor"), deps);
  assertEquals(response.status, 202);
  assertEquals(await response.json(), { document_id: DOC_ID, status: "pending", via: "outbox" });
  assertEquals(deps.pending, [DOC_ID]);
});

Deno.test("aviso inmediato al ingest-service si está configurado", async () => {
  const deps = withDocument();
  deps.notifyResult = true;
  const body = await (await handleReindex(reindexRequest({ document_id: DOC_ID }, "token-editor"), deps)).json();
  assertEquals(body.via, "ingest-api");
});

Deno.test("requiere sesión válida", async () => {
  const deps = withDocument();
  assertEquals((await handleReindex(reindexRequest({ document_id: DOC_ID }), deps)).status, 401);
  assertEquals((await handleReindex(reindexRequest({ document_id: DOC_ID }, "token-falso"), deps)).status, 401);
});

Deno.test("permisos: viewer y editor de otra área → 403; admin → 202", async () => {
  const deps = withDocument("creditos");
  assertEquals((await handleReindex(reindexRequest({ document_id: DOC_ID }, "token-viewer"), deps)).status, 403);
  assertEquals((await handleReindex(reindexRequest({ document_id: DOC_ID }, "token-editor"), deps)).status, 403);
  assertEquals((await handleReindex(reindexRequest({ document_id: DOC_ID }, "token-admin"), deps)).status, 202);
});

Deno.test("documento inexistente, en proceso o id inválido", async () => {
  assertEquals((await handleReindex(reindexRequest({ document_id: DOC_ID }, "token-admin"), new FakeDeps())).status, 404);
  const busy = withDocument("operaciones", "processing");
  assertEquals((await handleReindex(reindexRequest({ document_id: DOC_ID }, "token-admin"), busy)).status, 409);
  assertEquals((await handleReindex(reindexRequest({ document_id: "123" }, "token-admin"), busy)).status, 422);
});

Deno.test("CORS preflight y método incorrecto", async () => {
  const deps = withDocument();
  const preflight = await handleReindex(reindexRequest(null, undefined, "OPTIONS"), deps);
  assertEquals(preflight.status, 200);
  assertEquals(preflight.headers.get("access-control-allow-origin"), "*");
  assertEquals((await handleReindex(reindexRequest(null, "token-admin", "GET"), deps)).status, 405);
});
