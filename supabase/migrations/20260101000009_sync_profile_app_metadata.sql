-- =====================================================================
-- 20260101000009_sync_profile_app_metadata.sql
-- Sincroniza rol y área de tfm.profiles cuando cambia app_metadata.
--
-- Hallazgo de los tests de integración (Fase 4): la API de administración
-- de Supabase Auth INSERTA el usuario solo con {provider, providers} y
-- DESPUÉS actualiza raw_app_meta_data con el rol y el área. El trigger
-- AFTER INSERT (migración 05) nunca los veía y el perfil quedaba como
-- viewer/general.
--
-- app_metadata solo lo puede escribir service_role (Dashboard o API de
-- administración), así que es un canal seguro para asignar roles. Solo se
-- sincronizan las claves presentes y válidas.
-- =====================================================================
set search_path = public, extensions;

create or replace function tfm.sync_profile_from_app_metadata()
returns trigger
language plpgsql security definer
set search_path = ''
as $$
declare
  v_role text := lower(new.raw_app_meta_data->>'role');
  v_area text := lower(new.raw_app_meta_data->>'area');
begin
  if v_role is not null and v_role not in ('viewer', 'editor', 'admin') then
    v_role := null;
  end if;
  if v_area is not null and v_area !~ '^[a-z0-9_-]+$' then
    v_area := null;
  end if;
  if v_role is null and v_area is null then
    return new;
  end if;

  update tfm.profiles p
     set role = coalesce(v_role, p.role),
         area = coalesce(v_area, p.area)
   where p.id = new.id
     and (p.role is distinct from coalesce(v_role, p.role)
          or p.area is distinct from coalesce(v_area, p.area));
  return new;
end;
$$;

comment on function tfm.sync_profile_from_app_metadata() is
  'Propaga role/area de auth.users.raw_app_meta_data a tfm.profiles cuando service_role los modifica.';

drop trigger if exists tfm_on_auth_user_metadata_updated on auth.users;
create trigger tfm_on_auth_user_metadata_updated
  after update of raw_app_meta_data on auth.users
  for each row
  when (old.raw_app_meta_data is distinct from new.raw_app_meta_data)
  execute function tfm.sync_profile_from_app_metadata();
