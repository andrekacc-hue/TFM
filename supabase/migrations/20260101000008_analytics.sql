-- =====================================================================
-- 20260101000008_analytics.sql
-- Métricas para el analytics-service y la evaluación académica.
--
--   * tfm.queries guarda la latencia por etapa (timings) y el motivo de
--     abstención, que el rag-service ya calcula.
--   * Las agregaciones se hacen en PostgreSQL (percentiles, tasas): traer
--     todas las filas por la API para agregarlas en Python no escala.
--   * Solo service_role puede ejecutarlas; el api-gateway decide qué
--     roles de usuario ven las métricas.
-- =====================================================================
set search_path = public, extensions;

alter table tfm.queries add column if not exists timings jsonb;
alter table tfm.queries add column if not exists abstention_reason text;
create index if not exists idx_queries_channel_created on tfm.queries (channel, created_at desc);
create index if not exists idx_queries_abstained on tfm.queries (created_at desc) where abstained;

-- ---------------------------------------------------------------------
-- Resumen del periodo
-- ---------------------------------------------------------------------
create or replace function tfm.metrics_summary(
  p_from timestamptz,
  p_to timestamptz,
  p_channel text default null
)
returns jsonb
language sql stable
set search_path = tfm, public
as $$
  with q as (
    select * from tfm.queries
    where created_at >= p_from and created_at < p_to
      and (p_channel is null or channel = p_channel)
  ),
  answered as (select * from q where not abstained),
  f as (select fb.rating from tfm.feedback fb join q on q.id = fb.query_id)
  select jsonb_build_object(
    'total_queries',      (select count(*) from q),
    'unique_users',       (select count(distinct user_id) from q),
    'answered',           (select count(*) from answered),
    'abstained',          (select count(*) from q where abstained),
    'abstention_rate',    (select round(avg(case when abstained then 1 else 0 end)::numeric, 4) from q),
    'blocked_by_guardrails', (select count(*) from q where abstention_reason like 'guardrail:%'),
    'latency_ms', jsonb_build_object(
      'avg', (select round(avg(latency_ms)) from answered),
      'p50', (select round(percentile_cont(0.50) within group (order by latency_ms)) from answered where latency_ms is not null),
      'p90', (select round(percentile_cont(0.90) within group (order by latency_ms)) from answered where latency_ms is not null),
      'p95', (select round(percentile_cont(0.95) within group (order by latency_ms)) from answered where latency_ms is not null),
      'p99', (select round(percentile_cont(0.99) within group (order by latency_ms)) from answered where latency_ms is not null)
    ),
    'stage_avg_ms', jsonb_build_object(
      'retrieval',  (select round(avg((timings->>'retrieval_ms')::numeric)) from answered),
      'rerank',     (select round(avg((timings->>'rerank_ms')::numeric)) from answered),
      'generation', (select round(avg((timings->>'generation_ms')::numeric)) from answered)
    ),
    'tokens', jsonb_build_object(
      'input',  (select coalesce(sum(tokens_input), 0) from q),
      'output', (select coalesce(sum(tokens_output), 0) from q)
    ),
    'feedback', jsonb_build_object(
      'count',             (select count(*) from f),
      'positive',          (select count(*) from f where rating = 1),
      'negative',          (select count(*) from f where rating = -1),
      'satisfaction_rate', (select round(avg(case when rating = 1 then 1 else 0 end)::numeric, 4) from f),
      'coverage',          (select round((select count(*) from f)::numeric / nullif((select count(*) from answered), 0), 4))
    ),
    'by_channel', (select coalesce(jsonb_object_agg(channel, n), '{}'::jsonb)
                   from (select channel, count(*) n from q group by channel) s),
    'by_model',   (select coalesce(jsonb_object_agg(coalesce(llm_provider || ':' || llm_model, 'sin_llm'), n), '{}'::jsonb)
                   from (select llm_provider, llm_model, count(*) n from q group by 1, 2) s)
  );
$$;

-- ---------------------------------------------------------------------
-- Serie temporal
-- ---------------------------------------------------------------------
create or replace function tfm.metrics_timeseries(
  p_from timestamptz,
  p_to timestamptz,
  p_bucket text default 'day',
  p_channel text default null
)
returns table (
  bucket timestamptz,
  queries bigint,
  abstained bigint,
  avg_latency_ms numeric,
  p95_latency_ms numeric,
  positive_feedback bigint,
  negative_feedback bigint
)
language sql stable
set search_path = tfm, public
as $$
  select
    date_trunc(case when p_bucket in ('hour', 'day', 'week', 'month') then p_bucket else 'day' end, q.created_at),
    count(distinct q.id),
    count(distinct q.id) filter (where q.abstained),
    round(avg(q.latency_ms) filter (where not q.abstained)),
    round((percentile_cont(0.95) within group (order by q.latency_ms) filter (where not q.abstained))::numeric),
    count(fb.id) filter (where fb.rating = 1),
    count(fb.id) filter (where fb.rating = -1)
  from tfm.queries q
  left join tfm.feedback fb on fb.query_id = q.id
  where q.created_at >= p_from and q.created_at < p_to
    and (p_channel is null or q.channel = p_channel)
  group by 1
  order by 1;
$$;

-- ---------------------------------------------------------------------
-- Documentos más citados
-- ---------------------------------------------------------------------
create or replace function tfm.metrics_top_documents(
  p_from timestamptz,
  p_to timestamptz,
  p_limit int default 10
)
returns table (document_id uuid, title text, citations bigint, queries bigint, avg_similarity numeric)
language sql stable
set search_path = tfm, public
as $$
  select
    (s->>'document_id')::uuid,
    max(s->>'title'),
    count(*),
    count(distinct q.id),
    round(avg((s->>'similarity')::numeric), 3)
  from tfm.queries q
  cross join lateral jsonb_array_elements(coalesce(q.sources, '[]'::jsonb)) s
  where q.created_at >= p_from and q.created_at < p_to
  group by 1
  order by 3 desc
  limit least(greatest(p_limit, 1), 100);
$$;

-- ---------------------------------------------------------------------
-- Preguntas sin respuesta: brechas de la base de conocimientos
-- ---------------------------------------------------------------------
create or replace function tfm.metrics_unanswered(
  p_from timestamptz,
  p_to timestamptz,
  p_limit int default 20
)
returns table (question text, times bigint, last_asked timestamptz, reason text)
language sql stable
set search_path = tfm, public
as $$
  select question, count(*), max(created_at), max(abstention_reason)
  from tfm.queries
  where abstained
    and created_at >= p_from and created_at < p_to
    and coalesce(abstention_reason, '') not like 'guardrail:%'
  group by question
  order by 2 desc, 3 desc
  limit least(greatest(p_limit, 1), 200);
$$;

-- ---------------------------------------------------------------------
-- Estado de la base de conocimientos
-- ---------------------------------------------------------------------
create or replace function tfm.metrics_knowledge_base()
returns jsonb
language sql stable
set search_path = tfm, public
as $$
  select jsonb_build_object(
    'documents',  (select count(*) from tfm.documents),
    'by_status',  (select coalesce(jsonb_object_agg(status, n), '{}'::jsonb)
                   from (select status, count(*) n from tfm.documents group by status) s),
    'by_area',    (select coalesce(jsonb_object_agg(area, n), '{}'::jsonb)
                   from (select area, count(*) n from tfm.documents where status = 'indexed' group by area) s),
    'by_type',    (select coalesce(jsonb_object_agg(source_type, n), '{}'::jsonb)
                   from (select source_type, count(*) n from tfm.documents where status = 'indexed' group by source_type) s),
    'chunks',     (select count(*) from tfm.chunks),
    'incidents',  (select count(*) from tfm.incidents),
    'golden_questions', (select count(*) from tfm.golden_dataset)
  );
$$;

do $$
declare
  fn text;
begin
  foreach fn in array array[
    'tfm.metrics_summary(timestamptz, timestamptz, text)',
    'tfm.metrics_timeseries(timestamptz, timestamptz, text, text)',
    'tfm.metrics_top_documents(timestamptz, timestamptz, int)',
    'tfm.metrics_unanswered(timestamptz, timestamptz, int)',
    'tfm.metrics_knowledge_base()'
  ] loop
    execute format('revoke execute on function %s from public, anon, authenticated', fn);
    execute format('grant execute on function %s to service_role', fn);
  end loop;
end;
$$;
