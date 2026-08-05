-- Calendar-period single-stream rankings for the homepage.

create or replace function public.dashboard_stream_rankings(
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

  with ranked as (
    select stats.vtuber_id, stats.member_name as name, stats.group_name,
           stats.platform, stats.stream_url, stats.title, stats.started_at,
           round(stats.average_viewers)::integer as average_viewers,
           stats.peak_viewers, audience.youtube_avatar_url,
           audience.twitch_avatar_url,
           row_number() over (partition by stats.platform order by stats.average_viewers desc, stats.peak_viewers desc, stats.started_at desc) as average_rank,
           row_number() over (partition by stats.platform order by stats.peak_viewers desc, stats.average_viewers desc, stats.started_at desc) as peak_rank,
           row_number() over (partition by stats.platform, stats.vtuber_id order by stats.average_viewers desc, stats.peak_viewers desc, stats.started_at desc) as average_member_rank,
           row_number() over (partition by stats.platform, stats.vtuber_id order by stats.peak_viewers desc, stats.average_viewers desc, stats.started_at desc) as peak_member_rank
      from analytics.stream_stats stats
      left join dashboard.streamer_audience audience on audience.vtuber_id=stats.vtuber_id
     where stats.started_at >= (period_start::timestamp at time zone 'Asia/Taipei')
       and stats.started_at < (end_exclusive::timestamp at time zone 'Asia/Taipei')
       and stats.average_viewers is not null
       and stats.snapshot_count >= 5
  ), limits as (
    select least(greatest(result_limit,1),50) as amount
  )
  select jsonb_build_object(
    'period', ranking_period,
    'period_start', to_char(period_start,'YYYY-MM-DD'),
    'period_end', to_char(period_end,'YYYY-MM-DD'),
    'platforms', jsonb_build_object(
      'youtube', jsonb_build_object(
        'average_viewers', jsonb_build_object(
          'streams', coalesce((select jsonb_agg(to_jsonb(x)-array['average_rank','peak_rank','average_member_rank','peak_member_rank'] order by average_rank) from ranked x,limits where platform='youtube' and average_rank<=limits.amount),'[]'::jsonb),
          'unique_streams', coalesce((select jsonb_agg(to_jsonb(x)-array['average_rank','peak_rank','average_member_rank','peak_member_rank'] order by average_viewers desc,peak_viewers desc,started_at desc) from (select ranked.* from ranked,limits where platform='youtube' and average_member_rank=1 order by average_viewers desc,peak_viewers desc,started_at desc limit (select amount from limits)) x),'[]'::jsonb)
        ),
        'peak_viewers', jsonb_build_object(
          'streams', coalesce((select jsonb_agg(to_jsonb(x)-array['average_rank','peak_rank','average_member_rank','peak_member_rank'] order by peak_rank) from ranked x,limits where platform='youtube' and peak_rank<=limits.amount),'[]'::jsonb),
          'unique_streams', coalesce((select jsonb_agg(to_jsonb(x)-array['average_rank','peak_rank','average_member_rank','peak_member_rank'] order by peak_viewers desc,average_viewers desc,started_at desc) from (select ranked.* from ranked,limits where platform='youtube' and peak_member_rank=1 order by peak_viewers desc,average_viewers desc,started_at desc limit (select amount from limits)) x),'[]'::jsonb)
        )
      ),
      'twitch', jsonb_build_object(
        'average_viewers', jsonb_build_object(
          'streams', coalesce((select jsonb_agg(to_jsonb(x)-array['average_rank','peak_rank','average_member_rank','peak_member_rank'] order by average_rank) from ranked x,limits where platform='twitch' and average_rank<=limits.amount),'[]'::jsonb),
          'unique_streams', coalesce((select jsonb_agg(to_jsonb(x)-array['average_rank','peak_rank','average_member_rank','peak_member_rank'] order by average_viewers desc,peak_viewers desc,started_at desc) from (select ranked.* from ranked,limits where platform='twitch' and average_member_rank=1 order by average_viewers desc,peak_viewers desc,started_at desc limit (select amount from limits)) x),'[]'::jsonb)
        ),
        'peak_viewers', jsonb_build_object(
          'streams', coalesce((select jsonb_agg(to_jsonb(x)-array['average_rank','peak_rank','average_member_rank','peak_member_rank'] order by peak_rank) from ranked x,limits where platform='twitch' and peak_rank<=limits.amount),'[]'::jsonb),
          'unique_streams', coalesce((select jsonb_agg(to_jsonb(x)-array['average_rank','peak_rank','average_member_rank','peak_member_rank'] order by peak_viewers desc,average_viewers desc,started_at desc) from (select ranked.* from ranked,limits where platform='twitch' and peak_member_rank=1 order by peak_viewers desc,average_viewers desc,started_at desc limit (select amount from limits)) x),'[]'::jsonb)
        )
      )
    )
  ) into result;
  return result;
end;
$$;

revoke all on function public.dashboard_stream_rankings(text,integer) from public;
grant execute on function public.dashboard_stream_rankings(text,integer) to anon, authenticated;
