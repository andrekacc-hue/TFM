-- =====================================================================
-- Evaluación con RAGAs (migración 11): golden_dataset.code/expected_behavior
-- y RLS de tfm.evaluation_runs (viewer no ve métricas; editor sí; nadie escribe).
-- =====================================================================
begin;

create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;

select no_plan();

select has_table('tfm', 'evaluation_runs', 'tabla tfm.evaluation_runs');
select has_column('tfm', 'golden_dataset', 'code', 'golden_dataset.code');
select col_is_unique('tfm', 'golden_dataset', 'code', 'golden_dataset.code es único');

select throws_ok(
  $$ insert into tfm.golden_dataset (question, expected_answer, expected_behavior) values ('x', 'y', 'inventar') $$,
  '23514', null, 'expected_behavior solo admite answer/abstain');

insert into tfm.evaluation_runs (id, questions, metrics)
values ('e1000000-0000-0000-0000-000000000001', 30, '{"faithfulness": 0.9}');

insert into auth.users (id, email, aud, role, raw_app_meta_data) values
  ('00000000-0000-0000-0000-0000000000c1', 'eval-viewer@test.local', 'authenticated', 'authenticated', '{"role":"viewer","area":"general"}'),
  ('00000000-0000-0000-0000-0000000000c2', 'eval-editor@test.local', 'authenticated', 'authenticated', '{"role":"editor","area":"general"}');

-- viewer
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c1","role":"authenticated"}', true);
set local role authenticated;
select is((select count(*)::int from tfm.evaluation_runs where id = 'e1000000-0000-0000-0000-000000000001'), 0,
  'viewer no ve las ejecuciones de evaluación');

-- editor
reset role;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c2","role":"authenticated"}', true);
set local role authenticated;
select is((select count(*)::int from tfm.evaluation_runs where id = 'e1000000-0000-0000-0000-000000000001'), 1,
  'editor ve las ejecuciones de evaluación');
select throws_ok(
  $$ insert into tfm.evaluation_runs (questions, metrics) values (1, '{}') $$,
  '42501', null, 'editor no puede registrar ejecuciones (solo el script con service_role)');

reset role;
select * from finish();
rollback;
