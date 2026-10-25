-- =====================================================================
-- Tests de la Fase 1 (pgTAP): estructura, búsqueda vectorial y RLS.
-- Todo corre en una transacción que se revierte: no deja datos.
-- Las aserciones cuentan solo los fixtures (ids d0000000-...) para no depender
-- de los datos reales que ya existan en la base.
--
--   scripts/bootstrap.sh --test-only     (o .\scripts\bootstrap.ps1 -TestOnly)
-- =====================================================================
begin;

create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;

select no_plan();

-- ---------------------------------------------------------------------
-- 1. Estructura
-- ---------------------------------------------------------------------
select has_extension('vector', 'pgvector está instalado');
select has_schema('tfm', 'esquema tfm');

select has_table('tfm', 'profiles', 'tabla tfm.profiles');
select has_table('tfm', 'documents', 'tabla tfm.documents');
select has_table('tfm', 'chunks', 'tabla tfm.chunks');
select has_table('tfm', 'incidents', 'tabla tfm.incidents');
select has_table('tfm', 'queries', 'tabla tfm.queries');
select has_table('tfm', 'feedback', 'tabla tfm.feedback');
select has_table('tfm', 'golden_dataset', 'tabla tfm.golden_dataset');
select has_table('tfm', 'audit_events', 'tabla tfm.audit_events');

select has_function('tfm', 'match_chunks', 'función tfm.match_chunks');
select has_index('tfm', 'chunks', 'idx_chunks_hnsw', 'índice HNSW sobre embeddings');

select is(
  (select atttypmod from pg_attribute
   where attrelid = 'tfm.chunks'::regclass and attname = 'embedding'),
  384,
  'embedding tiene 384 dimensiones'
);

select ok(c.relrowsecurity, format('RLS habilitado en %s', c.oid::regclass))
from pg_class c
where c.oid in (
  'tfm.profiles'::regclass, 'tfm.documents'::regclass, 'tfm.chunks'::regclass,
  'tfm.incidents'::regclass, 'tfm.queries'::regclass, 'tfm.feedback'::regclass,
  'tfm.golden_dataset'::regclass, 'tfm.audit_events'::regclass
);

-- ---------------------------------------------------------------------
-- 2. Fixtures (como postgres, dueño de las tablas => sin RLS)
-- ---------------------------------------------------------------------
insert into auth.users (id, email, aud, role, raw_app_meta_data, raw_user_meta_data)
values
  ('00000000-0000-0000-0000-0000000000a1', 'viewer.ops@test.local',  'authenticated', 'authenticated',
   '{"area":"operaciones","role":"viewer"}', '{"full_name":"Viewer Operaciones"}'),
  ('00000000-0000-0000-0000-0000000000a2', 'viewer.cred@test.local', 'authenticated', 'authenticated',
   '{"area":"creditos","role":"viewer"}', '{}'),
  ('00000000-0000-0000-0000-0000000000a3', 'editor.ops@test.local',  'authenticated', 'authenticated',
   '{"area":"operaciones","role":"editor"}', '{}'),
  ('00000000-0000-0000-0000-0000000000a4', 'admin@test.local',       'authenticated', 'authenticated',
   '{"area":"general","role":"admin"}', '{}'),
  ('00000000-0000-0000-0000-0000000000a5', 'hacker@test.local',      'authenticated', 'authenticated',
   '{}', '{"role":"admin","area":"operaciones"}');

select is(
  (select role || '/' || area from tfm.profiles where id = '00000000-0000-0000-0000-0000000000a1'),
  'viewer/operaciones',
  'trigger crea el perfil con rol y área de app_metadata'
);
select is(
  (select full_name from tfm.profiles where id = '00000000-0000-0000-0000-0000000000a1'),
  'Viewer Operaciones',
  'trigger toma full_name de user_metadata'
);
select is(
  (select role || '/' || area from tfm.profiles where id = '00000000-0000-0000-0000-0000000000a5'),
  'viewer/general',
  'user_metadata NO permite autoasignarse rol ni área'
);

insert into tfm.documents (id, title, source_type, storage_path, area, status)
values
  ('d0000000-0000-0000-0000-000000000001', 'Manual operaciones', 'manual',
   'operaciones/d1/manual.pdf', 'operaciones', 'indexed'),
  ('d0000000-0000-0000-0000-000000000002', 'Manual créditos', 'manual',
   'creditos/d2/manual.pdf', 'creditos', 'indexed'),
  ('d0000000-0000-0000-0000-000000000003', 'Procedimiento pendiente', 'procedimiento',
   'operaciones/d3/proc.pdf', 'operaciones', 'pending'),
  ('d0000000-0000-0000-0000-000000000004', 'FAQ general', 'faq',
   'general/d4/faq.md', 'general', 'indexed');

-- Todos los chunks con el mismo vector (unos) => similitud 1 con la consulta "unos"
insert into tfm.chunks (document_id, chunk_index, content, embedding)
select d.id, 0, 'Contenido de ' || d.title, array_fill(1::real, array[384])::vector
from tfm.documents d
where d.id::text like 'd0000000-%';

create temp table q on commit drop as
select
  array_fill(1::real, array[384])::vector as ones,
  (select array_agg(case when i % 2 = 0 then 1 else -1 end)::real[]
   from generate_series(1, 384) i)::vector as orthogonal;
grant select on q to authenticated;

-- ---------------------------------------------------------------------
-- 3. match_chunks
-- ---------------------------------------------------------------------
select is(
  (select count(*)::int from tfm.match_chunks((select ones from q)) where document_id::text like 'd0000000-%'),
  3,
  'match_chunks devuelve solo documentos con status indexed'
);
select is(
  (select count(*)::int from tfm.match_chunks((select ones from q), 0.35, 20, 'creditos') where document_id::text like 'd0000000-%'),
  1,
  'match_chunks aplica filter_area'
);
select ok(
  (select min(similarity) from tfm.match_chunks((select ones from q)) where document_id::text like 'd0000000-%') > 0.99,
  'similitud coseno ~1 para vectores idénticos'
);
select is(
  (select count(*)::int from tfm.match_chunks((select orthogonal from q)) where document_id::text like 'd0000000-%'),
  0,
  'match_chunks aplica el umbral de similitud (abstención)'
);
select is(
  (select count(*)::int from tfm.match_chunks((select ones from q), 0.35, 1)),
  1,
  'match_chunks respeta match_count'
);

-- ---------------------------------------------------------------------
-- 4. RLS — viewer del área operaciones
-- ---------------------------------------------------------------------
select set_config('request.jwt.claims',
  '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', true);
set local role authenticated;

select is((select count(*)::int from tfm.documents where id::text like 'd0000000-%'), 3,
  'viewer operaciones ve documentos de operaciones + general');
select is((select count(*)::int from tfm.chunks where document_id::text like 'd0000000-%'), 3,
  'viewer operaciones ve chunks de sus documentos');
select is((select count(*)::int from tfm.match_chunks((select ones from q)) where document_id::text like 'd0000000-%'), 2,
  'RLS se aplica dentro de match_chunks');
select ok((select count(*) from tfm.incidents) >= 0, 'viewer puede leer incidentes');

select throws_ok(
  $$ insert into tfm.documents (title, source_type, storage_path, area, uploaded_by)
     values ('x', 'manual', 'operaciones/x/x.pdf', 'operaciones', '00000000-0000-0000-0000-0000000000a1') $$,
  '42501', null, 'viewer no puede registrar documentos');

select throws_ok(
  $$ update tfm.profiles set role = 'admin' where id = '00000000-0000-0000-0000-0000000000a1' $$,
  '42501', null, 'viewer no puede escalar su propio rol');

select lives_ok(
  $$ insert into tfm.queries (id, user_id, channel, question)
     values ('e0000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000a1', 'web', '¿Cómo reinicio el batch?') $$,
  'viewer registra su propia consulta');

select throws_ok(
  $$ insert into tfm.queries (user_id, channel, question)
     values ('00000000-0000-0000-0000-0000000000a2', 'web', 'suplantación') $$,
  '42501', null, 'viewer no puede registrar consultas a nombre de otro');

select lives_ok(
  $$ insert into tfm.feedback (query_id, user_id, rating)
     values ('e0000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000a1', 1) $$,
  'viewer valora su propia consulta');

select is((select count(*)::int from tfm.audit_events), 0, 'viewer no puede leer auditoría');

-- ---------------------------------------------------------------------
-- 5. RLS — viewer del área créditos
-- ---------------------------------------------------------------------
reset role;
select set_config('request.jwt.claims',
  '{"sub":"00000000-0000-0000-0000-0000000000a2","role":"authenticated"}', true);
set local role authenticated;

select is((select count(*)::int from tfm.documents where id::text like 'd0000000-%'), 2,
  'viewer créditos ve documentos de créditos + general');
select is((select count(*)::int from tfm.queries), 0,
  'un usuario no ve consultas de otros');
select is((select count(*)::int from tfm.feedback), 0,
  'un usuario no ve feedback de otros');

select throws_ok(
  $$ insert into tfm.feedback (query_id, user_id, rating)
     values ('e0000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000a2', -1) $$,
  '42501', null, 'no se puede valorar una consulta ajena');

-- ---------------------------------------------------------------------
-- 6. RLS — editor del área operaciones
-- ---------------------------------------------------------------------
reset role;
select set_config('request.jwt.claims',
  '{"sub":"00000000-0000-0000-0000-0000000000a3","role":"authenticated"}', true);
set local role authenticated;

select lives_ok(
  $$ insert into tfm.documents (title, source_type, storage_path, area, uploaded_by)
     values ('Nuevo procedimiento', 'procedimiento', 'operaciones/n/p.pdf', 'operaciones',
             '00000000-0000-0000-0000-0000000000a3') $$,
  'editor registra documentos en su área');

select throws_ok(
  $$ insert into tfm.documents (title, source_type, storage_path, area, uploaded_by)
     values ('Fuera de área', 'manual', 'creditos/n/m.pdf', 'creditos',
             '00000000-0000-0000-0000-0000000000a3') $$,
  '42501', null, 'editor no puede registrar documentos de otra área');

select lives_ok(
  $$ insert into tfm.incidents (code, system_affected, symptom, created_by)
     values ('INC-TEST-0001', 'Core', 'Prueba', '00000000-0000-0000-0000-0000000000a3') $$,
  'editor registra incidentes');

select is(
  (select count(*)::int from tfm.documents where area = 'creditos' and id::text like 'd0000000-%'),
  0,
  'editor no ve documentos de otra área'
);

-- ---------------------------------------------------------------------
-- 7. RLS — admin
-- ---------------------------------------------------------------------
reset role;
select set_config('request.jwt.claims',
  '{"sub":"00000000-0000-0000-0000-0000000000a4","role":"authenticated"}', true);
set local role authenticated;

select is((select count(*)::int from tfm.documents where id::text like 'd0000000-%'), 4,
  'admin ve documentos de todas las áreas');
select is((select count(*)::int from tfm.queries where id = 'e0000000-0000-0000-0000-000000000001'), 1,
  'admin ve consultas de todos los usuarios');
select ok((select count(*) from tfm.audit_events where resource_type = 'tfm.documents') > 0,
  'los cambios en documentos quedan auditados y el admin los lee');
select lives_ok(
  $$ update tfm.profiles set area = 'creditos' where id = '00000000-0000-0000-0000-0000000000a1' $$,
  'admin puede cambiar el área de un usuario');

-- ---------------------------------------------------------------------
-- 8. anon sin acceso a esquemas de negocio
-- ---------------------------------------------------------------------
reset role;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
set local role anon;

select throws_ok(
  $$ select 1 from tfm.documents $$,
  '42501', null, 'anon no puede leer tfm.documents');

reset role;

select * from finish();
rollback;
