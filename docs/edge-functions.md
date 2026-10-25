# Edge Functions de Supabase — Guía de despliegue

Dos funciones Deno/TypeScript conectan Supabase Storage con el pipeline de ingesta:

| Función | Quién la invoca | Autenticación | Qué hace |
|---------|-----------------|---------------|----------|
| `on-document-upload` | Trigger SQL en `storage.objects` (vía `pg_net`) | Cabecera `x-webhook-secret` | Registra en `tfm.documents` (estado `pending`) el archivo que un usuario subió al bucket `documents` |
| `reindex-document` | Portal web: `supabase.functions.invoke("reindex-document", { body: { document_id } })` | Access token del usuario (`auth.getUser`) | Devuelve un documento a `pending` para reprocesarlo |

## Arquitectura: patrón outbox

Las Edge Functions se ejecutan en la nube de Supabase y **no alcanzan** Redis ni el `ingest-service`
(red privada o `localhost`). La base de datos hace de buzón:

```
Portal ──(supabase-js, JWT)──► Storage: documents/{area}/{document_id}/{archivo}
          │  RLS: solo editores de su área / admin
          └─► trigger tfm_on_document_object_created (AFTER INSERT, solo si owner_id no es nulo)
                └─ net.http_post (asíncrono, no bloquea la subida)
                     └─► on-document-upload ──► tfm.documents  status=pending, enqueued_at=NULL

ingest-service ── outbox poller (cada 15 s)
     └─ tfm.claim_pending_documents()  (UPDATE … FOR UPDATE SKIP LOCKED)
          └─► XADD documents.ingest ──► worker ──► indexed ──► Realtime avisa al portal
```

- **Sin acoplamiento de red:** la función no necesita conocer la URL del worker.
- **Escalable:** `SKIP LOCKED` permite varias réplicas del ingest-service sin reclamar dos veces el mismo documento.
- **Auto-reparación:** un documento encolado que siga en `pending` más de `OUTBOX_STALE_SECONDS` (300 s) se
  reencola (p. ej. si Redis se reinició y perdió mensajes).
- **Subidas por la API del gateway** (`POST /api/v1/documents`): las hace el ingest-service con service_role
  (`owner_id` nulo), así que el trigger las ignora; el servicio las registra y encola él mismo.
- **Latencia opcional mínima:** si se define `INGEST_PUBLIC_URL` (ingest-service accesible desde internet, p. ej.
  con ngrok o en producción), la función lo avisa al instante; si el aviso falla, el outbox lo recoge igual.

## Requisitos

| Herramienta | Comprobación |
|-------------|--------------|
| Node.js 20+ (para `npx supabase`) | `node --version` |
| Deno 2 (solo para tests locales) | `deno --version` |
| Sesión en la Supabase CLI | `npx supabase login` (una vez; abre el navegador) |
| Migración 10 aplicada | `python scripts/apply_migrations.py` |
| `.env` con claves nuevas | `SUPABASE_SERVICE_ROLE_KEY=sb_secret_…` |

## Despliegue (un solo comando)

```powershell
cd C:\Frontend\TFM\soporte-bancario-rag
.\.venv\Scripts\python.exe scripts\configure_edge_functions.py
```

El script:

1. Genera `TFM_WEBHOOK_SECRET` (32 bytes aleatorios) y lo guarda en `.env` (se reutiliza en ejecuciones posteriores).
2. Guarda en **Supabase Vault** `tfm_edge_functions_url` y `tfm_webhook_secret`, que lee el trigger SQL. Nunca
   se versionan.
3. Define los secretos de las funciones con `supabase secrets set` desde un archivo temporal que se borra al terminar:
   `TFM_SECRET_KEY` y `TFM_WEBHOOK_SECRET` (y, si existen, `TFM_INGEST_API_URL` / `TFM_INTERNAL_API_KEY`).
4. Despliega ambas funciones con `--no-verify-jwt --use-api` (sin Docker).

> **¿Por qué `verify_jwt = false`?** Con las claves de API nuevas (`sb_publishable_`/`sb_secret_`) la
> plataforma no puede verificar el JWT por sí sola. Cada función hace su propia verificación: el webhook,
> un secreto compartido comparado en tiempo constante; `reindex-document`, el token del usuario con
> `auth.getUser()` y su rol y área en `tfm.profiles`.

Redesplegar solo el código: `npx supabase functions deploy on-document-upload reindex-document --project-ref <ref> --no-verify-jwt --use-api`.

## Pruebas

```powershell
# Unitarias (Deno, con dobles; no despliegan nada)
cd supabase\functions; deno task test        # 16 tests
deno task check                              # chequeo de tipos

# Extremo a extremo (stack levantado + funciones desplegadas)
cd ..\..; .\.venv\Scripts\python.exe -m pytest tests\integration\test_edge_functions.py -v
```

El test extremo a extremo crea un editor temporal, sube un Markdown **directamente a Storage** con su JWT y
verifica:

1. el trigger avisa a la función y el documento queda registrado (`origin = storage-trigger`);
2. el outbox lo encola y el worker lo indexa;
3. el RAG lo usa como fuente a través del gateway;
4. `reindex-document` rechaza a un viewer y a un editor de otra área, y reprocesa el documento para el editor del área;
5. las políticas de Storage impiden subir a otra área.

## Diagnóstico

| Síntoma | Comprobación |
|---------|--------------|
| El documento no aparece tras subirlo a Storage | `select status_code, content from net._http_response order by created desc limit 5;` (respuestas del trigger) |
| `401 invalid_webhook_secret` | El secreto de Vault y el de la función difieren: vuelve a ejecutar `configure_edge_functions.py` |
| Aviso `Edge Functions sin configurar (Vault)` en los logs de Postgres | Faltan los secretos de Vault: ejecuta el script |
| Documento queda en `pending` | `GET http://localhost:8002/ready` → `"outbox": "ok"`; logs: `docker compose logs ingest-service` |
| Logs de las funciones | Dashboard → Edge Functions → *on-document-upload* → Logs (eventos JSON `document_registered`, `reindex_requested`) |
