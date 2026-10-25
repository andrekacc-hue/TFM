import type { Deps, DocumentRow, NewDocument, Profile } from "../_shared/types.ts";

export const SECRET = "secreto-webhook-de-pruebas";
export const EDITOR_OPS: Profile = { id: "11111111-1111-4111-8111-111111111111", role: "editor", area: "operaciones" };
export const VIEWER_OPS: Profile = { id: "22222222-2222-4222-8222-222222222222", role: "viewer", area: "operaciones" };
export const ADMIN: Profile = { id: "33333333-3333-4333-8333-333333333333", role: "admin", area: "general" };
export const DOC_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

export class FakeDeps implements Deps {
  webhookSecret = SECRET;
  profiles = new Map<string, Profile>([EDITOR_OPS, VIEWER_OPS, ADMIN].map((p) => [p.id, p]));
  documents = new Map<string, DocumentRow>();
  upserted: NewDocument[] = [];
  pending: string[] = [];
  notified: string[] = [];
  tokens = new Map<string, string>([["token-editor", EDITOR_OPS.id], ["token-viewer", VIEWER_OPS.id], ["token-admin", ADMIN.id]]);
  notifyResult: boolean | null = null; // null = sin aviso al ingest-service configurado
  logs: string[] = [];

  repo = {
    getProfile: (id: string) => Promise.resolve(this.profiles.get(id) ?? null),
    getDocument: (id: string) => Promise.resolve(this.documents.get(id) ?? null),
    upsertDocument: (doc: NewDocument) => {
      this.upserted.push(doc);
      return Promise.resolve();
    },
    markPending: (id: string) => {
      this.pending.push(id);
      return Promise.resolve();
    },
  };

  getUserId = (token: string) => Promise.resolve(this.tokens.get(token) ?? null);

  get notifyIngest() {
    if (this.notifyResult === null) return undefined;
    return (id: string) => {
      this.notified.push(id);
      return Promise.resolve(this.notifyResult as boolean);
    };
  }

  log = (event: string) => {
    this.logs.push(event);
  };
}

export function webhook(record: Record<string, unknown>, secret = SECRET): Request {
  return new Request("http://localhost/on-document-upload", {
    method: "POST",
    headers: { "content-type": "application/json", "x-webhook-secret": secret },
    body: JSON.stringify({ type: "INSERT", record }),
  });
}

export function reindexRequest(body: unknown, token?: string, method = "POST"): Request {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (token) headers.authorization = `Bearer ${token}`;
  return new Request("http://localhost/reindex-document", {
    method,
    headers,
    body: method === "POST" ? JSON.stringify(body) : undefined,
  });
}
