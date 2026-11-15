begin;
create table if not exists public.news_demo_members (
  user_id uuid primary key references auth.users(id) on delete cascade,
  enabled boolean not null default true
);
alter table public.news_demo_members enable row level security;
revoke all on public.news_demo_members from anon, authenticated;
grant select,insert,update,delete on public.news_demo_members to service_role;

create or replace function public.read_news(
  p_categories text[] default null,
  p_offset integer default 0,
  p_limit integer default 20
)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare result jsonb;
begin
  if auth.uid() is null or not exists (
    select 1 from public.news_demo_members where user_id = auth.uid() and enabled
  ) then
    raise insufficient_privilege using message = 'demo_access_required';
  end if;
  if p_offset is null or p_offset < 0 or p_limit is null or p_limit < 1 or p_limit > 100
     or (p_categories is not null and not p_categories <@ array['경제','사회','정치','IT','스포츠']::text[]) then
    raise invalid_parameter_value using message = 'invalid_news_filter';
  end if;
  with grouped as (
    select a.url,a.title,a.description,a.published_at,
      array_agg(distinct m.category order by m.category) as categories,
      array_agg(distinct m.source order by m.source) as sources
    from public.news_articles a join public.news_memberships m using (url)
    where p_categories is null or m.category = any(p_categories)
    group by a.url
  ), dedup as (
    select *, row_number() over (
      partition by lower(regexp_replace(title,'\s+',' ','g'))
      order by published_at desc,url
    ) as title_rank from grouped
  ), candidates as (
    select * from dedup where title_rank = 1
  ), category_ranks as (
    select url,category,row_number() over (
      partition by category order by published_at desc,url
    ) as category_rank from candidates cross join lateral unnest(categories) as expanded(category)
  ), available as (
    select * from candidates where url in (select url from category_ranks where category_rank <= 100)
  ), page as (
    select * from available order by published_at desc,url limit p_limit offset p_offset
  )
  select jsonb_build_object(
    'schema_version','news-candidates-v1',
    'total_candidates',(select count(*) from candidates),
    'available_count',(select count(*) from available),
    'offset',p_offset,'limit',p_limit,
    'has_more',p_offset::bigint + p_limit < (select count(*) from available),
    'event_dedup_status','not_performed',
    'articles',coalesce((select jsonb_agg(jsonb_build_object(
      'article_id','rss_' || substr(encode(sha256(convert_to(url,'UTF8')),'hex'),1,24),
      'title',title,'description',description,'source_url',url,
      'category',categories[1],'categories',categories,'source',sources[1],'sources',sources,
      'published_at',published_at,'content_level','rss_description',
      'summary_status','not_available','ai_eligible',false,
      'ai_blockers',jsonb_build_array('full_text_missing','external_ai_permission_unverified','reuse_permission_unverified')
    ) order by published_at desc,url) from page),'[]'::jsonb)
  ) into result;
  return result;
end;
$$;
revoke all on function public.read_news(text[],integer,integer) from public,anon,authenticated;
grant execute on function public.read_news(text[],integer,integer) to authenticated;
commit;
