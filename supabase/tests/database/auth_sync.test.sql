-- =====================================================================
-- Sincronización de rol/área desde auth.users.raw_app_meta_data (migración 09).
-- Reproduce el comportamiento real de la API de administración de Supabase
-- Auth: INSERT con solo {provider} y UPDATE posterior con role/area.
-- =====================================================================
begin;

create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;

select no_plan();

insert into auth.users (id, email, aud, role, raw_app_meta_data)
values ('00000000-0000-0000-0000-0000000000b1', 'sync@test.local', 'authenticated', 'authenticated',
        '{"provider":"email","providers":["email"]}');

select is(
  (select role || '/' || area from tfm.profiles where id = '00000000-0000-0000-0000-0000000000b1'),
  'viewer/general',
  'al insertar sin rol el perfil queda viewer/general'
);

update auth.users
   set raw_app_meta_data = raw_app_meta_data || '{"role":"editor","area":"operaciones"}'
 where id = '00000000-0000-0000-0000-0000000000b1';

select is(
  (select role || '/' || area from tfm.profiles where id = '00000000-0000-0000-0000-0000000000b1'),
  'editor/operaciones',
  'el UPDATE de app_metadata (como hace la API de admin) sincroniza rol y área'
);

update auth.users
   set raw_app_meta_data = raw_app_meta_data || '{"area":"creditos"}'
 where id = '00000000-0000-0000-0000-0000000000b1';

select is(
  (select role || '/' || area from tfm.profiles where id = '00000000-0000-0000-0000-0000000000b1'),
  'editor/creditos',
  'solo se actualizan las claves presentes'
);

update auth.users
   set raw_app_meta_data = raw_app_meta_data || '{"role":"superusuario","area":"Área Inválida"}'
 where id = '00000000-0000-0000-0000-0000000000b1';

select is(
  (select role || '/' || area from tfm.profiles where id = '00000000-0000-0000-0000-0000000000b1'),
  'editor/creditos',
  'valores inválidos se ignoran'
);

select ok(
  exists (select 1 from tfm.audit_events
          where resource_type = 'tfm.profiles' and resource_id = '00000000-0000-0000-0000-0000000000b1'),
  'el cambio de rol queda auditado'
);

select * from finish();
rollback;
