import { assertEquals, assertMatch } from "@std/assert";
import { handleUpload } from "../on-document-upload/handler.ts";
import { ADMIN, DOC_ID, EDITOR_OPS, FakeDeps, VIEWER_OPS, webhook } from "./helpers.ts";

const record = (overrides: Record<string, unknown> = {}) => ({
  id: "obj-1",
  bucket_id: "documents",
  name: `operaciones/${DOC_ID}/PROC-OPS-014_reinicio_batch.pdf`,
  owner_id: EDITOR_OPS.id,
  metadata: { mimetype: "application/pdf", size: 1234 },
  user_metadata: { source_type: "procedimiento" },
  ...overrides,
});

Deno.test("registra el documento en pending y lo deja al outbox", async () => {
  const deps = new FakeDeps();
  const response = await handleUpload(webhook(record()), deps);
  assertEquals(response.status, 202);
  assertEquals(await response.json(), { document_id: DOC_ID, status: "pending", via: "outbox" });

  const doc = deps.upserted[0];
  assertEquals(doc.id, DOC_ID);
  assertEquals(doc.title, "PROC-OPS-014 reinicio batch");
  assertEquals(doc.source_type, "procedimiento");
  assertEquals(doc.area, "operaciones");
  assertEquals(doc.status, "pending");
  assertEquals(doc.enqueued_at, null);
  assertEquals(doc.uploaded_by, EDITOR_OPS.id);
  assertEquals(doc.metadata.origin, "storage-trigger");
  assertEquals(doc.metadata.size_bytes, 1234);
});

Deno.test("usa el título de user_metadata y normaliza source_type desconocido", async () => {
  const deps = new FakeDeps();
  await handleUpload(webhook(record({ user_metadata: { title: "  Manual ATM  ", source_type: "otro" } })), deps);
  assertEquals(deps.upserted[0].title, "Manual ATM");
  assertEquals(deps.upserted[0].source_type, "manual");
});

Deno.test("genera un id si la ruta no trae UUID", async () => {
  const deps = new FakeDeps();
  const response = await handleUpload(webhook(record({ name: "operaciones/manual.md" })), deps);
  const body = await response.json();
  assertMatch(body.document_id, /^[0-9a-f-]{36}$/);
  assertEquals(deps.upserted[0].storage_path, "operaciones/manual.md");
});

Deno.test("avisa al ingest-service cuando está configurado", async () => {
  const deps = new FakeDeps();
  deps.notifyResult = true;
  const body = await (await handleUpload(webhook(record()), deps)).json();
  assertEquals(body.via, "ingest-api");
  assertEquals(deps.notified, [DOC_ID]);
});

Deno.test("si el aviso falla, queda para el outbox", async () => {
  const deps = new FakeDeps();
  deps.notifyResult = false;
  assertEquals((await (await handleUpload(webhook(record()), deps)).json()).via, "outbox");
});

Deno.test("formato no soportado: se registra como failed y no se encola", async () => {
  const deps = new FakeDeps();
  deps.notifyResult = true;
  const response = await handleUpload(webhook(record({ name: `operaciones/${DOC_ID}/foto.png` })), deps);
  assertEquals((await response.json()).status, "failed");
  assertMatch(deps.upserted[0].error_message ?? "", /no soportado/);
  assertEquals(deps.notified, []);
});

Deno.test("rechaza secreto inválido o ausente", async () => {
  const deps = new FakeDeps();
  assertEquals((await handleUpload(webhook(record(), "otro"), deps)).status, 401);
  assertEquals((await handleUpload(webhook(record(), ""), deps)).status, 401);
  assertEquals(deps.upserted.length, 0);
});

Deno.test("ignora otros buckets y subidas de servicio (owner nulo)", async () => {
  const deps = new FakeDeps();
  assertEquals((await (await handleUpload(webhook(record({ bucket_id: "avatars" })), deps)).json()).ignored, true);
  assertEquals((await (await handleUpload(webhook(record({ owner_id: null })), deps)).json()).reason, "subida_de_servicio");
  assertEquals(deps.upserted.length, 0);
});

Deno.test("defensa en profundidad: viewer o editor de otra área → 403", async () => {
  const deps = new FakeDeps();
  assertEquals((await handleUpload(webhook(record({ owner_id: VIEWER_OPS.id })), deps)).status, 403);
  const otherArea = record({ name: `creditos/${DOC_ID}/m.pdf` });
  assertEquals((await handleUpload(webhook(otherArea), deps)).status, 403);
  assertEquals((await handleUpload(webhook({ ...otherArea, owner_id: ADMIN.id }), deps)).status, 202);
});

Deno.test("ruta inválida y método incorrecto", async () => {
  const deps = new FakeDeps();
  assertEquals((await handleUpload(webhook(record({ name: "Área Mala/x.pdf" })), deps)).status, 422);
  assertEquals((await handleUpload(new Request("http://x", { method: "GET" }), deps)).status, 405);
  const bad = new Request("http://x", { method: "POST", headers: { "x-webhook-secret": "secreto-webhook-de-pruebas" }, body: "{" });
  assertEquals((await handleUpload(bad, deps)).status, 400);
});
