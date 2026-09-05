-- Read-only detail-page APIs. All source tables remain private.

create or replace function public.dashboard_group_members(
  requested_group text,
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
  if analysis_period not in ('1m', '3m', '6m', '1y', 'all') then
    raise exception 'Invalid analysis period';
  end if;
  cutoff_date := case analysis_period
    when '1m' then (current_timestamp at time zone 'Asia/Taipei')::date - interval '1 month'
    when '3m' then (current_timestamp at time zone 'Asia/Taipei')::date - interval '3 months'
    when '6m' then (current_timestamp at time zone 'Asia/Taipei')::date - interval '6 months'
    when '1y' then (current_timestamp at time zone 'Asia/Taipei')::date - interval '1 year'
    else null end;
  if not exists (select 1 from dashboard.effective_streamer where group_name = requested_group) then
    return null;
  end if;
  with live_status as (
    select vtuber_id, bool_or(is_live) as is_live,
           max(viewer_count) filter (where is_live) as viewers_now
      from dashboard.current_live_status group by vtuber_id
  ), members as (
    select s.vtuber_id, s.name, s.group_name, s.youtube_url, s.twitch_url,
           s.enabled, s.display_order, audience.youtube_subscribers,
           audience.youtube_count_at, audience.youtube_avatar_url,
           audience.twitch_followers, audience.twitch_count_at,
           audience.twitch_avatar_url,
           count(stats.stream_id) filter (where cutoff_date is null or stats.started_at >= cutoff_date::timestamp at time zone 'Asia/Taipei') as stream_count,
           count(stats.stream_id) filter (where stats.platform='youtube' and (cutoff_date is null or stats.started_at >= cutoff_date::timestamp at time zone 'Asia/Taipei')) as youtube_count,
           count(stats.stream_id) filter (where stats.platform='twitch' and (cutoff_date is null or stats.started_at >= cutoff_date::timestamp at time zone 'Asia/Taipei')) as twitch_count,
           max(stats.peak_viewers) filter (where cutoff_date is null or stats.started_at >= cutoff_date::timestamp at time zone 'Asia/Taipei') as peak_viewers,
           (avg(stats.peak_viewers) filter (where stats.snapshot_count > 3 and (cutoff_date is null or stats.started_at >= cutoff_date::timestamp at time zone 'Asia/Taipei')))::integer as average_peak_viewers,
           round(avg(stats.average_viewers) filter (where stats.platform='youtube' and stats.snapshot_count > 3 and (cutoff_date is null or stats.started_at >= cutoff_date::timestamp at time zone 'Asia/Taipei'))::numeric, 1) as youtube_average_viewers,
           round(avg(stats.average_viewers) filter (where stats.platform='twitch' and stats.snapshot_count > 3 and (cutoff_date is null or stats.started_at >= cutoff_date::timestamp at time zone 'Asia/Taipei'))::numeric, 1) as twitch_average_viewers,
           round(coalesce(sum(stats.average_viewers * stats.observed_hours) filter (where stats.average_viewers is not null and (cutoff_date is null or stats.started_at >= cutoff_date::timestamp at time zone 'Asia/Taipei')), 0)::numeric, 1) as viewer_hours,
           min(stats.started_at) as first_stream_at, max(stats.started_at) as latest_stream_at,
           coalesce(live.is_live, false) as is_live, live.viewers_now
      from dashboard.effective_streamer s
      left join analytics.effective_stream_stats stats on stats.vtuber_id = s.vtuber_id
      left join live_status live on live.vtuber_id = s.vtuber_id
      left join dashboard.streamer_audience audience on audience.vtuber_id = s.vtuber_id
     where s.group_name = requested_group
     group by s.vtuber_id, s.name, s.group_name, s.youtube_url, s.twitch_url,
              s.enabled, s.display_order,
              audience.youtube_subscribers, audience.youtube_count_at,
              audience.youtube_avatar_url, audience.twitch_followers,
              audience.twitch_count_at, audience.twitch_avatar_url,
              live.vtuber_id, live.is_live, live.viewers_now
  )
  select coalesce(jsonb_agg(to_jsonb(members) order by coalesce(display_order, 999999), name), '[]'::jsonb)
    into result from members;
  return result;
end;
$$;

create or replace function public.dashboard_stream_snapshots(requested_stream_id bigint)
returns jsonb
language sql
stable
security definer
set search_path = pg_catalog
as $$
  select case when stream_row.stream_id is null then null else jsonb_build_object(
    'stream', to_jsonb(stream_row),
    'snapshots', coalesce((
      select jsonb_agg(jsonb_build_object('snapshot_id', snapshot_id, 'viewer_count', viewer_count, 'captured_at', captured_at) order by captured_at, snapshot_id)
      from dashboard.stream_snapshot where stream_id = requested_stream_id
    ), '[]'::jsonb)
  ) end
  from (
    select stream.stream_id, stream.vtuber_id, member.name, member.group_name,
           stream.platform, stream.stream_url,
           coalesce(stats.title, stream.title, 'Unknown title') as title,
           coalesce(stats.category, stream.category) as category,
           coalesce(stream.started_at, stream.first_seen_at) as started_at,
           stream.ended_at, stats.observed_end_at
      from dashboard.stream stream
      join dashboard.effective_streamer member on member.vtuber_id = stream.vtuber_id
      left join analytics.effective_stream_stats stats on stats.stream_id = stream.stream_id
     where stream.stream_id = requested_stream_id
  ) stream_row;
$$;

create or replace function public.dashboard_member_month_history(
  requested_group text,
  requested_vtuber text,
  requested_month text default null
)
returns jsonb
language plpgsql
stable
security definer
set search_path = pg_catalog
as $$
declare
  profile_row jsonb;
  first_month text;
  last_month text;
  selected_month text;
  month_start date;
  month_end date;
  result jsonb;
begin
  select jsonb_build_object('vtuber_id', vtuber_id, 'name', name, 'group_name', group_name)
    into profile_row from dashboard.effective_streamer
   where group_name=requested_group and vtuber_id=requested_vtuber;
  if profile_row is null then return null; end if;
  select to_char(min(day.broadcast_day), 'YYYY-MM'), to_char(max(day.broadcast_day), 'YYYY-MM')
    into first_month, last_month
    from analytics.stream_calendar_day day
    join analytics.effective_stream_stats stats on stats.stream_id=day.stream_id
   where stats.vtuber_id=requested_vtuber;
  selected_month := coalesce(requested_month, last_month, to_char(current_timestamp at time zone 'Asia/Taipei', 'YYYY-MM'));
  if selected_month !~ '^\d{4}-(0[1-9]|1[0-2])$' then raise exception 'Month must use YYYY-MM format'; end if;
  month_start := (selected_month || '-01')::date;
  month_end := (month_start + interval '1 month - 1 day')::date;
  with calendar as (
    select day::date as day,
           count(stats.stream_id) filter (where stats.platform='youtube') as youtube,
           count(stats.stream_id) filter (where stats.platform='twitch') as twitch
      from generate_series(month_start, month_end, interval '1 day') day
      left join analytics.stream_calendar_day cd on cd.broadcast_day=day::date
      left join analytics.effective_stream_stats stats on stats.stream_id=cd.stream_id and stats.vtuber_id=requested_vtuber
     group by day::date order by day::date
  ), streams as (
    select distinct stats.stream_id, stats.platform, stats.stream_url, stats.title,
           stats.category, stats.started_at, stats.ended_at, stats.peak_viewers,
           stats.average_viewers::integer as average_viewers, stats.snapshot_count
      from analytics.effective_stream_stats stats
      join analytics.stream_calendar_day day on day.stream_id=stats.stream_id
     where stats.vtuber_id=requested_vtuber and day.broadcast_day between month_start and month_end
  )
  select jsonb_build_object(
    'profile', profile_row, 'month', selected_month,
    'available', jsonb_build_object('first', first_month, 'last', last_month),
    'calendar', coalesce((select jsonb_agg(jsonb_build_object('day', to_char(day,'YYYY-MM-DD'), 'youtube',youtube,'twitch',twitch) order by day) from calendar), '[]'::jsonb),
    'streams', coalesce((select jsonb_agg(to_jsonb(streams) order by started_at desc) from streams), '[]'::jsonb)
  ) into result;
  return result;
end;
$$;

create or replace function public.dashboard_analysis(
  requested_group text,
  requested_vtuber text default null,
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
  profile_row jsonb;
  result jsonb;
begin
  if analysis_period not in ('1m','3m','6m','1y','all') then raise exception 'Invalid analysis period'; end if;
  cutoff_date := case analysis_period
    when '1m' then (current_timestamp at time zone 'Asia/Taipei')::date - interval '1 month'
    when '3m' then (current_timestamp at time zone 'Asia/Taipei')::date - interval '3 months'
    when '6m' then (current_timestamp at time zone 'Asia/Taipei')::date - interval '6 months'
    when '1y' then (current_timestamp at time zone 'Asia/Taipei')::date - interval '1 year'
    else null end;

  if requested_vtuber is null then
    select jsonb_build_object('name', requested_group, 'group_name', requested_group,
      'member_count', count(*), 'enabled_count', count(*) filter(where enabled),
      'vtuber_id', requested_group, 'is_group', true, 'enabled', true,
      'youtube_url', null, 'twitch_url', null, 'live_url', null,
      'is_live', coalesce((select bool_or(cls.is_live) from dashboard.current_live_status cls join dashboard.effective_streamer ls on ls.vtuber_id=cls.vtuber_id where ls.group_name=requested_group),false),
      'viewers_now', coalesce((select sum(cls.viewer_count) filter(where cls.is_live) from dashboard.current_live_status cls join dashboard.effective_streamer ls on ls.vtuber_id=cls.vtuber_id where ls.group_name=requested_group),0))
      into profile_row from dashboard.effective_streamer where group_name=requested_group group by group_name;
  else
    select to_jsonb(profile) into profile_row from (
      select s.*, coalesce(bool_or(cls.is_live),false) as is_live,
             max(cls.viewer_count) filter(where cls.is_live) as viewers_now,
             max(cls.stream_url) filter(where cls.is_live) as live_url,
             audience.youtube_subscribers, audience.youtube_count_at, audience.youtube_avatar_url,
             audience.twitch_followers, audience.twitch_count_at, audience.twitch_avatar_url
        from dashboard.effective_streamer s
        left join dashboard.current_live_status cls on cls.vtuber_id=s.vtuber_id
        left join dashboard.streamer_audience audience on audience.vtuber_id=s.vtuber_id
       where s.group_name=requested_group and s.vtuber_id=requested_vtuber
       group by s.vtuber_id, s.group_name, s.name, s.youtube_url,
                s.youtube_channel_id, s.twitch_url, s.twitch_login,
                s.enabled, s.display_order, s.note, s.synced_at,
                audience.youtube_subscribers, audience.youtube_count_at,
                audience.youtube_avatar_url, audience.twitch_followers,
                audience.twitch_count_at, audience.twitch_avatar_url
    ) profile;
  end if;
  if profile_row is null then return null; end if;

  with selected as (
    select * from analytics.effective_stream_stats
     where group_name=requested_group and (requested_vtuber is null or vtuber_id=requested_vtuber)
  ), period_streams as (
    select * from selected where cutoff_date is null or started_at >= cutoff_date::timestamp at time zone 'Asia/Taipei'
  ), per_member as (
    select vtuber_id,
      avg(average_viewers) filter(where platform='youtube' and snapshot_count>3) as yt_avg,
      avg(average_viewers) filter(where platform='twitch' and snapshot_count>3) as tw_avg
    from period_streams group by vtuber_id
  ), summary as (
    select count(*) as stream_count,
      count(*) filter(where platform='youtube') as youtube_count,
      count(*) filter(where platform='twitch') as twitch_count,
      max(peak_viewers) as peak_viewers,
      max(peak_viewers) filter(where platform='youtube') as youtube_peak_viewers,
      max(peak_viewers) filter(where platform='twitch') as twitch_peak_viewers,
      (avg(peak_viewers) filter(where snapshot_count>3))::integer as average_peak_viewers,
      case when requested_vtuber is null then (select round(avg(yt_avg)::numeric,1) from per_member) else round(avg(average_viewers) filter(where platform='youtube' and snapshot_count>3)::numeric,1) end as youtube_average_viewers,
      case when requested_vtuber is null then (select round(avg(tw_avg)::numeric,1) from per_member) else round(avg(average_viewers) filter(where platform='twitch' and snapshot_count>3)::numeric,1) end as twitch_average_viewers,
      coalesce(sum(snapshot_count),0) as snapshot_count, min(started_at) as first_stream_at,
      max(started_at) as latest_stream_at,
      round(coalesce(sum(greatest(extract(epoch from (last_capture-first_capture))/3600,0)) filter(where first_capture is not null and last_capture is not null),0)::numeric,1) as observed_hours,
      round(coalesce(sum(average_viewers * greatest(extract(epoch from (last_capture-first_capture))/3600,0)) filter(where average_viewers is not null and first_capture is not null and last_capture is not null),0)::numeric,1) as viewer_hours
    from period_streams
  ), recent as (
    select stream_id, vtuber_id, member_name, platform, stream_url, title, category,
           started_at, ended_at, peak_viewers, average_viewers::integer as average_viewers,
           snapshot_count, first_capture, last_capture
      from selected order by started_at desc limit 50
  ), daily as (
    select (started_at at time zone 'Asia/Taipei')::date as day, count(*) as streams, max(peak_viewers) as peak_viewers
      from selected where requested_vtuber is not null group by day order by day
  ), categories as (
    select category, count(*) as stream_count from period_streams
     where platform='twitch' and category is not null and btrim(category)<>''
     group by category order by stream_count desc, category limit 6
  ), interval_counts as (
    select interval.minute_of_day,
      count(distinct stats.stream_id) filter(where stats.platform='youtube') as youtube,
      count(distinct stats.stream_id) filter(where stats.platform='twitch') as twitch
      from generate_series(0,1439,30) minute(minute_of_day)
      left join analytics.stream_active_interval interval on interval.minute_of_day=minute.minute_of_day
      left join period_streams stats on stats.stream_id=interval.stream_id
     group by interval.minute_of_day order by interval.minute_of_day
  ), calendar_bounds as (
    select ((current_timestamp at time zone 'Asia/Taipei')::date - extract(isodow from current_timestamp at time zone 'Asia/Taipei')::integer + 1 - 21) as first_day
  ), calendar_counts as (
    select day::date as day,
      count(distinct stats.stream_id) filter(where stats.platform='youtube') as youtube,
      count(distinct stats.stream_id) filter(where stats.platform='twitch') as twitch
      from calendar_bounds, generate_series(first_day, first_day+27, interval '1 day') day
      left join analytics.stream_calendar_day cd on cd.broadcast_day=day::date
      left join selected stats on stats.stream_id=cd.stream_id
     group by day::date order by day::date
  )
  select jsonb_build_object(
    'profile', profile_row, 'summary', (select to_jsonb(summary) from summary),
    'streams', coalesce((select jsonb_agg(to_jsonb(recent) order by started_at desc) from recent),'[]'::jsonb),
    'daily', case when requested_vtuber is null then '[]'::jsonb else coalesce((select jsonb_agg(jsonb_build_object('day',to_char(day,'YYYY-MM-DD'),'streams',streams,'peak_viewers',peak_viewers) order by day) from daily),'[]'::jsonb) end,
    'categories', coalesce((select jsonb_agg(to_jsonb(categories) order by stream_count desc,category) from categories),'[]'::jsonb),
    'active_intervals', coalesce((select jsonb_agg(to_jsonb(interval_counts) order by minute_of_day) from interval_counts),'[]'::jsonb),
    'calendar', coalesce((select jsonb_agg(jsonb_build_object('day',to_char(day,'YYYY-MM-DD'),'youtube',youtube,'twitch',twitch) order by day) from calendar_counts),'[]'::jsonb),
    'period', jsonb_build_object('value',analysis_period,'cutoff',cutoff_date,
      'latest_stream_at',(select max(coalesce(started_at,first_seen_at)) from dashboard.stream where vtuber_id=requested_vtuber))
  ) into result;
  return result;
end;
$$;

revoke all on function public.dashboard_group_members(text,text) from public;
revoke all on function public.dashboard_stream_snapshots(bigint) from public;
revoke all on function public.dashboard_member_month_history(text,text,text) from public;
revoke all on function public.dashboard_analysis(text,text,text) from public;
grant execute on function public.dashboard_group_members(text,text) to anon, authenticated;
grant execute on function public.dashboard_stream_snapshots(bigint) to anon, authenticated;
grant execute on function public.dashboard_member_month_history(text,text,text) to anon, authenticated;
grant execute on function public.dashboard_analysis(text,text,text) to anon, authenticated;
