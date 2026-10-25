-- =====================================================================
-- 20260101000002_pgvector.sql
-- pgvector: tipo vector + índices HNSW para búsqueda semántica.
-- Se instala en el esquema "extensions" (convención de Supabase); los
-- objetos que lo usan declaran search_path con "extensions".
-- =====================================================================
set search_path = public, extensions;

create extension if not exists vector with schema extensions;

comment on extension vector is
  'Embeddings de 384 dimensiones (paraphrase-multilingual-MiniLM-L12-v2) con distancia coseno.';
