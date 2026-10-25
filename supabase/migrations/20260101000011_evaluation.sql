-- =====================================================================
-- 20260101000011_evaluation.sql
-- Evaluación del asistente con RAGAs (Fase 8).
--
--   tests/golden_dataset.json ──scripts/run_evaluation.py──► tfm.golden_dataset (upsert por code)
--   gateway /api/v1/query ──► RAGAs (juez LLM) ──► tfm.evaluation_runs ──► portal /evaluacion
--
-- Cada ejecución guarda las métricas agregadas (para comparar ejecuciones en el
-- portal) y el detalle por pregunta (para auditar respuestas concretas).
-- =====================================================================

-- ---------------------------------------------------------------------
-- golden_dataset: código estable y comportamiento esperado
-- ---------------------------------------------------------------------
alter table tfm.golden_dataset add column if not exists code text unique;
alter table tfm.golden_dataset add column if not exists expected_behavior text not null default 'answer'
  check (expected_behavior in ('answer', 'abstain'));

comment on column tfm.golden_dataset.code is
  'Identificador estable (GD-01…) del fichero tests/golden_dataset.json; permite recargarlo sin duplicar.';
comment on column tfm.golden_dataset.expected_behavior is
  'answer = la respuesta está en el corpus; abstain = fuera de alcance, lo correcto es abstenerse.';

-- ---------------------------------------------------------------------
-- evaluation_runs
-- ---------------------------------------------------------------------
create table if not exists tfm.evaluation_runs (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  label text,
  llm_provider text,
  llm_model text,
  judge_model text,
  questions int not null check (questions >= 0),
  metrics jsonb not null,
  results jsonb not null default '[]'::jsonb,
  config jsonb not null default '{}'::jsonb,
  duration_s numeric
);

create index if not exists idx_evaluation_runs_created on tfm.evaluation_runs (created_at desc);

comment on table tfm.evaluation_runs is
  'Ejecuciones de scripts/run_evaluation.py: métricas RAGAs y de abstención agregadas + detalle por pregunta.';
comment on column tfm.evaluation_runs.metrics is
  'faithfulness, answer_relevancy, context_precision, context_recall (media 0..1), abstención, latencias.';

alter table tfm.evaluation_runs enable row level security;

-- Las métricas de calidad son información interna de TI: editores y admin las consultan
-- en el portal; solo el script (service_role, que ignora RLS) o un admin las escriben.
create policy evaluation_runs_select on tfm.evaluation_runs
  for select to authenticated
  using ((select tfm.is_editor()));

create policy evaluation_runs_admin_delete on tfm.evaluation_runs
  for delete to authenticated
  using ((select tfm.is_admin()));
