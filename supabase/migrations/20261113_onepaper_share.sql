begin;
create extension if not exists pgcrypto with schema extensions;
-- OnePaper 폰 공유: 원문 토큰은 저장하지 않고 SHA-256만 둔다. 직접 접근은 막고 RPC로만 다룬다.
create table if not exists public.onepaper_shares (
  token_hash text primary key check (token_hash ~ '^[0-9a-f]{64}$'),
  owner uuid not null references auth.users(id) on delete cascade,
  session_id text not null,
  snapshot jsonb not null check (octet_length(snapshot::text) <= 200000),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '24 hours'
);
create index if not exists onepaper_shares_expires_idx on public.onepaper_shares (expires_at);
create index if not exists onepaper_shares_owner_idx on public.onepaper_shares (owner,created_at);
alter table public.onepaper_shares enable row level security;
revoke all on public.onepaper_shares from anon,authenticated;
grant select,insert,update,delete on public.onepaper_shares to service_role;

-- 앱이 보낸 임의 내용이 아니라 본인 계정·장치의 listening_history에 저장된 세션만 복사한다.
create or replace function public.create_onepaper_share(p_device_id uuid,p_session_id text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare
  uid uuid := auth.uid();
  doc jsonb;
  item jsonb;
  payload jsonb;
  snapshot jsonb;
  token text;
  expires timestamptz;
begin
  if uid is null or not exists (
    select 1 from public.news_demo_members where user_id=uid and enabled
  ) then raise insufficient_privilege using message='demo_access_required'; end if;
  if p_device_id is null or p_session_id is null or p_session_id !~ '^[A-Za-z0-9_-]{8,64}$' then
    raise invalid_parameter_value using message='invalid_share_request';
  end if;
  if (select count(*) from public.onepaper_shares
      where owner=uid and created_at > now() - interval '1 hour') >= 20 then
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
  insert into public.onepaper_shares(token_hash,owner,session_id,snapshot)
    values(encode(extensions.digest(token,'sha256'),'hex'),uid,p_session_id,snapshot)
    returning expires_at into expires;
  return jsonb_build_object('token',token,'expires_at',expires);
end;
$$;

-- 로그인 없이 토큰으로만 조회한다. 없거나 만료된 토큰과 잘못된 형식은 모두 null이다.
create or replace function public.read_onepaper_share(p_token text)
returns jsonb language sql stable security definer set search_path = '' as $$
  select jsonb_build_object('snapshot',s.snapshot,'expires_at',s.expires_at)
  from public.onepaper_shares s
  where p_token ~ '^[A-Za-z0-9_-]{22}$'
    and s.token_hash = encode(extensions.digest(p_token,'sha256'),'hex')
    and s.expires_at > now();
$$;

revoke all on function public.create_onepaper_share(uuid,text) from public,anon,authenticated;
revoke all on function public.read_onepaper_share(text) from public,anon,authenticated;
grant execute on function public.create_onepaper_share(uuid,text) to authenticated;
grant execute on function public.read_onepaper_share(text) to anon,authenticated;
commit;
