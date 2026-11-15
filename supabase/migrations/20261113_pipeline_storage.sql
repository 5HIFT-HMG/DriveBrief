begin;
create table if not exists public.briefing_review_records (
  namespace text not null check (namespace in ('fictional','real')),
  id text not null,
  record text not null,
  draft text not null,
  provenance text not null,
  decision text not null check (decision in ('needs_review','approved','rejected')),
  approval text,
  revision text not null,
  updated_at timestamptz not null default now(),
  primary key (namespace,id)
);
alter table public.briefing_review_records enable row level security;
revoke all on public.briefing_review_records from anon,authenticated;
grant select,insert,update,delete on public.briefing_review_records to service_role;
create table if not exists public.listening_history (
  user_id uuid not null references auth.users(id) on delete cascade,
  device_id uuid not null,
  revision bigint not null check (revision >= 1),
  document text not null check (octet_length(document) <= 1000000),
  updated_at timestamptz not null default now(),
  primary key (user_id,device_id)
);
alter table public.listening_history enable row level security;
revoke all on public.listening_history from anon,authenticated;
grant select,insert,update,delete on public.listening_history to service_role;
create or replace function public.save_listening_history(p_device_id uuid,p_revision bigint,p_document text)
returns bigint language plpgsql security definer set search_path = '' as $$
declare current_revision bigint;
begin
  if auth.uid() is null or not exists (
    select 1 from public.news_demo_members where user_id=auth.uid() and enabled
  ) then raise insufficient_privilege using message='demo_access_required'; end if;
  if p_device_id is null or p_revision is null or p_revision < 1 or p_document is null
     or octet_length(p_document)>1000000
     or (p_document::jsonb)->>'schema' is distinct from '1'
     or jsonb_typeof((p_document::jsonb)->'sessions') is distinct from 'array'
     or jsonb_array_length((p_document::jsonb)->'sessions')>20 then
    raise invalid_parameter_value using message='invalid_history';
  end if;
  insert into public.listening_history(user_id,device_id,revision,document)
  values(auth.uid(),p_device_id,p_revision,p_document)
  on conflict(user_id,device_id) do update set revision=excluded.revision,
    document=excluded.document,updated_at=now()
  where excluded.revision>public.listening_history.revision;
  select revision into current_revision from public.listening_history
    where user_id=auth.uid() and device_id=p_device_id;
  if current_revision=p_revision and exists (
    select 1 from public.listening_history where user_id=auth.uid() and device_id=p_device_id and document<>p_document
  ) then raise invalid_parameter_value using message='history_revision_conflict'; end if;
  return current_revision;
end;
$$;
create or replace function public.read_listening_history(p_device_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if auth.uid() is null or not exists (
    select 1 from public.news_demo_members where user_id=auth.uid() and enabled
  ) then raise insufficient_privilege using message='demo_access_required'; end if;
  return (select jsonb_build_object('revision',revision,'document',document)
    from public.listening_history where user_id=auth.uid() and device_id=p_device_id);
end;
$$;
revoke all on function public.save_listening_history(uuid,bigint,text) from public,anon,authenticated;
revoke all on function public.read_listening_history(uuid) from public,anon,authenticated;
grant execute on function public.save_listening_history(uuid,bigint,text) to authenticated;
grant execute on function public.read_listening_history(uuid) to authenticated;
commit;
