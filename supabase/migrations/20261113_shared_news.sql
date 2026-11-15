begin;
create table if not exists public.news_articles (
  url text primary key,
  title text not null,
  description text not null,
  published_at timestamptz not null,
  first_seen timestamptz not null,
  last_seen timestamptz not null
);
create table if not exists public.news_memberships (
  url text not null references public.news_articles(url) on delete cascade,
  category text not null check (category in ('경제','사회','정치','IT','스포츠')),
  source text not null,
  primary key (url,category,source)
);
create index if not exists news_published_at_idx on public.news_articles (published_at desc);
alter table public.news_articles enable row level security;
alter table public.news_memberships enable row level security;
revoke all on public.news_articles, public.news_memberships from anon, authenticated;
grant select,insert,update,delete on public.news_articles, public.news_memberships to service_role;
create or replace function public.sync_news(p_articles jsonb, p_memberships jsonb)
returns integer language plpgsql security invoker set search_path = '' as $$
declare uploaded integer;
begin
  insert into public.news_articles
  select * from jsonb_populate_recordset(null::public.news_articles, p_articles)
  on conflict (url) do update set title=excluded.title, description=excluded.description,
    published_at=excluded.published_at,
    first_seen=least(public.news_articles.first_seen,excluded.first_seen),
    last_seen=greatest(public.news_articles.last_seen,excluded.last_seen)
  where excluded.last_seen >= public.news_articles.last_seen;
  insert into public.news_memberships
  select * from jsonb_populate_recordset(null::public.news_memberships, p_memberships)
  on conflict do nothing;
  uploaded := jsonb_array_length(p_articles);
  return uploaded;
end;
$$;
revoke all on function public.sync_news(jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.sync_news(jsonb,jsonb) to service_role;
commit;
