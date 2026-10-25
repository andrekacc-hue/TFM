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
