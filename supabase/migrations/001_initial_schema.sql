-- Private source data. Do not add these schemas to the Supabase Data API.
create schema if not exists dashboard;
create schema if not exists analytics;

create table if not exists dashboard.streamer (
    vtuber_id text primary key,
    group_name text not null,
    name text not null,
    youtube_url text,
    youtube_channel_id text,
    twitch_url text,
    twitch_login text,
    enabled boolean not null,
    display_order integer,
    note text,
    synced_at timestamptz not null
);

create index if not exists idx_streamer_group
    on dashboard.streamer (group_name, display_order, name);

create table if not exists dashboard.group_settings (
    group_name text primary key,
    display_order integer,
    note text
);

create table if not exists dashboard.stream_title (
    title_id bigint primary key,
    title text not null unique
);

create table if not exists dashboard.stream_category (
    category_id bigint primary key,
    category text not null unique
);

create table if not exists dashboard.stream_tags (
    tags_id bigint primary key,
    tags text not null unique
);

create table if not exists dashboard.stream (
    stream_id bigint primary key,
    vtuber_id text not null references dashboard.streamer (vtuber_id),
    platform text not null check (platform in ('youtube', 'twitch')),
    platform_stream_id text not null,
    stream_url text,
    title text,
    category text,
    tags text,
    started_at timestamptz,
    ended_at timestamptz,
    first_seen_at timestamptz not null,
    last_seen_at timestamptz not null,
    created_at timestamptz not null,
    updated_at timestamptz not null,
    unique (platform, platform_stream_id)
);

create index if not exists idx_stream_member_platform_start
    on dashboard.stream (vtuber_id, platform, started_at desc);

create table if not exists dashboard.stream_snapshot (
    snapshot_id bigint primary key,
    stream_id bigint not null references dashboard.stream (stream_id) on delete cascade,
    vtuber_id text not null references dashboard.streamer (vtuber_id),
    platform text not null check (platform in ('youtube', 'twitch')),
    viewer_count integer not null,
    captured_at timestamptz not null,
    title_id bigint references dashboard.stream_title (title_id),
    category_id bigint references dashboard.stream_category (category_id),
    tags_id bigint references dashboard.stream_tags (tags_id)
);

create index if not exists idx_snapshot_stream_time
    on dashboard.stream_snapshot (stream_id, captured_at);

create index if not exists idx_snapshot_member_time
    on dashboard.stream_snapshot (vtuber_id, captured_at desc);

create table if not exists dashboard.current_live_status (
    vtuber_id text not null references dashboard.streamer (vtuber_id),
    platform text not null check (platform in ('youtube', 'twitch')),
    is_live boolean not null,
    stream_id bigint references dashboard.stream (stream_id),
    viewer_count integer,
    stream_url text,
    title_id bigint references dashboard.stream_title (title_id),
    category_id bigint references dashboard.stream_category (category_id),
    tags_id bigint references dashboard.stream_tags (tags_id),
    started_at timestamptz,
    last_checked_at timestamptz not null,
    last_live_at timestamptz,
    primary key (vtuber_id, platform)
);

create index if not exists idx_current_live
    on dashboard.current_live_status (is_live, viewer_count desc);

create table if not exists dashboard.streamer_audience (
    vtuber_id text primary key,
    name text not null,
    group_table text not null,
    youtube_channel_id text,
    youtube_subscribers bigint,
    youtube_source text,
    youtube_count_at timestamptz,
    youtube_error text,
    twitch_login text,
    twitch_followers bigint,
    twitch_source text,
    twitch_count_at timestamptz,
    twitch_error text,
    updated_at timestamptz not null,
    youtube_url text,
    youtube_avatar_url text,
    youtube_avatar_width integer,
    youtube_avatar_height integer,
    youtube_avatar_source text,
    youtube_avatar_at timestamptz,
    youtube_avatar_error text,
    twitch_avatar_url text,
    twitch_avatar_source text,
    twitch_avatar_at timestamptz,
    twitch_avatar_error text
);

create index if not exists idx_audience_youtube_channel
    on dashboard.streamer_audience (youtube_channel_id);

create index if not exists idx_audience_twitch_login
    on dashboard.streamer_audience (twitch_login);

create table if not exists analytics.stream_stats (
    stream_id bigint primary key references dashboard.stream (stream_id) on delete cascade,
    vtuber_id text not null references dashboard.streamer (vtuber_id),
    group_name text not null,
    member_name text not null,
    platform text not null check (platform in ('youtube', 'twitch')),
    stream_url text,
    title text,
    category text,
    started_at timestamptz not null,
    ended_at timestamptz,
    observed_end_at timestamptz,
    peak_viewers integer,
    average_viewers double precision,
    snapshot_count integer not null,
    first_capture timestamptz,
    last_capture timestamptz,
    observed_hours double precision not null
);

create index if not exists idx_stats_member_start
    on analytics.stream_stats (vtuber_id, started_at desc);

create index if not exists idx_stats_group_start
    on analytics.stream_stats (group_name, started_at desc);

create index if not exists idx_stats_group_platform_start
    on analytics.stream_stats (group_name, platform, started_at desc);

create table if not exists analytics.stream_calendar_day (
    stream_id bigint not null references analytics.stream_stats (stream_id) on delete cascade,
    broadcast_day date not null,
    primary key (stream_id, broadcast_day)
);

create index if not exists idx_calendar_day
    on analytics.stream_calendar_day (broadcast_day, stream_id);

create table if not exists analytics.stream_active_interval (
    stream_id bigint not null references analytics.stream_stats (stream_id) on delete cascade,
    minute_of_day smallint not null check (minute_of_day between 0 and 1439),
    primary key (stream_id, minute_of_day)
);

create index if not exists idx_active_interval
    on analytics.stream_active_interval (minute_of_day, stream_id);

-- Program-level grouping: Groups without a numeric display_order are presented
-- as `other` without changing their stored source group_name.
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

-- Defense in depth: raw tables have RLS enabled with no anon/authenticated
-- policies. The server-side postgres role used by the sync job remains able to
-- load data, while browser roles cannot select or mutate raw rows.
alter table dashboard.streamer enable row level security;
alter table dashboard.group_settings enable row level security;
alter table dashboard.stream_title enable row level security;
alter table dashboard.stream_category enable row level security;
alter table dashboard.stream_tags enable row level security;
alter table dashboard.stream enable row level security;
alter table dashboard.stream_snapshot enable row level security;
alter table dashboard.current_live_status enable row level security;
alter table dashboard.streamer_audience enable row level security;
alter table analytics.stream_stats enable row level security;
alter table analytics.stream_calendar_day enable row level security;
alter table analytics.stream_active_interval enable row level security;

-- Only server-side sync jobs need direct table access. Public read access will
-- be added later through reviewed views and RPC functions in the public schema.
revoke all on schema dashboard from anon, authenticated;
revoke all on schema analytics from anon, authenticated;
revoke all on all tables in schema dashboard from anon, authenticated;
revoke all on all tables in schema analytics from anon, authenticated;
revoke all on dashboard.effective_streamer from anon, authenticated;
revoke all on analytics.effective_stream_stats from anon, authenticated;
