-- Configurable all-member rankings for the dedicated Rankings page.

create or replace function public.dashboard_member_rankings(
  ranking_metric text default 'average_viewers',
  ranking_platform text default 'combined',
  analysis_period text default '1m'
)
returns jsonb
language plpgsql
stable
security definer
set search_path = pg_catalog
as $$
declare
  cutoff_date date;
  result jsonb;
begin
  if ranking_metric not in ('average_viewers','peak_viewers','viewer_hours') then
    raise exception 'Invalid ranking metric';
  end if;
  if ranking_platform not in ('combined','youtube','twitch') then
    raise exception 'Invalid ranking platform';
  end if;
  if analysis_period not in ('1m','3m','6m','1y','all') then
    raise exception 'Invalid analysis period';
  end if;
  cutoff_date := case analysis_period
    when '1m' then (current_timestamp at time zone 'Asia/Taipei')::date - interval '1 month'
    when '3m' then (current_timestamp at time zone 'Asia/Taipei')::date - interval '3 months'
    when '6m' then (current_timestamp at time zone 'Asia/Taipei')::date - interval '6 months'
    when '1y' then (current_timestamp at time zone 'Asia/Taipei')::date - interval '1 year'
    else null end;

  with platform_stats as (
    select stats.vtuber_id, stats.member_name as name, stats.group_name,
           stats.platform,
           avg(stats.average_viewers) filter(where stats.snapshot_count > 3) as average_viewers,
           max(stats.peak_viewers) as peak_viewers,
           sum(stats.average_viewers * stats.observed_hours)
             filter(where stats.average_viewers is not null) as viewer_hours
      from analytics.effective_stream_stats stats
     where cutoff_date is null
        or stats.started_at >= cutoff_date::timestamp at time zone 'Asia/Taipei'
     group by stats.vtuber_id, stats.member_name, stats.group_name, stats.platform
  ), members as (
    select p.vtuber_id, max(p.name) as name, max(p.group_name) as group_name,
           max(p.average_viewers) filter(where p.platform='youtube') as youtube_average_viewers,
           max(p.average_viewers) filter(where p.platform='twitch') as twitch_average_viewers,
           max(p.peak_viewers) filter(where p.platform='youtube') as youtube_peak_viewers,
           max(p.peak_viewers) filter(where p.platform='twitch') as twitch_peak_viewers,
           max(p.viewer_hours) filter(where p.platform='youtube') as youtube_viewer_hours,
           max(p.viewer_hours) filter(where p.platform='twitch') as twitch_viewer_hours
      from platform_stats p group by p.vtuber_id
  ), scored as (
    select members.*, audience.youtube_avatar_url, audience.twitch_avatar_url,
      case ranking_metric
        when 'average_viewers' then case ranking_platform
          when 'youtube' then youtube_average_viewers
          when 'twitch' then twitch_average_viewers
          else greatest(youtube_average_viewers, twitch_average_viewers) end
        when 'peak_viewers' then case ranking_platform
          when 'youtube' then youtube_peak_viewers
          when 'twitch' then twitch_peak_viewers
          else greatest(youtube_peak_viewers, twitch_peak_viewers) end
        else case ranking_platform
          when 'youtube' then youtube_viewer_hours
          when 'twitch' then twitch_viewer_hours
          else greatest(youtube_viewer_hours, twitch_viewer_hours) end
      end as metric_value
    from members
    left join dashboard.streamer_audience audience using(vtuber_id)
  ), ranked as (
    select row_number() over(order by metric_value desc nulls last, name, vtuber_id) as rank,
           * from scored where metric_value is not null
  )
  select coalesce(jsonb_agg(to_jsonb(ranked) order by rank), '[]'::jsonb)
    into result from ranked;
  return result;
end;
$$;

revoke all on function public.dashboard_member_rankings(text,text,text) from public;
grant execute on function public.dashboard_member_rankings(text,text,text) to anon, authenticated;
