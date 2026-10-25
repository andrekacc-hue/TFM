-- =====================================================================
-- 20260101000010_storage_outbox.sql
-- Ingesta disparada por Storage + outbox transaccional.
--
--   portal ──(supabase-js, JWT de usuario)──► storage.objects
--        └─ trigger tfm_on_document_object_created ──pg_net──► Edge Function
--                                       on-document-upload ──► tfm.documents (pending)
--   ingest-service (outbox poller) ── tfm.claim_pending_documents() ──► Redis Stream
--
-- Las Edge Functions corren en la nube de Supabase y no alcanzan Redis ni el
-- ingest-service; la base de datos actúa de buzón (patrón outbox). Además, los
-- documentos que se queden en "pending" (p. ej. si Redis perdió mensajes) se
-- vuelven a encolar automáticamente.
--
-- Secretos en Vault (los crea scripts/configure_edge_functions.py, nunca en git):
--   tfm_edge_functions_url   https://<ref>.supabase.co/functions/v1
--   tfm_webhook_secret       secreto compartido trigger → Edge Function
-- =====================================================================
set search_path = public, extensions;

create extension if not exists pg_net with schema extensions;

-- ---------------------------------------------------------------------
-- Outbox: cuándo se publicó cada documento en el stream
-- ---------------------------------------------------------------------
alter table tfm.documents add column if not exists enqueued_at timestamptz;
create index if not exists idx_documents_outbox on tfm.documents (created_at) where status = 'pending';

comment on column tfm.documents.enqueued_at is
  'Último envío a la cola de ingesta. NULL = pendiente de encolar (outbox).';

create or replace function tfm.claim_pending_documents(
  p_limit int default 10,
  p_stale_seconds int default 300
)
returns setof uuid
language sql
volatile
set search_path = tfm, public
as $$
  -- FOR UPDATE SKIP LOCKED: varias réplicas del ingest-service pueden sondear a la
  -- vez sin reclamar el mismo documento.
  update tfm.documents d
     set enqueued_at = now()
   where d.id in (
     select id from tfm.documents
      where status = 'pending'
        and (enqueued_at is null or enqueued_at < now() - make_interval(secs => p_stale_seconds))
      order by created_at
      for update skip locked
      limit least(greatest(p_limit, 1), 100)
   )
  returning d.id;
$$;

comment on function tfm.claim_pending_documents(int, int) is
  'Reclama documentos pending sin encolar (o encolados hace más de p_stale_seconds) para publicarlos en Redis.';

revoke execute on function tfm.claim_pending_documents(int, int) from public, anon, authenticated;
grant execute on function tfm.claim_pending_documents(int, int) to service_role;

-- ---------------------------------------------------------------------
-- Trigger de Storage → Edge Function on-document-upload
-- Solo para subidas hechas por un USUARIO (owner_id no nulo) en el bucket
-- "documents": las del ingest-service usan service_role (owner nulo) y ya
-- registran el documento ellas mismas.
-- ---------------------------------------------------------------------
create or replace function tfm.on_storage_object_created()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_url text;
  v_secret text;
begin
  if new.bucket_id <> 'documents' or coalesce(new.owner_id, new.owner::text) is null then
    return new;
  end if;

  select decrypted_secret into v_url from vault.decrypted_secrets where name = 'tfm_edge_functions_url';
  select decrypted_secret into v_secret from vault.decrypted_secrets where name = 'tfm_webhook_secret';
  if v_url is null or v_secret is null then
    raise warning 'tfm: Edge Functions sin configurar (Vault); se omite la ingesta de %', new.name;
    return new;
  end if;

  -- Llamada asíncrona (pg_net): no bloquea ni puede revertir la subida
  perform net.http_post(
    url := v_url || '/on-document-upload',
    body := jsonb_build_object(
      'type', 'INSERT',
      'record', jsonb_build_object(
        'id', new.id,
        'bucket_id', new.bucket_id,
        'name', new.name,
        'owner_id', coalesce(new.owner_id, new.owner::text),
        'metadata', new.metadata,
        'user_metadata', new.user_metadata,
        'created_at', new.created_at
      )
    ),
    headers := jsonb_build_object('Content-Type', 'application/json', 'x-webhook-secret', v_secret),
    timeout_milliseconds := 5000
  );
  return new;
exception when others then
  -- Un fallo del aviso nunca debe impedir que el archivo se guarde;
  -- el documento puede registrarse después con reindex.
  raise warning 'tfm: no se pudo notificar la subida de %: %', new.name, sqlerrm;
  return new;
end;
$$;

comment on function tfm.on_storage_object_created() is
  'AFTER INSERT en storage.objects: avisa a la Edge Function on-document-upload (pg_net) de subidas de usuarios.';

drop trigger if exists tfm_on_document_object_created on storage.objects;
create trigger tfm_on_document_object_created
  after insert on storage.objects
  for each row execute function tfm.on_storage_object_created();
