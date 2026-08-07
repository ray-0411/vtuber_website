-- Present unnumbered Groups as `other` without mutating source rows.

create or replace view dashboard.effective_streamer as
select s.vtuber_id,
       case when s.group_name = 'other' or settings.display_order is not null
            then s.group_name else 'other' end as group_name,
       s.name, s.youtube_url, s.youtube_channel_id, s.twitch_url, s.twitch_login,
       s.enabled, s.display_order, s.note, s.synced_at
from dashboard.streamer s
left join dashboard.group_settings settings on settings.group_name = s.group_name;

create or replace view analytics.effective_stream_stats as
select stats.stream_id, stats.vtuber_id, member.group_name,
       stats.member_name, stats.platform, stats.stream_url, stats.title,
       stats.category, stats.started_at, stats.ended_at, stats.observed_end_at,
       stats.peak_viewers, stats.average_viewers, stats.snapshot_count,
       stats.first_capture, stats.last_capture, stats.observed_hours
from analytics.stream_stats stats
join dashboard.effective_streamer member on member.vtuber_id = stats.vtuber_id;

revoke all on dashboard.effective_streamer from anon, authenticated;
revoke all on analytics.effective_stream_stats from anon, authenticated;
