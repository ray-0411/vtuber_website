from __future__ import annotations

import argparse
import calendar as month_calendar
import json
import mimetypes
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE = ROOT / "data" / "merged_live_data.db"
DEFAULT_ANALYTICS_CACHE = ROOT / "data" / "merged_analytics_cache.db"
STATIC_DIR = ROOT / "static"


def repair_text(value):
    """Repair Big5 bytes that were previously decoded as Latin-1, when possible."""
    if not isinstance(value, str) or not value:
        return value
    try:
        repaired = value.encode("latin-1").decode("cp950")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    markers = ("¤", "¡", "¦", "µ", "³", "Â", "½", "©")
    return repaired if sum(value.count(x) for x in markers) >= 2 else value


def parse_database_time(value):
    if not value:
        return None
    try:
        if value.endswith("Z"):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def build_time_analytics(stream_rows):
    calendar_today = datetime.now().date()
    current_week_start = calendar_today - timedelta(days=calendar_today.weekday())
    calendar_start = current_week_start - timedelta(weeks=3)
    calendar_end = current_week_start + timedelta(days=6)
    calendar_counts = {
        calendar_start + timedelta(days=offset): {"youtube": 0, "twitch": 0}
        for offset in range(28)
    }
    interval_counts = {
        minute: {"youtube": 0, "twitch": 0}
        for minute in range(0, 24 * 60, 30)
    }
    for row in stream_rows:
        platform = row["platform"]
        if platform not in {"youtube", "twitch"}:
            continue
        started_at = parse_database_time(row["started_at"])
        ended_at = parse_database_time(row["observed_end_at"]) or started_at
        if started_at is None:
            continue
        if ended_at < started_at:
            ended_at = started_at
        cursor = started_at.replace(
            minute=0 if started_at.minute < 30 else 30, second=0, microsecond=0
        )
        final_interval = ended_at.replace(
            minute=0 if ended_at.minute < 30 else 30, second=0, microsecond=0
        )
        touched_intervals = set()
        while cursor <= final_interval and len(touched_intervals) < 48:
            touched_intervals.add(cursor.hour * 60 + cursor.minute)
            cursor += timedelta(minutes=30)
        include_in_intervals = (
            "include_in_intervals" not in row.keys()
            or row["include_in_intervals"]
        )
        if include_in_intervals:
            for minute in touched_intervals:
                interval_counts[minute][platform] += 1

        first_day = (started_at - timedelta(hours=12)).date()
        last_day = (ended_at - timedelta(hours=12)).date()
        day = max(first_day, calendar_start)
        last_day = min(last_day, calendar_end)
        while day <= last_day:
            calendar_counts[day][platform] += 1
            day += timedelta(days=1)

    return (
        [
            {"day": day.isoformat(), **counts}
            for day, counts in calendar_counts.items()
        ],
        [
            {"minute_of_day": minute, **counts}
            for minute, counts in interval_counts.items()
        ],
    )


class DashboardRepository:
    def __init__(self, database: Path, analytics_cache: Path | None = None):
        self.database = database
        self.analytics_cache = analytics_cache

    def connect(self):
        connection = sqlite3.connect(
            f"file:{self.database.as_posix()}?mode=ro", uri=True, timeout=5
        )
        connection.row_factory = sqlite3.Row
        if self.analytics_cache is not None:
            connection.execute(
                "ATTACH DATABASE ? AS analytics",
                (f"file:{self.analytics_cache.as_posix()}?mode=ro",),
            )
        connection.execute("PRAGMA query_only = ON")
        return connection

    @staticmethod
    def _clean(row):
        return {key: repair_text(value) for key, value in dict(row).items()}

    def overview(self):
        with self.connect() as db:
            counts = db.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM streamer WHERE enabled = 1) AS streamers,
                  (SELECT COUNT(*) FROM current_live_status WHERE is_live = 1) AS live_now,
                  (SELECT COUNT(*) FROM stream) AS streams,
                  (SELECT COALESCE(SUM(viewer_count), 0)
                     FROM current_live_status WHERE is_live = 1) AS viewers_now
                """
            ).fetchone()
            latest = db.execute(
                "SELECT MAX(last_checked_at) AS last_checked_at FROM current_live_status"
            ).fetchone()
            platforms = db.execute(
                """
                SELECT platform, COUNT(*) AS count
                FROM stream
                GROUP BY platform
                ORDER BY count DESC
                """
            ).fetchall()
        return {
            **dict(counts),
            "last_checked_at": latest["last_checked_at"],
            "platforms": [dict(row) for row in platforms],
        }

    def live(self):
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT cls.vtuber_id, s.name, s.group_name, cls.platform,
                       cls.viewer_count, cls.stream_url,
                       (SELECT MIN(snapshot.captured_at)
                          FROM stream_snapshot snapshot
                         WHERE snapshot.stream_id = cls.stream_id)
                         AS started_at,
                       COALESCE(st.title, stream.title, '未提供標題') AS title,
                       audience.youtube_avatar_url,
                       audience.twitch_avatar_url
                FROM current_live_status cls
                JOIN streamer s ON s.vtuber_id = cls.vtuber_id
                LEFT JOIN stream ON stream.stream_id = cls.stream_id
                LEFT JOIN stream_title st ON st.title_id = cls.title_id
                LEFT JOIN streamer_audience audience
                       ON audience.vtuber_id = cls.vtuber_id
                WHERE cls.is_live = 1
                ORDER BY cls.viewer_count DESC, s.name
                """
            ).fetchall()
        return [self._clean(row) for row in rows]

    def weekly_ranking(self, period="last_week", limit=10):
        today = datetime.now().date()
        this_week_start = today - timedelta(days=today.weekday())
        periods = {
            "last_week": (this_week_start - timedelta(days=7), this_week_start),
            "this_week": (this_week_start, today + timedelta(days=1)),
            "this_month": (today.replace(day=1), today + timedelta(days=1)),
        }
        if period not in periods:
            raise ValueError("Invalid ranking period")
        period_start, period_end_exclusive = periods[period]
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT stats.vtuber_id, stats.member_name AS name, stats.group_name,
                       stats.platform, stats.stream_url, stats.title,
                       stats.started_at,
                       CAST(ROUND(stats.average_viewers) AS INTEGER)
                         AS average_viewers,
                       stats.peak_viewers,
                       audience.youtube_avatar_url,
                       audience.twitch_avatar_url
                FROM analytics.stream_stats stats
                LEFT JOIN streamer_audience audience
                       ON audience.vtuber_id = stats.vtuber_id
                WHERE stats.started_at >= ? AND stats.started_at < ?
                  AND stats.average_viewers IS NOT NULL
                  AND stats.snapshot_count >= 5
                ORDER BY stats.platform,
                         stats.average_viewers DESC,
                         stats.peak_viewers DESC,
                         stats.started_at DESC
                """,
                (
                    period_start.isoformat(),
                    period_end_exclusive.isoformat(),
                ),
            ).fetchall()
        ranking_limit = min(max(limit, 1), 50)
        platform_rankings = {}
        for platform in ("youtube", "twitch"):
            platform_rows = [
                self._clean(row) for row in rows if row["platform"] == platform
            ]
            platform_rankings[platform] = {}
            for metric in ("average_viewers", "peak_viewers"):
                ranked_rows = sorted(
                    platform_rows,
                    key=lambda row: (
                        row.get(metric) or 0,
                        row.get("average_viewers") or 0,
                        row.get("peak_viewers") or 0,
                        row.get("started_at") or "",
                    ),
                    reverse=True,
                )
                unique_rows = []
                seen_vtubers = set()
                for row in ranked_rows:
                    if row["vtuber_id"] in seen_vtubers:
                        continue
                    seen_vtubers.add(row["vtuber_id"])
                    unique_rows.append(row)
                    if len(unique_rows) == ranking_limit:
                        break
                platform_rankings[platform][metric] = {
                    "streams": ranked_rows[:ranking_limit],
                    "unique_streams": unique_rows,
                }
        return {
            "period": period,
            "period_start": period_start.isoformat(),
            "period_end": (period_end_exclusive - timedelta(days=1)).isoformat(),
            "platforms": platform_rankings,
        }

    def monthly_average_ranking(self, limit=10):
        today = datetime.now().date()
        month_end = today.replace(day=1)
        month_start = (month_end - timedelta(days=1)).replace(day=1)
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT stats.vtuber_id, stats.member_name AS name,
                       stats.group_name, stats.platform,
                       CAST(ROUND(AVG(stats.average_viewers)) AS INTEGER)
                         AS average_viewers,
                       COUNT(*) AS stream_count,
                       audience.youtube_avatar_url,
                       audience.twitch_avatar_url
                FROM analytics.stream_stats stats
                LEFT JOIN streamer_audience audience
                       ON audience.vtuber_id = stats.vtuber_id
                WHERE stats.started_at >= ? AND stats.started_at < ?
                  AND stats.average_viewers IS NOT NULL
                  AND stats.snapshot_count > 3
                GROUP BY stats.vtuber_id, stats.member_name,
                         stats.group_name, stats.platform
                ORDER BY stats.platform, average_viewers DESC,
                         stream_count DESC, stats.member_name
                """,
                (month_start.isoformat(), month_end.isoformat()),
            ).fetchall()
        ranking_limit = min(max(limit, 1), 50)
        cleaned = [self._clean(row) for row in rows]
        return {
            "month_start": month_start.isoformat(),
            "month_end": (month_end - timedelta(days=1)).isoformat(),
            "platforms": {
                platform: [
                    row for row in cleaned if row["platform"] == platform
                ][:ranking_limit]
                for platform in ("youtube", "twitch")
            },
        }

    def member_rankings(self, metric="average_viewers", platform="combined", period="1m"):
        valid_metrics = {"average_viewers", "peak_viewers", "viewer_hours"}
        valid_platforms = {"combined", "youtube", "twitch"}
        period_modifiers = {
            "1m": "-1 month", "3m": "-3 months", "6m": "-6 months",
            "1y": "-1 year", "all": None,
        }
        if metric not in valid_metrics or platform not in valid_platforms:
            raise ValueError("Invalid ranking selection")
        if period not in period_modifiers:
            raise ValueError("Invalid analysis period")
        with self.connect() as db:
            cutoff = None
            if period_modifiers[period] is not None:
                cutoff = db.execute(
                    "SELECT date('now', 'localtime', ?)",
                    (period_modifiers[period],),
                ).fetchone()[0]
            rows = db.execute(
                """
                SELECT stats.vtuber_id, MAX(stats.member_name) AS name,
                       CASE WHEN MAX(settings.display_order) IS NOT NULL
                                  OR MAX(stats.group_name) = 'other'
                            THEN MAX(stats.group_name) ELSE 'other' END AS group_name,
                       stats.platform,
                       AVG(CASE WHEN stats.snapshot_count > 3
                                THEN stats.average_viewers END) AS average_viewers,
                       MAX(stats.peak_viewers) AS peak_viewers,
                       SUM(CASE WHEN stats.average_viewers IS NOT NULL
                                THEN stats.average_viewers * stats.observed_hours END)
                         AS viewer_hours,
                       MAX(audience.youtube_avatar_url) AS youtube_avatar_url,
                       MAX(audience.twitch_avatar_url) AS twitch_avatar_url
                FROM analytics.stream_stats stats
                LEFT JOIN group_settings settings
                       ON settings.group_name = stats.group_name
                LEFT JOIN streamer_audience audience
                       ON audience.vtuber_id = stats.vtuber_id
                WHERE :cutoff IS NULL OR stats.started_at >= :cutoff
                GROUP BY stats.vtuber_id, stats.platform
                """,
                {"cutoff": cutoff},
            ).fetchall()
        members = {}
        for raw in rows:
            row = self._clean(raw)
            member = members.setdefault(row["vtuber_id"], {
                "vtuber_id": row["vtuber_id"], "name": row["name"],
                "group_name": row["group_name"],
                "youtube_avatar_url": row["youtube_avatar_url"],
                "twitch_avatar_url": row["twitch_avatar_url"],
            })
            for key in valid_metrics:
                member[f"{row['platform']}_{key}"] = row[key]
        ranked = []
        for member in members.values():
            youtube = member.get(f"youtube_{metric}")
            twitch = member.get(f"twitch_{metric}")
            value = member.get(f"{platform}_{metric}") if platform != "combined" else max(
                (item for item in (youtube, twitch) if item is not None), default=None
            )
            if value is not None:
                member["metric_value"] = value
                ranked.append(member)
        ranked.sort(key=lambda row: (-row["metric_value"], row["name"], row["vtuber_id"]))
        for rank, row in enumerate(ranked, 1):
            row["rank"] = rank
        return ranked

    def group_members(self, group_name, period="1m"):
        period_modifiers = {
            "1m": "-1 month",
            "3m": "-3 months",
            "6m": "-6 months",
            "1y": "-1 year",
            "all": None,
        }
        if period not in period_modifiers:
            raise ValueError("Invalid analysis period")
        with self.connect() as db:
            cutoff = None
            if period_modifiers[period] is not None:
                cutoff = db.execute(
                    "SELECT date('now', 'localtime', ?)",
                    (period_modifiers[period],),
                ).fetchone()[0]
            exists = db.execute(
                "SELECT COUNT(*) FROM streamer WHERE group_name = ?", (group_name,)
            ).fetchone()[0]
            if not exists:
                return None
            rows = db.execute(
                """
                WITH per_stream AS (
                  SELECT stream_id, vtuber_id, platform, started_at,
                         peak_viewers, average_viewers, snapshot_count,
                         observed_hours
                  FROM analytics.stream_stats
                ),
                live_status AS (
                  SELECT vtuber_id, MAX(is_live) AS is_live,
                         MAX(CASE WHEN is_live = 1 THEN viewer_count END) AS viewers_now
                  FROM current_live_status
                  GROUP BY vtuber_id
                )
                SELECT s.vtuber_id, s.name, s.group_name, s.youtube_url,
                       s.twitch_url, s.enabled, s.display_order,
                       audience.youtube_subscribers,
                       audience.youtube_count_at,
                       audience.youtube_avatar_url,
                       audience.twitch_followers,
                       audience.twitch_count_at,
                       audience.twitch_avatar_url,
                       COUNT(CASE WHEN (:cutoff IS NULL OR ps.started_at >= :cutoff)
                                  THEN ps.stream_id END) AS stream_count,
                       SUM(CASE WHEN ps.platform = 'youtube'
                                  AND (:cutoff IS NULL OR ps.started_at >= :cutoff)
                                THEN 1 ELSE 0 END) AS youtube_count,
                       SUM(CASE WHEN ps.platform = 'twitch'
                                  AND (:cutoff IS NULL OR ps.started_at >= :cutoff)
                                THEN 1 ELSE 0 END) AS twitch_count,
                       MAX(CASE WHEN (:cutoff IS NULL OR ps.started_at >= :cutoff)
                                THEN ps.peak_viewers END) AS peak_viewers,
                       CAST(AVG(CASE WHEN ps.snapshot_count > 3
                                      AND (:cutoff IS NULL OR ps.started_at >= :cutoff)
                                     THEN ps.peak_viewers END) AS INTEGER)
                         AS average_peak_viewers,
                       ROUND(AVG(CASE WHEN ps.platform = 'youtube'
                                       AND ps.snapshot_count > 3
                                       AND (:cutoff IS NULL OR ps.started_at >= :cutoff)
                                      THEN ps.average_viewers END), 1) AS youtube_average_viewers,
                       ROUND(AVG(CASE WHEN ps.platform = 'twitch'
                                       AND ps.snapshot_count > 3
                                       AND (:cutoff IS NULL OR ps.started_at >= :cutoff)
                                      THEN ps.average_viewers END), 1) AS twitch_average_viewers,
                       ROUND(SUM(CASE WHEN ps.average_viewers IS NOT NULL
                                      AND (:cutoff IS NULL OR ps.started_at >= :cutoff)
                                     THEN ps.average_viewers * ps.observed_hours
                                     ELSE 0 END), 1) AS viewer_hours,
                       MIN(ps.started_at) AS first_stream_at,
                       MAX(ps.started_at) AS latest_stream_at,
                       COALESCE(cls.is_live, 0) AS is_live,
                       cls.viewers_now
                FROM streamer s
                LEFT JOIN per_stream ps ON ps.vtuber_id = s.vtuber_id
                LEFT JOIN live_status cls ON cls.vtuber_id = s.vtuber_id
                LEFT JOIN streamer_audience audience
                       ON audience.vtuber_id = s.vtuber_id
                WHERE s.group_name = :group_name
                GROUP BY s.vtuber_id
                ORDER BY COALESCE(s.display_order, 999999), s.name
                """,
                {"group_name": group_name, "cutoff": cutoff},
            ).fetchall()
        return [self._clean(row) for row in rows]

    def groups(self):
        with self.connect() as db:
            has_group_settings = db.execute(
                """
                SELECT COUNT(*) FROM sqlite_master
                WHERE type = 'table' AND name = 'group_settings'
                """
            ).fetchone()[0]
            settings_join = (
                "LEFT JOIN group_settings settings ON settings.group_name = ms.group_name"
                if has_group_settings
                else ""
            )
            display_order = (
                "settings.display_order AS display_order"
                if has_group_settings
                else "NULL AS display_order"
            )
            ordering = (
                "CASE WHEN settings.display_order IS NULL THEN 1 ELSE 0 END, "
                "settings.display_order, ms.group_name"
                if has_group_settings
                else "ms.group_name"
            )
            rows = db.execute(
                f"""
                WITH member_stats AS (
                  SELECT s.vtuber_id, s.group_name, s.enabled,
                         audience.youtube_subscribers,
                         audience.twitch_followers,
                         COUNT(DISTINCT st.stream_id) AS stream_count
                  FROM streamer s
                  LEFT JOIN stream st ON st.vtuber_id = s.vtuber_id
                  LEFT JOIN streamer_audience audience
                         ON audience.vtuber_id = s.vtuber_id
                  GROUP BY s.vtuber_id
                ),
                live_status AS (
                  SELECT vtuber_id, MAX(is_live) AS is_live
                  FROM current_live_status
                  GROUP BY vtuber_id
                )
                SELECT ms.group_name,
                       {display_order},
                       COUNT(*) AS member_count,
                       SUM(CASE WHEN ms.enabled = 1 THEN 1 ELSE 0 END) AS enabled_count,
                       SUM(COALESCE(ms.youtube_subscribers, 0)) AS youtube_subscribers,
                       SUM(COALESCE(ms.twitch_followers, 0)) AS twitch_followers,
                       SUM(ms.stream_count) AS stream_count,
                       COALESCE(MAX(ls.is_live), 0) AS has_live
                FROM member_stats ms
                LEFT JOIN live_status ls ON ls.vtuber_id = ms.vtuber_id
                {settings_join}
                GROUP BY ms.group_name
                ORDER BY {ordering}
                """
            ).fetchall()
        return [self._clean(row) for row in rows]

    def member_analysis(self, group_name, vtuber_id, period="1m"):
        period_modifiers = {
            "1m": "-1 month",
            "3m": "-3 months",
            "6m": "-6 months",
            "1y": "-1 year",
            "all": None,
        }
        if period not in period_modifiers:
            raise ValueError("Invalid analysis period")
        with self.connect() as db:
            profile = db.execute(
                """
                SELECT s.*, COALESCE(MAX(cls.is_live), 0) AS is_live,
                       MAX(CASE WHEN cls.is_live = 1 THEN cls.viewer_count END) AS viewers_now,
                       MAX(CASE WHEN cls.is_live = 1 THEN cls.stream_url END) AS live_url,
                       audience.youtube_subscribers,
                       audience.youtube_count_at,
                       audience.youtube_avatar_url,
                       audience.twitch_followers,
                       audience.twitch_count_at,
                       audience.twitch_avatar_url
                FROM streamer s
                LEFT JOIN current_live_status cls ON cls.vtuber_id = s.vtuber_id
                LEFT JOIN streamer_audience audience
                       ON audience.vtuber_id = s.vtuber_id
                WHERE s.group_name = ? AND s.vtuber_id = ?
                GROUP BY s.vtuber_id
                """,
                (group_name, vtuber_id),
            ).fetchone()
            if profile is None:
                return None

            latest_stream_at = db.execute(
                """
                SELECT MAX(COALESCE(started_at, first_seen_at))
                FROM stream
                WHERE vtuber_id = ?
                """,
                (vtuber_id,),
            ).fetchone()[0]
            cutoff = None
            if period_modifiers[period] is not None:
                cutoff = db.execute(
                    "SELECT date('now', 'localtime', ?)",
                    (period_modifiers[period],),
                ).fetchone()[0]

            summary = db.execute(
                """
                WITH per_stream AS (
                  SELECT stream_id, platform, started_at, peak_viewers,
                         average_viewers, snapshot_count AS snapshots,
                         first_capture, last_capture
                  FROM analytics.stream_stats
                  WHERE vtuber_id = ?
                    AND (? IS NULL OR started_at >= ?)
                )
                SELECT COUNT(*) AS stream_count,
                       SUM(CASE WHEN platform = 'youtube' THEN 1 ELSE 0 END) AS youtube_count,
                       SUM(CASE WHEN platform = 'twitch' THEN 1 ELSE 0 END) AS twitch_count,
                       MAX(peak_viewers) AS peak_viewers,
                       MAX(CASE WHEN platform = 'youtube' THEN peak_viewers END) AS youtube_peak_viewers,
                       MAX(CASE WHEN platform = 'twitch' THEN peak_viewers END) AS twitch_peak_viewers,
                       CAST(AVG(CASE WHEN snapshots > 3 THEN peak_viewers END) AS INTEGER)
                         AS average_peak_viewers,
                       ROUND(AVG(CASE WHEN platform = 'youtube'
                                      AND snapshots > 3
                                      THEN average_viewers END), 1) AS youtube_average_viewers,
                       ROUND(AVG(CASE WHEN platform = 'twitch'
                                      AND snapshots > 3
                                      THEN average_viewers END), 1) AS twitch_average_viewers,
                       SUM(snapshots) AS snapshot_count,
                       MIN(started_at) AS first_stream_at,
                       MAX(started_at) AS latest_stream_at,
                       ROUND(SUM(
                         CASE WHEN first_capture IS NOT NULL AND last_capture IS NOT NULL
                         THEN MAX((julianday(last_capture) - julianday(first_capture)) * 24, 0)
                         ELSE 0 END
                       ), 1) AS observed_hours,
                       ROUND(SUM(
                         CASE WHEN average_viewers IS NOT NULL
                                   AND first_capture IS NOT NULL
                                   AND last_capture IS NOT NULL
                         THEN average_viewers * MAX(
                           (julianday(last_capture) - julianday(first_capture)) * 24, 0
                         ) ELSE 0 END
                       ), 1) AS viewer_hours,
                       ROUND(SUM(CASE WHEN platform = 'youtube'
                                          AND average_viewers IS NOT NULL
                                          AND first_capture IS NOT NULL
                                          AND last_capture IS NOT NULL
                                     THEN average_viewers * MAX(
                                       (julianday(last_capture) - julianday(first_capture)) * 24, 0
                                     ) ELSE 0 END), 1) AS youtube_viewer_hours,
                       ROUND(SUM(CASE WHEN platform = 'twitch'
                                          AND average_viewers IS NOT NULL
                                          AND first_capture IS NOT NULL
                                          AND last_capture IS NOT NULL
                                     THEN average_viewers * MAX(
                                       (julianday(last_capture) - julianday(first_capture)) * 24, 0
                                     ) ELSE 0 END), 1) AS twitch_viewer_hours
                FROM per_stream
                """,
                (vtuber_id, cutoff, cutoff),
            ).fetchone()

            streams = db.execute(
                """
                SELECT stream_id, platform, stream_url, title, category,
                       started_at, ended_at, peak_viewers,
                       CAST(average_viewers AS INTEGER) AS average_viewers,
                       snapshot_count, first_capture, last_capture
                FROM analytics.stream_stats
                WHERE vtuber_id = ?
                ORDER BY started_at DESC
                LIMIT 50
                """,
                (vtuber_id,),
            ).fetchall()

            daily = db.execute(
                """
                SELECT substr(started_at, 1, 10) AS day,
                       COUNT(*) AS streams,
                       MAX(peak_viewers) AS peak_viewers
                FROM analytics.stream_stats
                WHERE vtuber_id = ?
                GROUP BY day
                ORDER BY day
                """,
                (vtuber_id,),
            ).fetchall()

            categories = db.execute(
                """
                WITH stream_categories AS (
                  SELECT stream_id, category
                  FROM analytics.stream_stats
                  WHERE vtuber_id = ? AND platform = 'twitch'
                    AND (? IS NULL OR started_at >= ?)
                )
                SELECT category, COUNT(*) AS stream_count
                FROM stream_categories
                WHERE category IS NOT NULL AND trim(category) <> ''
                GROUP BY category
                ORDER BY stream_count DESC, category
                LIMIT 6
                """,
                (vtuber_id, cutoff, cutoff),
            ).fetchall()

            calendar_streams = db.execute(
                """
                SELECT stream_id, platform, started_at, observed_end_at
                FROM analytics.stream_stats
                WHERE vtuber_id = ?
                """,
                (vtuber_id,),
            ).fetchall()

        calendar_today = datetime.now().date()
        current_week_start = calendar_today - timedelta(days=calendar_today.weekday())
        calendar_start = current_week_start - timedelta(weeks=3)
        calendar_end = current_week_start + timedelta(days=6)
        calendar_counts = {
            day: {"youtube": 0, "twitch": 0}
            for day in (
                calendar_start + timedelta(days=offset)
                for offset in range(28)
            )
        }
        active_interval_counts = {
            minute: {"youtube": 0, "twitch": 0}
            for minute in range(0, 24 * 60, 30)
        }
        for row in calendar_streams:
            started_at = parse_database_time(row["started_at"])
            ended_at = parse_database_time(row["observed_end_at"]) or started_at
            if started_at is None:
                continue
            if ended_at < started_at:
                ended_at = started_at
            cursor = started_at.replace(
                minute=0 if started_at.minute < 30 else 30,
                second=0,
                microsecond=0,
            )
            final_interval = ended_at.replace(
                minute=0 if ended_at.minute < 30 else 30,
                second=0,
                microsecond=0,
            )
            touched_intervals = set()
            while cursor <= final_interval and len(touched_intervals) < 48:
                touched_intervals.add(cursor.hour * 60 + cursor.minute)
                cursor += timedelta(minutes=30)
            within_period = cutoff is None or row["started_at"] >= cutoff
            if within_period and row["platform"] in {"youtube", "twitch"}:
                for minute in touched_intervals:
                    active_interval_counts[minute][row["platform"]] += 1
            first_day = (started_at - timedelta(hours=12)).date()
            last_day = (ended_at - timedelta(hours=12)).date()
            day = max(first_day, calendar_start)
            last_day = min(last_day, calendar_end)
            while day <= last_day:
                if row["platform"] in calendar_counts[day]:
                    calendar_counts[day][row["platform"]] += 1
                day += timedelta(days=1)

        calendar = [
            {
                "day": day.isoformat(),
                "youtube": counts["youtube"],
                "twitch": counts["twitch"],
            }
            for day, counts in calendar_counts.items()
        ]
        active_intervals = [
            {
                "minute_of_day": minute,
                "youtube": counts["youtube"],
                "twitch": counts["twitch"],
            }
            for minute, counts in active_interval_counts.items()
        ]

        return {
            "profile": self._clean(profile),
            "summary": dict(summary),
            "streams": [self._clean(row) for row in streams],
            "daily": [dict(row) for row in daily],
            "categories": [self._clean(row) for row in categories],
            "active_intervals": active_intervals,
            "calendar": calendar,
            "period": {
                "value": period,
                "cutoff": cutoff,
                "latest_stream_at": latest_stream_at,
            },
        }

    def stream_viewer_history(self, stream_id):
        with self.connect() as db:
            stream = db.execute(
                """
                SELECT st.stream_id, st.vtuber_id, s.name, s.group_name,
                       st.platform, st.stream_url,
                       COALESCE(stats.title, st.title, '未提供標題') AS title,
                       COALESCE(stats.category, st.category) AS category,
                       COALESCE(st.started_at, st.first_seen_at) AS started_at,
                       st.ended_at, stats.observed_end_at
                FROM stream st
                JOIN streamer s ON s.vtuber_id = st.vtuber_id
                LEFT JOIN analytics.stream_stats stats USING (stream_id)
                WHERE st.stream_id = ?
                """,
                (stream_id,),
            ).fetchone()
            if stream is None:
                return None
            snapshots = db.execute(
                """
                SELECT snapshot_id, viewer_count, captured_at
                FROM stream_snapshot
                WHERE stream_id = ?
                ORDER BY captured_at, snapshot_id
                """,
                (stream_id,),
            ).fetchall()
            return {
                "stream": self._clean(stream),
                "snapshots": [dict(row) for row in snapshots],
            }

    def member_month_history(self, group_name, vtuber_id, month=None):
        with self.connect() as db:
            profile = db.execute(
                """
                SELECT vtuber_id, name, group_name
                FROM streamer
                WHERE group_name = ? AND vtuber_id = ?
                """,
                (group_name, vtuber_id),
            ).fetchone()
            if profile is None:
                return None

            available = db.execute(
                """
                SELECT MIN(substr(day.broadcast_day, 1, 7)),
                       MAX(substr(day.broadcast_day, 1, 7))
                FROM analytics.stream_calendar_day day
                JOIN analytics.stream_stats stats USING (stream_id)
                WHERE stats.vtuber_id = ?
                """,
                (vtuber_id,),
            ).fetchone()
            first_month, last_month = available
            selected_month = month or last_month or datetime.now().strftime("%Y-%m")
            try:
                selected_date = datetime.strptime(selected_month, "%Y-%m")
            except ValueError as exc:
                raise ValueError("Month must use YYYY-MM format") from exc
            if selected_date.strftime("%Y-%m") != selected_month:
                raise ValueError("Month must use YYYY-MM format")

            year, month_number = selected_date.year, selected_date.month
            day_count = month_calendar.monthrange(year, month_number)[1]
            month_start = f"{selected_month}-01"
            month_end = f"{selected_month}-{day_count:02d}"
            counted_days = {
                row["day"]: {"youtube": row["youtube"], "twitch": row["twitch"]}
                for row in db.execute(
                    """
                    SELECT day.broadcast_day AS day,
                           SUM(CASE WHEN stats.platform = 'youtube' THEN 1 ELSE 0 END)
                             AS youtube,
                           SUM(CASE WHEN stats.platform = 'twitch' THEN 1 ELSE 0 END)
                             AS twitch
                    FROM analytics.stream_calendar_day day
                    JOIN analytics.stream_stats stats USING (stream_id)
                    WHERE stats.vtuber_id = ?
                      AND day.broadcast_day BETWEEN ? AND ?
                    GROUP BY day.broadcast_day
                    """,
                    (vtuber_id, month_start, month_end),
                ).fetchall()
            }
            days = []
            for day_number in range(1, day_count + 1):
                day = f"{selected_month}-{day_number:02d}"
                values = counted_days.get(day, {"youtube": 0, "twitch": 0})
                days.append({"day": day, **values})

            streams = db.execute(
                """
                SELECT DISTINCT stats.stream_id, stats.platform, stats.stream_url,
                       stats.title, stats.category, stats.started_at, stats.ended_at,
                       stats.peak_viewers,
                       CAST(stats.average_viewers AS INTEGER) AS average_viewers,
                       stats.snapshot_count
                FROM analytics.stream_stats stats
                JOIN analytics.stream_calendar_day day USING (stream_id)
                WHERE stats.vtuber_id = ?
                  AND day.broadcast_day BETWEEN ? AND ?
                ORDER BY stats.started_at DESC
                """,
                (vtuber_id, month_start, month_end),
            ).fetchall()
            return {
                "profile": self._clean(profile),
                "month": selected_month,
                "available": {"first": first_month, "last": last_month},
                "calendar": days,
                "streams": [self._clean(row) for row in streams],
            }

    def group_analysis(self, group_name, period="1m"):
        period_modifiers = {
            "1m": "-1 month",
            "3m": "-3 months",
            "6m": "-6 months",
            "1y": "-1 year",
            "all": None,
        }
        if period not in period_modifiers:
            raise ValueError("Invalid analysis period")
        with self.connect() as db:
            cutoff = None
            if period_modifiers[period] is not None:
                cutoff = db.execute(
                    "SELECT date('now', 'localtime', ?)",
                    (period_modifiers[period],),
                ).fetchone()[0]
            group_row = db.execute(
                """
                SELECT group_name AS name, group_name,
                       COUNT(*) AS member_count,
                       SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) AS enabled_count
                FROM streamer
                WHERE group_name = ?
                GROUP BY group_name
                """,
                (group_name,),
            ).fetchone()
            if group_row is None:
                return None
            live_row = db.execute(
                """
                SELECT COALESCE(MAX(cls.is_live), 0) AS is_live,
                       COALESCE(SUM(CASE WHEN cls.is_live = 1
                                         THEN cls.viewer_count ELSE 0 END), 0) AS viewers_now
                FROM streamer s
                LEFT JOIN current_live_status cls ON cls.vtuber_id = s.vtuber_id
                WHERE s.group_name = ?
                """,
                (group_name,),
            ).fetchone()
            profile = {
                **dict(group_row),
                **dict(live_row),
                "vtuber_id": group_name,
                "is_group": True,
                "enabled": 1,
                "youtube_url": None,
                "twitch_url": None,
                "live_url": None,
            }
            summary = db.execute(
                """
                WITH per_stream AS (
                  SELECT stream_id, vtuber_id, platform, started_at,
                         peak_viewers, average_viewers,
                         snapshot_count AS snapshots, first_capture, last_capture
                  FROM analytics.stream_stats
                  WHERE group_name = ?
                    AND (? IS NULL OR started_at >= ?)
                ),
                per_member AS (
                  SELECT vtuber_id,
                         AVG(CASE WHEN platform = 'youtube'
                                  AND snapshots > 3
                                  THEN average_viewers END) AS youtube_average_viewers,
                         AVG(CASE WHEN platform = 'twitch'
                                  AND snapshots > 3
                                  THEN average_viewers END) AS twitch_average_viewers
                  FROM per_stream
                  GROUP BY vtuber_id
                )
                SELECT COUNT(*) AS stream_count,
                       SUM(CASE WHEN platform = 'youtube' THEN 1 ELSE 0 END) AS youtube_count,
                       SUM(CASE WHEN platform = 'twitch' THEN 1 ELSE 0 END) AS twitch_count,
                       MAX(CASE WHEN platform = 'youtube' THEN peak_viewers END) AS youtube_peak_viewers,
                       MAX(CASE WHEN platform = 'twitch' THEN peak_viewers END) AS twitch_peak_viewers,
                       (SELECT ROUND(AVG(youtube_average_viewers), 1) FROM per_member)
                         AS youtube_average_viewers,
                       (SELECT ROUND(AVG(twitch_average_viewers), 1) FROM per_member)
                         AS twitch_average_viewers,
                       SUM(snapshots) AS snapshot_count,
                       MIN(started_at) AS first_stream_at,
                       MAX(started_at) AS latest_stream_at,
                       ROUND(SUM(
                         CASE WHEN first_capture IS NOT NULL AND last_capture IS NOT NULL
                         THEN MAX((julianday(last_capture) - julianday(first_capture)) * 24, 0)
                         ELSE 0 END
                       ), 1) AS observed_hours,
                       ROUND(SUM(
                         CASE WHEN average_viewers IS NOT NULL
                                   AND first_capture IS NOT NULL
                                   AND last_capture IS NOT NULL
                         THEN average_viewers * MAX(
                           (julianday(last_capture) - julianday(first_capture)) * 24, 0
                         ) ELSE 0 END
                       ), 1) AS viewer_hours,
                       ROUND(SUM(CASE WHEN platform = 'youtube'
                                          AND average_viewers IS NOT NULL
                                          AND first_capture IS NOT NULL
                                          AND last_capture IS NOT NULL
                                     THEN average_viewers * MAX(
                                       (julianday(last_capture) - julianday(first_capture)) * 24, 0
                                     ) ELSE 0 END), 1) AS youtube_viewer_hours,
                       ROUND(SUM(CASE WHEN platform = 'twitch'
                                          AND average_viewers IS NOT NULL
                                          AND first_capture IS NOT NULL
                                          AND last_capture IS NOT NULL
                                     THEN average_viewers * MAX(
                                       (julianday(last_capture) - julianday(first_capture)) * 24, 0
                                     ) ELSE 0 END), 1) AS twitch_viewer_hours
                FROM per_stream
                """,
                (group_name, cutoff, cutoff),
            ).fetchone()
            streams = db.execute(
                """
                SELECT stream_id, vtuber_id, member_name, platform, stream_url,
                       title, category, started_at, ended_at, peak_viewers,
                       CAST(average_viewers AS INTEGER) AS average_viewers,
                       snapshot_count
                FROM analytics.stream_stats
                WHERE group_name = ?
                ORDER BY started_at DESC
                LIMIT 50
                """,
                (group_name,),
            ).fetchall()
            categories = db.execute(
                """
                SELECT category, COUNT(*) AS stream_count
                FROM analytics.stream_stats
                WHERE group_name = ? AND platform = 'twitch'
                  AND (? IS NULL OR started_at >= ?)
                  AND category IS NOT NULL AND trim(category) <> ''
                GROUP BY category
                ORDER BY stream_count DESC, category
                LIMIT 6
                """,
                (group_name, cutoff, cutoff),
            ).fetchall()
            time_streams = db.execute(
                """
                SELECT stream_id, platform, started_at, observed_end_at,
                       CASE WHEN ? IS NULL OR started_at >= ?
                            THEN 1 ELSE 0 END AS include_in_intervals
                FROM analytics.stream_stats
                WHERE group_name = ?
                """,
                (cutoff, cutoff, group_name),
            ).fetchall()

        calendar, active_intervals = build_time_analytics(time_streams)
        return {
            "profile": self._clean(profile),
            "summary": dict(summary),
            "streams": [self._clean(row) for row in streams],
            "daily": [],
            "categories": [self._clean(row) for row in categories],
            "active_intervals": active_intervals,
            "calendar": calendar,
            "period": {
                "value": period,
                "cutoff": cutoff,
            },
        }

class DashboardHandler(BaseHTTPRequestHandler):
    repository: DashboardRepository

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/overview":
                return self.send_json(self.repository.overview())
            if parsed.path == "/api/live":
                return self.send_json(self.repository.live())
            if parsed.path == "/api/rankings/weekly":
                params = parse_qs(parsed.query)
                return self.send_json(self.repository.weekly_ranking(
                    period=params.get("period", ["last_week"])[0]
                ))
            if parsed.path == "/api/rankings/monthly-average":
                return self.send_json(self.repository.monthly_average_ranking())
            if parsed.path == "/api/rankings/members":
                params = parse_qs(parsed.query)
                return self.send_json(self.repository.member_rankings(
                    metric=params.get("metric", ["average_viewers"])[0],
                    platform=params.get("platform", ["combined"])[0],
                    period=params.get("period", ["1m"])[0],
                ))
            parts = [part for part in parsed.path.split("/") if part]
            if (
                len(parts) == 4
                and parts[:2] == ["api", "streams"]
                and parts[3] == "snapshots"
            ):
                try:
                    stream_id = int(parts[2])
                except ValueError:
                    return self.send_json({"error": "Invalid stream ID"}, 400)
                data = self.repository.stream_viewer_history(stream_id)
                return self.send_json(
                    data if data is not None else {"error": "Stream not found"},
                    200 if data is not None else 404,
                )
            if parts == ["api", "groups"]:
                return self.send_json(self.repository.groups())
            if len(parts) == 3 and parts[:2] == ["api", "groups"]:
                params = parse_qs(parsed.query)
                data = self.repository.group_members(
                    parts[2],
                    period=params.get("period", ["1m"])[0],
                )
                return self.send_json(
                    data if data is not None else {"error": "Group not found"},
                    200 if data is not None else 404,
                )
            if (
                len(parts) == 4
                and parts[:2] == ["api", "groups"]
                and parts[3] == "analysis"
            ):
                params = parse_qs(parsed.query)
                data = self.repository.group_analysis(
                    parts[2],
                    period=params.get("period", ["1m"])[0],
                )
                return self.send_json(
                    data if data is not None else {"error": "Group not found"},
                    200 if data is not None else 404,
                )
            if (
                len(parts) == 6
                and parts[:2] == ["api", "groups"]
                and parts[3] == "members"
                and parts[5] == "history"
            ):
                params = parse_qs(parsed.query)
                try:
                    data = self.repository.member_month_history(
                        parts[2],
                        parts[4],
                        month=params.get("month", [None])[0],
                    )
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                return self.send_json(
                    data if data is not None else {"error": "Member not found"},
                    200 if data is not None else 404,
                )
            if (
                len(parts) == 5
                and parts[:2] == ["api", "groups"]
                and parts[3] == "members"
            ):
                params = parse_qs(parsed.query)
                data = self.repository.member_analysis(
                    parts[2],
                    parts[4],
                    period=params.get("period", ["1m"])[0],
                )
                return self.send_json(
                    data if data is not None else {"error": "Member not found"},
                    200 if data is not None else 404,
                )
            return self.serve_static(parsed.path)
        except (sqlite3.Error, ValueError) as exc:
            return self.send_json({"error": str(exc)}, 500)

    def serve_static(self, request_path):
        parts = [part for part in request_path.split("/") if part]
        if parts == ["rankings"]:
            relative = "rankings.html"
        elif len(parts) == 2 and parts[0] == "groups":
            relative = "group.html"
        elif len(parts) == 3 and parts[0] == "groups" and parts[2] == "analysis":
            relative = "member.html"
        elif len(parts) == 4 and parts[0] == "groups" and parts[2] == "members":
            relative = "member.html"
        elif (
            len(parts) == 5
            and parts[0] == "groups"
            and parts[2] == "members"
            and parts[4] == "history"
        ):
            relative = "history.html"
        else:
            relative = "index.html" if request_path == "/" else request_path.lstrip("/")
        path = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in path.parents or not path.is_file():
            return self.send_json({"error": "Not found"}, 404)
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def main():
    parser = argparse.ArgumentParser(description="VTuber live data dashboard")
    parser.add_argument(
        "--database",
        default=os.environ.get("LIVE_DATA_DB", str(DEFAULT_DATABASE)),
        help="Path to a dashboard database (or set LIVE_DATA_DB)",
    )
    parser.add_argument(
        "--analytics-cache",
        default=os.environ.get(
            "ANALYTICS_CACHE_DB", str(DEFAULT_ANALYTICS_CACHE)
        ),
        help="Path to analytics_cache.db (or set ANALYTICS_CACHE_DB)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    database = Path(args.database).resolve()
    if not database.is_file():
        raise SystemExit(f"Database not found: {database}")
    analytics_cache = Path(args.analytics_cache).resolve()
    if not analytics_cache.is_file():
        raise SystemExit(
            f"Analytics cache not found: {analytics_cache}\n"
            "Run: python scripts/build_analytics_cache.py"
        )
    DashboardHandler.repository = DashboardRepository(database, analytics_cache)
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Dashboard: http://{args.host}:{args.port}")
    print(f"Database:  {database} (read-only)")
    print(f"Analytics: {analytics_cache} (read-only)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
