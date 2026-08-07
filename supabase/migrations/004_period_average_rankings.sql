-- Calendar-period average viewer rankings for the homepage.

create or replace function public.dashboard_period_average_rankings(
  ranking_period text default 'last_week',
  result_limit integer default 10
)
returns jsonb
language plpgsql
stable
security definer
set search_path = pg_catalog
as $$
declare
  today_date date := (current_timestamp at time zone 'Asia/Taipei')::date;
  this_week_start date;
  period_start date;
  period_end date;
  end_exclusive date;
  result jsonb;
begin
  this_week_start := today_date - extract(isodow from today_date)::integer + 1;
  case ranking_period
    when 'last_week' then
      period_start := this_week_start - 7;
      period_end := this_week_start - 1;
      end_exclusive := this_week_start;
    when 'this_week' then
      period_start := this_week_start;
      period_end := today_date;
      end_exclusive := today_date + 1;
    when 'this_month' then
      period_start := date_trunc('month', today_date)::date;
      period_end := today_date;
      end_exclusive := today_date + 1;
    else
      raise exception 'Invalid ranking period';
  end case;

  with totals as (
    select stats.vtuber_id, stats.member_name as name, stats.group_name,
           stats.platform, round(avg(stats.average_viewers))::integer as average_viewers,
           count(*) as stream_count, audience.youtube_avatar_url,
           audience.twitch_avatar_url
      from analytics.effective_stream_stats stats
      left join dashboard.streamer_audience audience on audience.vtuber_id = stats.vtuber_id
     where stats.started_at >= (period_start::timestamp at time zone 'Asia/Taipei')
       and stats.started_at < (end_exclusive::timestamp at time zone 'Asia/Taipei')
       and stats.average_viewers is not null
       and stats.snapshot_count > 3
     group by stats.vtuber_id, stats.member_name, stats.group_name,
              stats.platform, audience.youtube_avatar_url, audience.twitch_avatar_url
  ), limited_youtube as (
    select * from totals where platform='youtube'
     order by average_viewers desc, stream_count desc, name
     limit least(greatest(result_limit,1),50)
  ), limited_twitch as (
    select * from totals where platform='twitch'
     order by average_viewers desc, stream_count desc, name
     limit least(greatest(result_limit,1),50)
  )
  select jsonb_build_object(
    'period', ranking_period,
    'period_start', to_char(period_start,'YYYY-MM-DD'),
    'period_end', to_char(period_end,'YYYY-MM-DD'),
    'platforms', jsonb_build_object(
      'youtube', coalesce((select jsonb_agg(to_jsonb(limited_youtube) order by average_viewers desc,stream_count desc,name) from limited_youtube),'[]'::jsonb),
      'twitch', coalesce((select jsonb_agg(to_jsonb(limited_twitch) order by average_viewers desc,stream_count desc,name) from limited_twitch),'[]'::jsonb)
    )
  ) into result;
  return result;
end;
$$;

revoke all on function public.dashboard_period_average_rankings(text,integer) from public;
grant execute on function public.dashboard_period_average_rankings(text,integer) to anon, authenticated;
