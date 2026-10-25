-- =====================================================================
-- 20260101000007_match_chunks_metadata.sql
-- match_chunks devuelve también los metadatos del chunk (sección, página),
-- que el ingest-service guarda desde la Fase 3. Permite citas del tipo
-- [Fuente: Manual X, Paso 2 (pág. 3)] en lugar de "fragmento N".
--
-- Cambiar el tipo de retorno exige DROP + CREATE (no basta con REPLACE).
-- =====================================================================
set search_path = public, extensions;

drop function if exists tfm.match_chunks(extensions.vector, float, int, text);

create function tfm.match_chunks(
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
  chunk_index int,
  metadata jsonb
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
    c.chunk_index,
    coalesce(c.metadata, '{}'::jsonb)
  from tfm.chunks c
  join tfm.documents d on d.id = c.document_id
  where d.status = 'indexed'
    and (filter_area is null or d.area = filter_area)
    and 1 - (c.embedding <=> query_embedding) > match_threshold
  order by c.embedding <=> query_embedding
  limit least(greatest(match_count, 1), 200);
$$;

comment on function tfm.match_chunks(extensions.vector, float, int, text) is
  'Top-k chunks de documentos indexados por similitud coseno, con umbral, filtro de área y metadatos (sección/página).';

revoke execute on function tfm.match_chunks(extensions.vector, float, int, text) from public, anon;
grant execute on function tfm.match_chunks(extensions.vector, float, int, text)
  to authenticated, service_role;
