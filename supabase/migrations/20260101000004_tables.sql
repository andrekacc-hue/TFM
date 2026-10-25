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
