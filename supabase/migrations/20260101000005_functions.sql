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
