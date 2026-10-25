-- =====================================================================
-- tfm_schema.sql — GENERADO por scripts/build_deploy_sql.py
-- Instalación desde cero: pegar completo en Supabase -> SQL Editor -> Run.
-- No editar a mano.
-- =====================================================================
begin;

-- >>> 20260101000001_init.sql
-- =====================================================================
-- 20260101000001_init.sql
-- Extensiones base. Compatible con Supabase Cloud y self-hosted.
-- =====================================================================
set search_path = public, extensions;

-- Funciones criptográficas y búsqueda difusa (trigramas)
create extension if not exists pgcrypto with schema extensions;
create extension if not exists pg_trgm with schema extensions;

-- >>> 20260101000002_pgvector.sql
-- =====================================================================
-- 20260101000002_pgvector.sql
-- pgvector: tipo vector + índices HNSW para búsqueda semántica.
-- Se instala en el esquema "extensions" (convención de Supabase); los
-- objetos que lo usan declaran search_path con "extensions".
-- =====================================================================
set search_path = public, extensions;

create extension if not exists vector with schema extensions;

comment on extension vector is
  'Embeddings de 384 dimensiones (paraphrase-multilingual-MiniLM-L12-v2) con distancia coseno.';

-- >>> 20260101000003_schemas.sql
-- =====================================================================
-- 20260101000003_schemas.sql
-- Esquema único de la aplicación: tfm
--
-- Modelo de privilegios:
--   anon          -> sin acceso
--   authenticated -> privilegios DML, filtrados por RLS (migración 06)
--   service_role  -> microservicios; BYPASSRLS
--
-- IMPORTANTE (Supabase Cloud): añadir "tfm" en
--   Project Settings -> Data API -> Exposed schemas
-- para que supabase-js / supabase-py puedan usar .schema('tfm').
-- =====================================================================
set search_path = public, extensions;

create schema if not exists tfm;

comment on schema tfm is
  'TFM Soporte TI Produbanco: base de conocimientos RAG, consultas, feedback, evaluación y auditoría.';

grant usage on schema tfm to authenticated, service_role;
revoke all on schema tfm from anon;

alter default privileges in schema tfm
  grant select, insert, update, delete on tables to authenticated;
alter default privileges in schema tfm
  grant all on tables to service_role;
alter default privileges in schema tfm
  grant usage, select on sequences to authenticated, service_role;
alter default privileges in schema tfm
  revoke execute on functions from public;
alter default privileges in schema tfm
  grant execute on functions to authenticated, service_role;

-- ---------------------------------------------------------------------
-- Trigger genérico: mantiene la columna updated_at
-- ---------------------------------------------------------------------
create or replace function tfm.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

comment on function tfm.set_updated_at() is
  'Trigger BEFORE UPDATE que actualiza updated_at con la marca de tiempo actual.';

-- >>> 20260101000004_tables.sql
-- =====================================================================
-- 20260101000004_tables.sql
-- Tablas del dominio, todas en el esquema tfm.
--
--   tfm.profiles        rol (viewer/editor/admin) y área de cada usuario
--   tfm.documents       documentos fuente
--   tfm.chunks          fragmentos con embedding vector(384)
--   tfm.incidents       histórico de incidentes
--   tfm.queries         consultas al asistente
--   tfm.feedback        valoración de respuestas
--   tfm.golden_dataset  preguntas de evaluación (RAGAs)
--   tfm.audit_events    auditoría
--
-- Notas de diseño:
--   * FKs a auth.users con ON DELETE SET NULL/CASCADE: borrar un usuario
--     no queda bloqueado por su historial.
--   * UNIQUE (document_id, chunk_index): reindexación idempotente.
--   * UNIQUE (query_id, user_id) en feedback: un voto por usuario.
--   * Áreas como slug en minúsculas (se usan como carpeta en Storage).
-- =====================================================================
set search_path = public, extensions;

-- ---------------------------------------------------------------------
-- tfm.profiles
-- ---------------------------------------------------------------------
create table tfm.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  full_name text,
  area text not null default 'general' check (area ~ '^[a-z0-9_-]+$'),
  role text not null default 'viewer' check (role in ('viewer','editor','admin')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index idx_profiles_area on tfm.profiles(area);
create index idx_profiles_email on tfm.profiles(email);

comment on table tfm.profiles is
  'Perfil de aplicación: rol (viewer/editor/admin) y área funcional. Lo crea el trigger tfm_on_auth_user_created.';

create trigger trg_profiles_updated_at
  before update on tfm.profiles
  for each row execute function tfm.set_updated_at();

-- ---------------------------------------------------------------------
-- tfm.documents
-- ---------------------------------------------------------------------
create table tfm.documents (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  source_type text not null check (source_type in ('manual','procedimiento','incidente','faq')),
  storage_path text not null,
  area text not null check (area ~ '^[a-z0-9_-]+$'),
  version int not null default 1,
  status text not null default 'pending' check (status in ('pending','processing','indexed','failed')),
  error_message text,
  chunk_count int default 0,
  uploaded_by uuid references auth.users(id) on delete set null,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  metadata jsonb default '{}'::jsonb
);
create index idx_documents_status on tfm.documents(status);
create index idx_documents_area on tfm.documents(area);

comment on table tfm.documents is
  'Documentos fuente (manuales, procedimientos, incidentes, FAQ). storage_path = {area}/{document_id}/{archivo}.';

create trigger trg_documents_updated_at
  before update on tfm.documents
  for each row execute function tfm.set_updated_at();

-- ---------------------------------------------------------------------
-- tfm.chunks — fragmentos vectorizados (384 dim, coseno)
-- ---------------------------------------------------------------------
create table tfm.chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid references tfm.documents(id) on delete cascade,
  chunk_index int not null,
  content text not null,
  embedding extensions.vector(384) not null,
  token_count int,
  metadata jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  constraint uq_chunks_document_index unique (document_id, chunk_index)
);
create index idx_chunks_hnsw on tfm.chunks using hnsw (embedding extensions.vector_cosine_ops);
create index idx_chunks_document on tfm.chunks(document_id);

comment on table tfm.chunks is
  'Fragmentos de documentos con su embedding. Índice HNSW con distancia coseno.';

-- ---------------------------------------------------------------------
-- tfm.incidents
-- ---------------------------------------------------------------------
create table tfm.incidents (
  id uuid primary key default gen_random_uuid(),
  code text unique not null,
  system_affected text not null,
  symptom text not null,
  diagnosis text,
  resolution text,
  severity text check (severity in ('baja','media','alta','critica')),
  resolved_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz default now(),
  document_id uuid references tfm.documents(id) on delete set null
);
create index idx_incidents_system on tfm.incidents(system_affected);
create index idx_incidents_symptom_trgm on tfm.incidents using gin (symptom extensions.gin_trgm_ops);

comment on table tfm.incidents is
  'Incidentes de TI Producción con diagnóstico y resolución; pueden vincularse a un documento indexado.';

-- ---------------------------------------------------------------------
-- tfm.queries
-- ---------------------------------------------------------------------
create table tfm.queries (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete set null,
  channel text not null check (channel in ('web','teams','api')),
  question text not null,
  answer text,
  sources jsonb,
  latency_ms int,
  tokens_input int,
  tokens_output int,
  abstained boolean default false,
  llm_provider text,
  llm_model text,
  trace_id text,
  created_at timestamptz default now()
);
create index idx_queries_user on tfm.queries(user_id);
create index idx_queries_created on tfm.queries(created_at desc);

comment on table tfm.queries is
  'Registro de consultas: respuesta, fuentes citadas, latencia, tokens y trace_id distribuido.';

-- ---------------------------------------------------------------------
-- tfm.feedback
-- ---------------------------------------------------------------------
create table tfm.feedback (
  id uuid primary key default gen_random_uuid(),
  query_id uuid references tfm.queries(id) on delete cascade,
  user_id uuid references auth.users(id) on delete cascade,
  rating smallint not null check (rating in (-1, 1)),
  comment text,
  created_at timestamptz default now(),
  constraint uq_feedback_query_user unique (query_id, user_id)
);
create index idx_feedback_query on tfm.feedback(query_id);

-- ---------------------------------------------------------------------
-- tfm.golden_dataset
-- ---------------------------------------------------------------------
create table tfm.golden_dataset (
  id uuid primary key default gen_random_uuid(),
  question text not null,
  expected_answer text not null,
  expected_document_id uuid references tfm.documents(id) on delete set null,
  tags text[],
  difficulty text check (difficulty in ('facil','media','dificil')),
  created_at timestamptz default now()
);

-- ---------------------------------------------------------------------
-- tfm.audit_events
-- ---------------------------------------------------------------------
create table tfm.audit_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete set null,
  action text not null,
  resource_type text not null,
  resource_id uuid,
  payload jsonb,
  ip_address inet,
  created_at timestamptz default now()
);
create index idx_audit_created on tfm.audit_events(created_at desc);
create index idx_audit_resource on tfm.audit_events(resource_type, resource_id);

-- >>> 20260101000005_functions.sql
-- =====================================================================
-- 20260101000005_functions.sql
-- Funciones de negocio, helpers de autorización y triggers (esquema tfm).
-- =====================================================================
set search_path = public, extensions;

-- ---------------------------------------------------------------------
-- Helpers de autorización (SECURITY DEFINER para leer tfm.profiles
-- desde las políticas RLS sin recursión).
-- ---------------------------------------------------------------------
create or replace function tfm.current_app_role()
returns text
language sql stable security definer
set search_path = ''
as $$
  select coalesce(
    (select p.role from tfm.profiles p where p.id = auth.uid()),
    'viewer'
  );
$$;

create or replace function tfm.current_app_area()
returns text
language sql stable security definer
set search_path = ''
as $$
  select p.area from tfm.profiles p where p.id = auth.uid();
$$;

create or replace function tfm.is_admin()
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select tfm.current_app_role() = 'admin';
$$;

create or replace function tfm.is_editor()
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select tfm.current_app_role() in ('editor', 'admin');
$$;

comment on function tfm.current_app_role() is 'Rol de aplicación del usuario del JWT (viewer por defecto).';
comment on function tfm.current_app_area() is 'Área funcional del usuario del JWT.';
comment on function tfm.is_admin()         is 'true si el usuario del JWT es admin.';
comment on function tfm.is_editor()        is 'true si el usuario del JWT es editor o admin.';

revoke execute on function tfm.current_app_role(), tfm.current_app_area(),
  tfm.is_admin(), tfm.is_editor() from public, anon;
grant execute on function tfm.current_app_role(), tfm.current_app_area(),
  tfm.is_admin(), tfm.is_editor() to authenticated, service_role;

-- ---------------------------------------------------------------------
-- Alta automática de perfil al registrarse un usuario.
-- Rol y área se leen de raw_app_meta_data, que solo puede escribir
-- service_role (el usuario NO puede autoasignarse rol ni área).
-- ---------------------------------------------------------------------
create or replace function tfm.handle_new_user()
returns trigger
language plpgsql security definer
set search_path = ''
as $$
declare
  v_role text := lower(coalesce(new.raw_app_meta_data->>'role', ''));
  v_area text := lower(coalesce(new.raw_app_meta_data->>'area', ''));
begin
  if v_role not in ('viewer', 'editor', 'admin') then
    v_role := 'viewer';
  end if;
  if v_area !~ '^[a-z0-9_-]+$' then
    v_area := 'general';
  end if;

  insert into tfm.profiles (id, email, full_name, area, role)
  values (
    new.id,
    new.email,
    coalesce(
      new.raw_user_meta_data->>'full_name',
      new.raw_user_meta_data->>'name',
      split_part(coalesce(new.email, ''), '@', 1)
    ),
    v_area,
    v_role
  )
  on conflict (id) do nothing;

  return new;
end;
$$;

drop trigger if exists tfm_on_auth_user_created on auth.users;
create trigger tfm_on_auth_user_created
  after insert on auth.users
  for each row execute function tfm.handle_new_user();

-- Perfiles para usuarios que ya existían antes de esta migración
insert into tfm.profiles (id, email, full_name)
select u.id, u.email, split_part(coalesce(u.email, ''), '@', 1)
from auth.users u
on conflict (id) do nothing;

-- ---------------------------------------------------------------------
-- Impide que un usuario no-admin cambie su propio rol o área.
-- SECURITY INVOKER: current_user es el rol de la sesión.
-- ---------------------------------------------------------------------
create or replace function tfm.protect_profile_privileges()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if (new.role is distinct from old.role
      or new.area is distinct from old.area
      or new.id is distinct from old.id)
     and current_user in ('authenticated', 'anon')
     and not tfm.is_admin() then
    raise exception 'Solo un administrador puede modificar el rol o el área de un usuario'
      using errcode = '42501';
  end if;
  return new;
end;
$$;

create trigger trg_profiles_protect_privileges
  before update on tfm.profiles
  for each row execute function tfm.protect_profile_privileges();

-- ---------------------------------------------------------------------
-- Auditoría genérica (INSERT/UPDATE/DELETE) -> tfm.audit_events
-- ---------------------------------------------------------------------
create or replace function tfm.log_change()
returns trigger
language plpgsql security definer
set search_path = ''
as $$
declare
  v_row jsonb := case when tg_op = 'DELETE' then to_jsonb(old) else to_jsonb(new) end;
  v_id uuid;
  v_ip inet;
begin
  begin
    v_id := (v_row->>'id')::uuid;
  exception when others then
    v_id := null;
  end;

  -- IP del cliente si la petición llega por PostgREST
  begin
    v_ip := nullif(trim(split_part(
      coalesce(current_setting('request.headers', true)::jsonb->>'x-forwarded-for', ''),
      ',', 1)), '')::inet;
  exception when others then
    v_ip := null;
  end;

  insert into tfm.audit_events (user_id, action, resource_type, resource_id, payload, ip_address)
  values (
    auth.uid(),
    lower(tg_op),
    tg_table_schema || '.' || tg_table_name,
    v_id,
    case
      when tg_op = 'UPDATE' then jsonb_build_object('old', to_jsonb(old), 'new', to_jsonb(new))
      else v_row
    end,
    v_ip
  );

  return null;
end;
$$;

comment on function tfm.log_change() is
  'Trigger AFTER que registra cambios en tfm.audit_events con usuario (auth.uid()) e IP de origen.';

create trigger trg_audit_documents
  after insert or update or delete on tfm.documents
  for each row execute function tfm.log_change();

create trigger trg_audit_incidents
  after insert or update or delete on tfm.incidents
  for each row execute function tfm.log_change();

create trigger trg_audit_golden_dataset
  after insert or update or delete on tfm.golden_dataset
  for each row execute function tfm.log_change();

create trigger trg_audit_profiles
  after update or delete on tfm.profiles
  for each row execute function tfm.log_change();

-- ---------------------------------------------------------------------
-- tfm.match_chunks — búsqueda vectorial (similitud coseno)
--
-- SECURITY INVOKER: con el JWT de un usuario aplica RLS; con
-- service_role (rag-service) se filtra por área con filter_area.
-- ---------------------------------------------------------------------
create or replace function tfm.match_chunks(
  query_embedding extensions.vector(384),
  match_threshold float default 0.35,
  match_count int default 20,
  filter_area text default null
)
returns table (
  chunk_id uuid,
  document_id uuid,
  content text,
  similarity float,
  document_title text,
  source_type text,
  chunk_index int
)
language sql stable
set search_path = tfm, public, extensions
as $$
  select
    c.id,
    c.document_id,
    c.content,
    1 - (c.embedding <=> query_embedding) as similarity,
    d.title,
    d.source_type,
    c.chunk_index
  from tfm.chunks c
  join tfm.documents d on d.id = c.document_id
  where d.status = 'indexed'
    and (filter_area is null or d.area = filter_area)
    and 1 - (c.embedding <=> query_embedding) > match_threshold
  order by c.embedding <=> query_embedding
  limit least(greatest(match_count, 1), 200);
$$;

comment on function tfm.match_chunks(extensions.vector, float, int, text) is
  'Top-k chunks de documentos indexados por similitud coseno, con umbral y filtro de área opcional.';

revoke execute on function tfm.match_chunks(extensions.vector, float, int, text) from public, anon;
grant execute on function tfm.match_chunks(extensions.vector, float, int, text)
  to authenticated, service_role;

-- >>> 20260101000006_rls_policies.sql
-- =====================================================================
-- 20260101000006_rls_policies.sql
-- Row Level Security, Storage y Realtime (esquema tfm).
--
-- Matriz de acceso (service_role tiene BYPASSRLS):
--   documents/chunks : leen su área + 'general'; editor escribe en su
--                      área; admin todo.
--   incidents        : todos leen; editor crea/edita; admin borra.
--   queries/feedback : cada usuario solo los suyos; admin lee todo.
--   golden_dataset   : todos leen; admin escribe.
--   audit_events     : solo admin lee; nadie escribe salvo triggers.
--   profiles         : cada uno el suyo; admin todos.
--
-- Los helpers se envuelven en (select ...) para que Postgres los evalúe
-- una vez por sentencia (initplan) y no por fila.
-- =====================================================================
set search_path = public, extensions;

alter table tfm.profiles        enable row level security;
alter table tfm.documents       enable row level security;
alter table tfm.chunks          enable row level security;
alter table tfm.incidents       enable row level security;
alter table tfm.queries         enable row level security;
alter table tfm.feedback        enable row level security;
alter table tfm.golden_dataset  enable row level security;
alter table tfm.audit_events    enable row level security;

-- ---------------------------------------------------------------------
-- tfm.profiles
-- ---------------------------------------------------------------------
create policy profiles_select on tfm.profiles
  for select to authenticated
  using (id = (select auth.uid()) or (select tfm.is_admin()));

-- El trigger trg_profiles_protect_privileges impide cambiar rol/área
create policy profiles_update on tfm.profiles
  for update to authenticated
  using (id = (select auth.uid()) or (select tfm.is_admin()))
  with check (id = (select auth.uid()) or (select tfm.is_admin()));

-- ---------------------------------------------------------------------
-- tfm.documents
-- ---------------------------------------------------------------------
create policy documents_select on tfm.documents
  for select to authenticated
  using (
    (select tfm.is_admin())
    or area = 'general'
    or area = (select tfm.current_app_area())
  );

create policy documents_insert on tfm.documents
  for insert to authenticated
  with check (
    (select tfm.is_editor())
    and uploaded_by = (select auth.uid())
    and ((select tfm.is_admin()) or area = (select tfm.current_app_area()))
  );

create policy documents_update on tfm.documents
  for update to authenticated
  using (
    (select tfm.is_editor())
    and ((select tfm.is_admin()) or area = (select tfm.current_app_area()))
  )
  with check (
    (select tfm.is_editor())
    and ((select tfm.is_admin()) or area = (select tfm.current_app_area()))
  );

create policy documents_delete on tfm.documents
  for delete to authenticated
  using ((select tfm.is_admin()));

-- ---------------------------------------------------------------------
-- tfm.chunks — visibles si el documento padre es visible
-- ---------------------------------------------------------------------
create policy chunks_select on tfm.chunks
  for select to authenticated
  using (exists (select 1 from tfm.documents d where d.id = chunks.document_id));

create policy chunks_admin_write on tfm.chunks
  for all to authenticated
  using ((select tfm.is_admin()))
  with check ((select tfm.is_admin()));

-- ---------------------------------------------------------------------
-- tfm.incidents
-- ---------------------------------------------------------------------
create policy incidents_select on tfm.incidents
  for select to authenticated
  using (true);

create policy incidents_insert on tfm.incidents
  for insert to authenticated
  with check ((select tfm.is_editor()) and created_by = (select auth.uid()));

create policy incidents_update on tfm.incidents
  for update to authenticated
  using ((select tfm.is_editor()))
  with check ((select tfm.is_editor()));

create policy incidents_delete on tfm.incidents
  for delete to authenticated
  using ((select tfm.is_admin()));

-- ---------------------------------------------------------------------
-- tfm.queries
-- ---------------------------------------------------------------------
create policy queries_select on tfm.queries
  for select to authenticated
  using (user_id = (select auth.uid()) or (select tfm.is_admin()));

create policy queries_insert on tfm.queries
  for insert to authenticated
  with check (user_id = (select auth.uid()));

create policy queries_delete on tfm.queries
  for delete to authenticated
  using ((select tfm.is_admin()));

-- ---------------------------------------------------------------------
-- tfm.feedback
-- ---------------------------------------------------------------------
create policy feedback_select on tfm.feedback
  for select to authenticated
  using (user_id = (select auth.uid()) or (select tfm.is_admin()));

create policy feedback_insert on tfm.feedback
  for insert to authenticated
  with check (
    user_id = (select auth.uid())
    and exists (
      select 1 from tfm.queries q
      where q.id = feedback.query_id and q.user_id = (select auth.uid())
    )
  );

create policy feedback_update on tfm.feedback
  for update to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

create policy feedback_delete on tfm.feedback
  for delete to authenticated
  using (user_id = (select auth.uid()));

-- ---------------------------------------------------------------------
-- tfm.golden_dataset
-- ---------------------------------------------------------------------
create policy golden_select on tfm.golden_dataset
  for select to authenticated
  using (true);

create policy golden_admin_write on tfm.golden_dataset
  for all to authenticated
  using ((select tfm.is_admin()))
  with check ((select tfm.is_admin()));

-- ---------------------------------------------------------------------
-- tfm.audit_events — solo lectura para admin
-- ---------------------------------------------------------------------
create policy audit_admin_select on tfm.audit_events
  for select to authenticated
  using ((select tfm.is_admin()));

-- ---------------------------------------------------------------------
-- Realtime: estado de documentos y nuevas consultas (dashboard)
-- ---------------------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    create publication supabase_realtime;
  end if;

  if not exists (select 1 from pg_publication_tables
                 where pubname = 'supabase_realtime'
                   and schemaname = 'tfm' and tablename = 'documents') then
    alter publication supabase_realtime add table tfm.documents;
  end if;

  if not exists (select 1 from pg_publication_tables
                 where pubname = 'supabase_realtime'
                   and schemaname = 'tfm' and tablename = 'queries') then
    alter publication supabase_realtime add table tfm.queries;
  end if;
exception when insufficient_privilege then
  raise warning 'No se pudo configurar la publicación supabase_realtime: %', sqlerrm;
end;
$$;

-- ---------------------------------------------------------------------
-- Storage: bucket privado "documents"  ({area}/{document_id}/{archivo})
-- ---------------------------------------------------------------------
do $$
begin
  if to_regclass('storage.buckets') is null then
    raise warning 'Esquema storage no disponible: reaplica esta migración cuando Storage esté activo.';
    return;
  end if;

  insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values (
    'documents', 'documents', false, 52428800,
    array[
      'application/pdf',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'text/markdown',
      'text/x-markdown',
      'text/plain'
    ]
  )
  on conflict (id) do nothing;

  begin
    execute $p$
      create policy tfm_documents_bucket_select on storage.objects
        for select to authenticated
        using (
          bucket_id = 'documents'
          and (
            (select tfm.is_admin())
            or (storage.foldername(name))[1] = 'general'
            or (storage.foldername(name))[1] = (select tfm.current_app_area())
          )
        )
    $p$;

    execute $p$
      create policy tfm_documents_bucket_insert on storage.objects
        for insert to authenticated
        with check (
          bucket_id = 'documents'
          and (select tfm.is_editor())
          and (
            (select tfm.is_admin())
            or (storage.foldername(name))[1] = (select tfm.current_app_area())
          )
        )
    $p$;

    execute $p$
      create policy tfm_documents_bucket_delete on storage.objects
        for delete to authenticated
        using (bucket_id = 'documents' and (select tfm.is_admin()))
    $p$;
  exception
    when insufficient_privilege then
      raise warning 'Sin privilegios para crear políticas en storage.objects (%). '
                    'El acceso seguirá funcionando vía service_role.', sqlerrm;
    when duplicate_object then
      null;
  end;
end;
$$;

-- >>> 20260101000007_match_chunks_metadata.sql
-- =====================================================================
-- 20260101000007_match_chunks_metadata.sql
-- match_chunks devuelve también los metadatos del chunk (sección, página),
-- que el ingest-service guarda desde la Fase 3. Permite citas del tipo
-- [Fuente: Manual X, Paso 2 (pág. 3)] en lugar de "fragmento N".
--
-- Cambiar el tipo de retorno exige DROP + CREATE (no basta con REPLACE).
-- =====================================================================
set search_path = public, extensions;

drop function if exists tfm.match_chunks(extensions.vector, float, int, text);

create function tfm.match_chunks(
  query_embedding extensions.vector(384),
  match_threshold float default 0.35,
  match_count int default 20,
  filter_area text default null
)
returns table (
  chunk_id uuid,
  document_id uuid,
  content text,
  similarity float,
  document_title text,
  source_type text,
  chunk_index int,
  metadata jsonb
)
language sql stable
set search_path = tfm, public, extensions
as $$
  select
    c.id,
    c.document_id,
    c.content,
    1 - (c.embedding <=> query_embedding) as similarity,
    d.title,
    d.source_type,
    c.chunk_index,
    coalesce(c.metadata, '{}'::jsonb)
  from tfm.chunks c
  join tfm.documents d on d.id = c.document_id
  where d.status = 'indexed'
    and (filter_area is null or d.area = filter_area)
    and 1 - (c.embedding <=> query_embedding) > match_threshold
  order by c.embedding <=> query_embedding
  limit least(greatest(match_count, 1), 200);
$$;

comment on function tfm.match_chunks(extensions.vector, float, int, text) is
  'Top-k chunks de documentos indexados por similitud coseno, con umbral, filtro de área y metadatos (sección/página).';

revoke execute on function tfm.match_chunks(extensions.vector, float, int, text) from public, anon;
grant execute on function tfm.match_chunks(extensions.vector, float, int, text)
  to authenticated, service_role;

-- >>> registro de migraciones (compatible con Supabase CLI)
create schema if not exists supabase_migrations;
create table if not exists supabase_migrations.schema_migrations (version text primary key, statements text[], name text);
insert into supabase_migrations.schema_migrations (version, name) values ('20260101000001', 'init') on conflict do nothing;
insert into supabase_migrations.schema_migrations (version, name) values ('20260101000002', 'pgvector') on conflict do nothing;
insert into supabase_migrations.schema_migrations (version, name) values ('20260101000003', 'schemas') on conflict do nothing;
insert into supabase_migrations.schema_migrations (version, name) values ('20260101000004', 'tables') on conflict do nothing;
insert into supabase_migrations.schema_migrations (version, name) values ('20260101000005', 'functions') on conflict do nothing;
insert into supabase_migrations.schema_migrations (version, name) values ('20260101000006', 'rls_policies') on conflict do nothing;
insert into supabase_migrations.schema_migrations (version, name) values ('20260101000007', 'match_chunks_metadata') on conflict do nothing;

-- >>> seed.sql
-- =====================================================================
-- seed.sql — Datos de ejemplo (idempotente)
-- Los documentos y el golden dataset se cargan en fases posteriores
-- (scripts/seed_corpus.py y tests/golden_dataset.json).
-- =====================================================================

insert into tfm.incidents (code, system_affected, symptom, diagnosis, resolution, severity, resolved_at)
values
  ('INC-2026-0001', 'Core bancario',
   'El proceso batch de cierre diario no finaliza y queda en estado RUNNING después de las 02:00.',
   'Bloqueo en la tabla de saldos por una transacción de conciliación no confirmada.',
   'Identificar la sesión bloqueante, coordinar con el DBA de turno su cancelación y relanzar el paso de cierre desde el último checkpoint.',
   'critica', now() - interval '20 days'),
  ('INC-2026-0002', 'Banca en línea',
   'Usuarios reportan error HTTP 502 al iniciar sesión en la banca web.',
   'Pool de conexiones del servicio de autenticación agotado tras un despliegue.',
   'Reiniciar ordenadamente los nodos del servicio de autenticación y aumentar el tamaño del pool según el procedimiento de capacidad.',
   'alta', now() - interval '12 days'),
  ('INC-2026-0003', 'Cajeros automáticos (ATM)',
   'Retiros rechazados con código de respuesta 91 en una red de cajeros.',
   'Caída del enlace con el switch transaccional del proveedor.',
   'Activar el enlace de contingencia y escalar al proveedor según la matriz de escalamiento.',
   'alta', now() - interval '7 days'),
  ('INC-2026-0004', 'Transferencias interbancarias',
   'Lote de transferencias SPI queda pendiente de envío.',
   'Certificado de firma digital próximo a expirar no fue renovado.',
   'Renovar el certificado con el área de Seguridad y reenviar el lote desde la consola de pagos.',
   'media', now() - interval '3 days'),
  ('INC-2026-0005', 'Reportería regulatoria',
   'El reporte diario para el ente de control se genera vacío.',
   'Cambio de esquema en la vista de origen sin actualización del ETL.',
   'Actualizar el mapeo del ETL, regenerar el reporte y validar totales de control con Riesgos.',
   'baja', null)
on conflict (code) do nothing;

notify pgrst, 'reload schema';
commit;
