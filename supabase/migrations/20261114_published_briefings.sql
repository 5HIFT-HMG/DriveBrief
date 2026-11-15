begin;
-- Mac 파이프라인이 사람 승인을 거친 기사로 편성한 브리핑을 길이별로 게시한다.
-- namespace는 실제 기사(real)인지 가상 검증 자료(fictional)인지 나타낸다.
-- 쓰기는 서버 키(service_role)만, 앱은 read_published_briefing RPC로만 읽는다.
create table if not exists public.published_briefings (
  length_option text primary key check (length_option in ('짧게','중간','길게')),
  namespace text not null check (namespace in ('real','fictional')),
  briefing jsonb not null check (octet_length(briefing::text) <= 500000),
  revision text not null,
  published_at timestamptz not null default now()
);
alter table public.published_briefings enable row level security;
revoke all on public.published_briefings from anon,authenticated;
grant select,insert,update,delete on public.published_briefings to service_role;

-- 익명 세션 또는 허용 목록 사용자만 읽는다. 게시된 것이 없으면 null.
create or replace function public.read_published_briefing(p_length text)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.history_user_allowed() then
    raise insufficient_privilege using message='demo_access_required';
  end if;
  if p_length is null or p_length not in ('짧게','중간','길게') then
    raise invalid_parameter_value using message='invalid_length';
  end if;
  return (select briefing from public.published_briefings where length_option = p_length);
end;
$$;
revoke all on function public.read_published_briefing(text) from public,anon,authenticated;
grant execute on function public.read_published_briefing(text) to authenticated;
commit;
