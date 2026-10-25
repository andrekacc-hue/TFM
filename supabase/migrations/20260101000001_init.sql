-- =====================================================================
-- 20260101000001_init.sql
-- Extensiones base. Compatible con Supabase Cloud y self-hosted.
-- =====================================================================
set search_path = public, extensions;

-- Funciones criptográficas y búsqueda difusa (trigramas)
create extension if not exists pgcrypto with schema extensions;
create extension if not exists pg_trgm with schema extensions;
