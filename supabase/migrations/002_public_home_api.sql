-- Read-only homepage API. Raw dashboard/analytics tables remain private.

create or replace function public.dashboard_overview()
returns jsonb
language sql
stable
security definer
set search_path = pg_catalog
as $$
  select jsonb_build_object(
    'streamers', (select count(*) from dashboard.effective_streamer where enabled),
    'live_now', (select count(*) from dashboard.current_live_status where is_live),
    'streams', (select count(*) from dashboard.stream),
    'viewers_now', (select coalesce(sum(viewer_count), 0) from dashboard.current_live_status where is_live),
    'last_checked_at', (select max(last_checked_at) from dashboard.current_live_status),
    'platforms', coalesce((
      select jsonb_agg(jsonb_build_object('platform', platform, 'count', stream_count) order by stream_count desc)
      from (select platform, count(*) as stream_count from dashboard.stream group by platform) totals
    ), '[]'::jsonb)
  );
$$;

create or replace function public.dashboard_live()
returns jsonb
language sql
stable
security definer
set search_path = pg_catalog
as $$
  select coalesce(jsonb_agg(to_jsonb(live_row) order by viewer_count desc nulls last, name), '[]'::jsonb)
  from (
    select cls.vtuber_id, s.name, s.group_name, cls.platform,
           cls.viewer_count, cls.stream_url,
           (select min(snapshot.captured_at)
              from dashboard.stream_snapshot snapshot
             where snapshot.stream_id = cls.stream_id) as started_at,
           coalesce(st.title, stream.title, 'Unknown title') as title,
           audience.youtube_avatar_url, audience.twitch_avatar_url
      from dashboard.current_live_status cls
      join dashboard.effective_streamer s on s.vtuber_id = cls.vtuber_id
      left join dashboard.stream stream on stream.stream_id = cls.stream_id
      left join dashboard.stream_title st on st.title_id = cls.title_id
      left join dashboard.streamer_audience audience on audience.vtuber_id = cls.vtuber_id
     where cls.is_live
  ) live_row;
$$;

create or replace function public.dashboard_weekly_rankings(result_limit integer default 10)
returns jsonb
language sql
stable
security definer
set search_path = pg_catalog
as $$
  with bounds as (
    select (current_timestamp at time zone 'Asia/Taipei')::date
           - extract(isodow from current_timestamp at time zone 'Asia/Taipei')::integer + 1 as this_week
  ), ranked as (
    select stats.vtuber_id, stats.member_name as name, stats.group_name,
           stats.platform, stats.stream_url, stats.title, stats.started_at,
           round(stats.average_viewers)::integer as average_viewers,
           stats.peak_viewers, audience.youtube_avatar_url,
           audience.twitch_avatar_url,
           row_number() over (partition by stats.platform order by stats.average_viewers desc, stats.peak_viewers desc, stats.started_at desc) as average_rank,
           row_number() over (partition by stats.platform order by stats.peak_viewers desc, stats.average_viewers desc, stats.started_at desc) as peak_rank,
           row_number() over (partition by stats.platform, stats.vtuber_id order by stats.average_viewers desc, stats.peak_viewers desc, stats.started_at desc) as average_member_rank,
           row_number() over (partition by stats.platform, stats.vtuber_id order by stats.peak_viewers desc, stats.average_viewers desc, stats.started_at desc) as peak_member_rank
      from analytics.effective_stream_stats stats
      cross join bounds
      left join dashboard.streamer_audience audience on audience.vtuber_id = stats.vtuber_id
     where stats.started_at >= ((bounds.this_week - 7)::timestamp at time zone 'Asia/Taipei')
       and stats.started_at < (bounds.this_week::timestamp at time zone 'Asia/Taipei')
       and stats.average_viewers is not null
       and stats.snapshot_count >= 5
  ), limits as (
    select least(greatest(result_limit, 1), 50) as amount
  )
  select jsonb_build_object(
    'week_start', to_char(bounds.this_week - interval '7 days', 'YYYY-MM-DD'),
    'week_end', to_char(bounds.this_week - interval '1 day', 'YYYY-MM-DD'),
    'platforms', jsonb_build_object(
      'youtube', jsonb_build_object(
        'average_viewers', jsonb_build_object(
          'streams', coalesce((select jsonb_agg(to_jsonb(x) - array['average_rank','peak_rank','average_member_rank','peak_member_rank'] order by average_rank) from ranked x, limits where platform='youtube' and average_rank <= limits.amount), '[]'::jsonb),
          'unique_streams', coalesce((select jsonb_agg(to_jsonb(x) - array['average_rank','peak_rank','average_member_rank','peak_member_rank'] order by average_viewers desc, peak_viewers desc, started_at desc) from (select ranked.* from ranked, limits where platform='youtube' and average_member_rank=1 order by average_viewers desc, peak_viewers desc, started_at desc limit (select amount from limits)) x), '[]'::jsonb)
        ),
        'peak_viewers', jsonb_build_object(
          'streams', coalesce((select jsonb_agg(to_jsonb(x) - array['average_rank','peak_rank','average_member_rank','peak_member_rank'] order by peak_rank) from ranked x, limits where platform='youtube' and peak_rank <= limits.amount), '[]'::jsonb),
          'unique_streams', coalesce((select jsonb_agg(to_jsonb(x) - array['average_rank','peak_rank','average_member_rank','peak_member_rank'] order by peak_viewers desc, average_viewers desc, started_at desc) from (select ranked.* from ranked, limits where platform='youtube' and peak_member_rank=1 order by peak_viewers desc, average_viewers desc, started_at desc limit (select amount from limits)) x), '[]'::jsonb)
        )
      ),
      'twitch', jsonb_build_object(
        'average_viewers', jsonb_build_object(
          'streams', coalesce((select jsonb_agg(to_jsonb(x) - array['average_rank','peak_rank','average_member_rank','peak_member_rank'] order by average_rank) from ranked x, limits where platform='twitch' and average_rank <= limits.amount), '[]'::jsonb),
          'unique_streams', coalesce((select jsonb_agg(to_jsonb(x) - array['average_rank','peak_rank','average_member_rank','peak_member_rank'] order by average_viewers desc, peak_viewers desc, started_at desc) from (select ranked.* from ranked, limits where platform='twitch' and average_member_rank=1 order by average_viewers desc, peak_viewers desc, started_at desc limit (select amount from limits)) x), '[]'::jsonb)
        ),
        'peak_viewers', jsonb_build_object(
          'streams', coalesce((select jsonb_agg(to_jsonb(x) - array['average_rank','peak_rank','average_member_rank','peak_member_rank'] order by peak_rank) from ranked x, limits where platform='twitch' and peak_rank <= limits.amount), '[]'::jsonb),
          'unique_streams', coalesce((select jsonb_agg(to_jsonb(x) - array['average_rank','peak_rank','average_member_rank','peak_member_rank'] order by peak_viewers desc, average_viewers desc, started_at desc) from (select ranked.* from ranked, limits where platform='twitch' and peak_member_rank=1 order by peak_viewers desc, average_viewers desc, started_at desc limit (select amount from limits)) x), '[]'::jsonb)
        )
      )
    )
  ) from bounds;
$$;

create or replace function public.dashboard_monthly_average_rankings(result_limit integer default 10)
returns jsonb
language sql
stable
security definer
set search_path = pg_catalog
as $$
  with bounds as (
    select date_trunc('month', current_timestamp at time zone 'Asia/Taipei')::date as month_end
  ), totals as (
    select stats.vtuber_id, stats.member_name as name, stats.group_name,
           stats.platform, round(avg(stats.average_viewers))::integer as average_viewers,
           count(*) as stream_count, audience.youtube_avatar_url,
           audience.twitch_avatar_url
      from analytics.effective_stream_stats stats
      cross join bounds
      left join dashboard.streamer_audience audience on audience.vtuber_id = stats.vtuber_id
     where stats.started_at >= ((bounds.month_end - interval '1 month')::timestamp at time zone 'Asia/Taipei')
       and stats.started_at < (bounds.month_end::timestamp at time zone 'Asia/Taipei')
       and stats.average_viewers is not null
       and stats.snapshot_count > 3
     group by stats.vtuber_id, stats.member_name, stats.group_name,
              stats.platform, audience.youtube_avatar_url, audience.twitch_avatar_url
  ), limits as (
    select least(greatest(result_limit, 1), 50) as amount
  )
  select jsonb_build_object(
    'month_start', to_char(bounds.month_end - interval '1 month', 'YYYY-MM-DD'),
    'month_end', to_char(bounds.month_end - interval '1 day', 'YYYY-MM-DD'),
    'platforms', jsonb_build_object(
      'youtube', coalesce((select jsonb_agg(to_jsonb(x) order by average_viewers desc, stream_count desc, name) from (select totals.* from totals, limits where platform='youtube' order by average_viewers desc, stream_count desc, name limit (select amount from limits)) x), '[]'::jsonb),
      'twitch', coalesce((select jsonb_agg(to_jsonb(x) order by average_viewers desc, stream_count desc, name) from (select totals.* from totals, limits where platform='twitch' order by average_viewers desc, stream_count desc, name limit (select amount from limits)) x), '[]'::jsonb)
    )
  ) from bounds;
$$;

create or replace function public.dashboard_groups()
returns jsonb
language sql
stable
security definer
set search_path = pg_catalog
as $$
  with member_stats as (
    select s.vtuber_id, s.group_name, s.enabled,
           audience.youtube_subscribers, audience.twitch_followers,
           count(distinct stream.stream_id) as stream_count
      from dashboard.effective_streamer s
      left join dashboard.stream stream on stream.vtuber_id = s.vtuber_id
      left join dashboard.streamer_audience audience on audience.vtuber_id = s.vtuber_id
     group by s.vtuber_id, s.group_name, s.enabled,
              audience.youtube_subscribers, audience.twitch_followers
  ), live_status as (
    select vtuber_id, bool_or(is_live) as is_live
      from dashboard.current_live_status group by vtuber_id
  ), groups as (
    select ms.group_name, settings.display_order, count(*) as member_count,
           count(*) filter (where ms.enabled) as enabled_count,
           sum(coalesce(ms.youtube_subscribers, 0)) as youtube_subscribers,
           sum(coalesce(ms.twitch_followers, 0)) as twitch_followers,
           sum(ms.stream_count) as stream_count,
           coalesce(bool_or(ls.is_live), false) as has_live
      from member_stats ms
      left join live_status ls on ls.vtuber_id = ms.vtuber_id
      left join dashboard.group_settings settings on settings.group_name = ms.group_name
     group by ms.group_name, settings.display_order
  )
  select coalesce(jsonb_agg(to_jsonb(groups) order by (display_order is null), display_order, group_name), '[]'::jsonb)
  from groups;
$$;

revoke all on function public.dashboard_overview() from public;
revoke all on function public.dashboard_live() from public;
revoke all on function public.dashboard_weekly_rankings(integer) from public;
revoke all on function public.dashboard_monthly_average_rankings(integer) from public;
revoke all on function public.dashboard_groups() from public;

grant execute on function public.dashboard_overview() to anon, authenticated;
grant execute on function public.dashboard_live() to anon, authenticated;
grant execute on function public.dashboard_weekly_rankings(integer) to anon, authenticated;
grant execute on function public.dashboard_monthly_average_rankings(integer) to anon, authenticated;
grant execute on function public.dashboard_groups() to anon, authenticated;
