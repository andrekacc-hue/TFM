-- =====================================================================
-- 20260101000006_rls_policies.sql
-- Row Level Security, Storage y Realtime (esquema tfm).
--
-- Matriz de acceso (service_role tiene BYPASSRLS):
--   documents/chunks : leen su área + 'general'; editor escribe en su
--                      área; admin todo.
--   incidents        : todos leen; editor crea/edita; admin borra.
--   queries/feedback : cada usuario solo los suyos; admin lee todo.
--   golden_dataset   : todos leen; admin escribe.
--   audit_events     : solo admin lee; nadie escribe salvo triggers.
--   profiles         : cada uno el suyo; admin todos.
--
-- Los helpers se envuelven en (select ...) para que Postgres los evalúe
-- una vez por sentencia (initplan) y no por fila.
-- =====================================================================
set search_path = public, extensions;

alter table tfm.profiles        enable row level security;
alter table tfm.documents       enable row level security;
alter table tfm.chunks          enable row level security;
alter table tfm.incidents       enable row level security;
alter table tfm.queries         enable row level security;
alter table tfm.feedback        enable row level security;
alter table tfm.golden_dataset  enable row level security;
alter table tfm.audit_events    enable row level security;

-- ---------------------------------------------------------------------
-- tfm.profiles
-- ---------------------------------------------------------------------
create policy profiles_select on tfm.profiles
  for select to authenticated
  using (id = (select auth.uid()) or (select tfm.is_admin()));

-- El trigger trg_profiles_protect_privileges impide cambiar rol/área
create policy profiles_update on tfm.profiles
  for update to authenticated
  using (id = (select auth.uid()) or (select tfm.is_admin()))
  with check (id = (select auth.uid()) or (select tfm.is_admin()));

-- ---------------------------------------------------------------------
-- tfm.documents
-- ---------------------------------------------------------------------
create policy documents_select on tfm.documents
  for select to authenticated
  using (
    (select tfm.is_admin())
    or area = 'general'
    or area = (select tfm.current_app_area())
  );

create policy documents_insert on tfm.documents
  for insert to authenticated
  with check (
    (select tfm.is_editor())
    and uploaded_by = (select auth.uid())
    and ((select tfm.is_admin()) or area = (select tfm.current_app_area()))
  );

create policy documents_update on tfm.documents
  for update to authenticated
  using (
    (select tfm.is_editor())
    and ((select tfm.is_admin()) or area = (select tfm.current_app_area()))
  )
  with check (
    (select tfm.is_editor())
    and ((select tfm.is_admin()) or area = (select tfm.current_app_area()))
  );

create policy documents_delete on tfm.documents
  for delete to authenticated
  using ((select tfm.is_admin()));

-- ---------------------------------------------------------------------
-- tfm.chunks — visibles si el documento padre es visible
-- ---------------------------------------------------------------------
create policy chunks_select on tfm.chunks
  for select to authenticated
  using (exists (select 1 from tfm.documents d where d.id = chunks.document_id));

create policy chunks_admin_write on tfm.chunks
  for all to authenticated
  using ((select tfm.is_admin()))
  with check ((select tfm.is_admin()));

-- ---------------------------------------------------------------------
-- tfm.incidents
-- ---------------------------------------------------------------------
create policy incidents_select on tfm.incidents
  for select to authenticated
  using (true);

create policy incidents_insert on tfm.incidents
  for insert to authenticated
  with check ((select tfm.is_editor()) and created_by = (select auth.uid()));

create policy incidents_update on tfm.incidents
  for update to authenticated
  using ((select tfm.is_editor()))
  with check ((select tfm.is_editor()));

create policy incidents_delete on tfm.incidents
  for delete to authenticated
  using ((select tfm.is_admin()));

-- ---------------------------------------------------------------------
-- tfm.queries
-- ---------------------------------------------------------------------
create policy queries_select on tfm.queries
  for select to authenticated
  using (user_id = (select auth.uid()) or (select tfm.is_admin()));

create policy queries_insert on tfm.queries
  for insert to authenticated
  with check (user_id = (select auth.uid()));

create policy queries_delete on tfm.queries
  for delete to authenticated
  using ((select tfm.is_admin()));

-- ---------------------------------------------------------------------
-- tfm.feedback
-- ---------------------------------------------------------------------
create policy feedback_select on tfm.feedback
  for select to authenticated
  using (user_id = (select auth.uid()) or (select tfm.is_admin()));

create policy feedback_insert on tfm.feedback
  for insert to authenticated
  with check (
    user_id = (select auth.uid())
    and exists (
      select 1 from tfm.queries q
      where q.id = feedback.query_id and q.user_id = (select auth.uid())
    )
  );

create policy feedback_update on tfm.feedback
  for update to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

create policy feedback_delete on tfm.feedback
  for delete to authenticated
  using (user_id = (select auth.uid()));

-- ---------------------------------------------------------------------
-- tfm.golden_dataset
-- ---------------------------------------------------------------------
create policy golden_select on tfm.golden_dataset
  for select to authenticated
  using (true);

create policy golden_admin_write on tfm.golden_dataset
  for all to authenticated
  using ((select tfm.is_admin()))
  with check ((select tfm.is_admin()));

-- ---------------------------------------------------------------------
-- tfm.audit_events — solo lectura para admin
-- ---------------------------------------------------------------------
create policy audit_admin_select on tfm.audit_events
  for select to authenticated
  using ((select tfm.is_admin()));

-- ---------------------------------------------------------------------
-- Realtime: estado de documentos y nuevas consultas (dashboard)
-- ---------------------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    create publication supabase_realtime;
  end if;

  if not exists (select 1 from pg_publication_tables
                 where pubname = 'supabase_realtime'
                   and schemaname = 'tfm' and tablename = 'documents') then
    alter publication supabase_realtime add table tfm.documents;
  end if;

  if not exists (select 1 from pg_publication_tables
                 where pubname = 'supabase_realtime'
                   and schemaname = 'tfm' and tablename = 'queries') then
    alter publication supabase_realtime add table tfm.queries;
  end if;
exception when insufficient_privilege then
  raise warning 'No se pudo configurar la publicación supabase_realtime: %', sqlerrm;
end;
$$;

-- ---------------------------------------------------------------------
-- Storage: bucket privado "documents"  ({area}/{document_id}/{archivo})
-- ---------------------------------------------------------------------
do $$
begin
  if to_regclass('storage.buckets') is null then
    raise warning 'Esquema storage no disponible: reaplica esta migración cuando Storage esté activo.';
    return;
  end if;

  insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values (
    'documents', 'documents', false, 52428800,
    array[
      'application/pdf',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'text/markdown',
      'text/x-markdown',
      'text/plain'
    ]
  )
  on conflict (id) do nothing;

  begin
    execute $p$
      create policy tfm_documents_bucket_select on storage.objects
        for select to authenticated
        using (
          bucket_id = 'documents'
          and (
            (select tfm.is_admin())
            or (storage.foldername(name))[1] = 'general'
            or (storage.foldername(name))[1] = (select tfm.current_app_area())
          )
        )
    $p$;

    execute $p$
      create policy tfm_documents_bucket_insert on storage.objects
        for insert to authenticated
        with check (
          bucket_id = 'documents'
          and (select tfm.is_editor())
          and (
            (select tfm.is_admin())
            or (storage.foldername(name))[1] = (select tfm.current_app_area())
          )
        )
    $p$;

    execute $p$
      create policy tfm_documents_bucket_delete on storage.objects
        for delete to authenticated
        using (bucket_id = 'documents' and (select tfm.is_admin()))
    $p$;
  exception
    when insufficient_privilege then
      raise warning 'Sin privilegios para crear políticas en storage.objects (%). '
                    'El acceso seguirá funcionando vía service_role.', sqlerrm;
    when duplicate_object then
      null;
  end;
end;
$$;
