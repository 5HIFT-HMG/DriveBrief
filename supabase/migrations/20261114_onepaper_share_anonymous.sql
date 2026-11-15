begin;
-- 로그인 화면 없이 OnePaper 공유: 앱이 만든 Supabase 익명 세션도 본인 청취 기록 저장/조회와 공유 생성을 허용한다.
-- 공유 뉴스(read_news)는 기존대로 허용 목록 사용자만 조회한다.
create or replace function public.history_user_allowed()
returns boolean language sql stable security definer set search_path = '' as $$
  select auth.uid() is not null and (
    coalesce((auth.jwt()->>'is_anonymous')::boolean, false)
    or exists (select 1 from public.news_demo_members where user_id = auth.uid() and enabled)
  );
$$;
revoke all on function public.history_user_allowed() from public,anon,authenticated;

alter table public.onepaper_shares add column if not exists anonymous boolean not null default false;
create index if not exists onepaper_shares_anonymous_idx on public.onepaper_shares (created_at) where anonymous;

create or replace function public.save_listening_history(p_device_id uuid,p_revision bigint,p_document text)
returns bigint language plpgsql security definer set search_path = '' as $$
declare current_revision bigint;
begin
  if not public.history_user_allowed() then
    raise insufficient_privilege using message='demo_access_required';
  end if;
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
  if not public.history_user_allowed() then
    raise insufficient_privilege using message='demo_access_required';
  end if;
  return (select jsonb_build_object('revision',revision,'document',document)
    from public.listening_history where user_id=auth.uid() and device_id=p_device_id);
end;
$$;

-- 본인 계정·장치의 listening_history에 저장된 세션만 복사한다. 익명 사용자 전체에도 시간당 상한을 둔다.
create or replace function public.create_onepaper_share(p_device_id uuid,p_session_id text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare
  uid uuid := auth.uid();
  is_anonymous boolean := coalesce((auth.jwt()->>'is_anonymous')::boolean, false);
  doc jsonb;
  item jsonb;
  payload jsonb;
  snapshot jsonb;
  token text;
  expires timestamptz;
begin
  if not public.history_user_allowed() then
    raise insufficient_privilege using message='demo_access_required';
  end if;
  if p_device_id is null or p_session_id is null or p_session_id !~ '^[A-Za-z0-9_-]{8,64}$' then
    raise invalid_parameter_value using message='invalid_share_request';
  end if;
  if (select count(*) from public.onepaper_shares
      where owner=uid and created_at > now() - interval '1 hour') >= 20
     or (is_anonymous and (select count(*) from public.onepaper_shares
      where anonymous and created_at > now() - interval '1 hour') >= 300) then
    raise sqlstate 'PT429' using message='rate_limited';
  end if;

  select document::jsonb into doc from public.listening_history where user_id=uid and device_id=p_device_id;
  select s into item from jsonb_array_elements(coalesce(doc->'sessions','[]'::jsonb)) s
    where s->>'session_id'=p_session_id limit 1;
  if item is null then raise sqlstate 'PT409' using message='session_not_synced'; end if;

  payload := (item->>'payload')::jsonb;
  if payload->>'schema_version' is distinct from 'approved-briefing-v1'
     or jsonb_typeof(payload->'articles') is distinct from 'array'
     or jsonb_array_length(payload->'articles') not between 1 and 10
     or jsonb_typeof(item->'progress') is distinct from 'array'
     or jsonb_array_length(item->'progress') <> jsonb_array_length(payload->'articles')
     or exists (select 1 from jsonb_array_elements(item->'progress') p
       where p->>'status' is null or p->>'status' not in ('UNHEARD','PLAYING','COMPLETED','SKIPPED','INTERRUPTED')) then
    raise invalid_parameter_value using message='invalid_snapshot';
  end if;

  -- 공유에 필요한 필드만 남긴다. 사용자/장치 ID, 커서, 중단 사유는 넣지 않는다.
  select jsonb_build_object(
    'schema','onepaper-share-v1',
    'session_label',left(p_session_id,8),
    'created_at',(item->>'created_at')::bigint,
    'ended',coalesce((item->>'ended')::boolean,false),
    'fully_completed',coalesce((item->>'ended')::boolean,false) and bool_and(p->>'status'='COMPLETED'),
    'length_option',payload->>'length_option',
    'articles',jsonb_agg(jsonb_build_object(
      'title',a->>'title','source',a->>'source','one_line',a->>'one_line','detail',a->>'detail',
      'source_url',case when a->>'source_url' ~* '^https?://[^\s]+$' then a->>'source_url' end,
      'sentence_count',jsonb_array_length(a->'tts_sentences'),
      'approved_sentence_count',coalesce((a->>'approved_sentence_count')::int,jsonb_array_length(a->'tts_sentences')),
      'status',p->>'status',
      'completed_count',jsonb_array_length(p->'completed'),
      'skipped_count',jsonb_array_length(p->'skipped')
    ) order by i))
  into snapshot
  from jsonb_array_elements(payload->'articles') with ordinality as x(a,i)
  join jsonb_array_elements(item->'progress') with ordinality as y(p,j) on i=j;
  if octet_length(snapshot::text) > 200000 then raise invalid_parameter_value using message='too_large'; end if;

  delete from public.onepaper_shares where expires_at < now();
  token := rtrim(translate(encode(extensions.gen_random_bytes(16),'base64'),'+/','-_'),'=');
  insert into public.onepaper_shares(token_hash,owner,session_id,snapshot,anonymous)
    values(encode(extensions.digest(token,'sha256'),'hex'),uid,p_session_id,snapshot,is_anonymous)
    returning expires_at into expires;
  return jsonb_build_object('token',token,'expires_at',expires);
end;
$$;

revoke all on function public.save_listening_history(uuid,bigint,text) from public,anon,authenticated;
revoke all on function public.read_listening_history(uuid) from public,anon,authenticated;
revoke all on function public.create_onepaper_share(uuid,text) from public,anon,authenticated;
grant execute on function public.save_listening_history(uuid,bigint,text) to authenticated;
grant execute on function public.read_listening_history(uuid) to authenticated;
grant execute on function public.create_onepaper_share(uuid,text) to authenticated;
commit;
