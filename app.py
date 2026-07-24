from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE = ROOT / "data" / "live_data.db"
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
    def __init__(self, database: Path):
        self.database = database

    def connect(self):
        connection = sqlite3.connect(
            f"file:{self.database.as_posix()}?mode=ro", uri=True, timeout=5
        )
        connection.row_factory = sqlite3.Row
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
                  (SELECT COUNT(*) FROM stream_snapshot) AS snapshots,
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
                       cls.viewer_count, cls.stream_url, cls.started_at,
                       COALESCE(st.title, stream.title, '未提供標題') AS title,
                       COALESCE(sc.category, stream.category) AS category
                FROM current_live_status cls
                JOIN streamer s ON s.vtuber_id = cls.vtuber_id
                LEFT JOIN stream ON stream.stream_id = cls.stream_id
                LEFT JOIN stream_title st ON st.title_id = cls.title_id
                LEFT JOIN stream_category sc ON sc.category_id = cls.category_id
                WHERE cls.is_live = 1
                ORDER BY cls.viewer_count DESC, s.name
                """
            ).fetchall()
        return [self._clean(row) for row in rows]

    def recent_streams(self, limit=30, platform=None, query=None):
        where, values = [], []
        if platform in {"youtube", "twitch"}:
            where.append("stream.platform = ?")
            values.append(platform)
        if query:
            where.append("(s.name LIKE ? OR stream.title LIKE ? OR stream.vtuber_id LIKE ?)")
            term = f"%{query[:80]}%"
            values.extend([term, term, term])
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        values.append(min(max(limit, 1), 100))
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT stream.stream_id, stream.vtuber_id, s.name, s.group_name,
                       stream.platform, stream.stream_url, stream.title,
                       stream.category, stream.started_at, stream.ended_at,
                       stream.last_seen_at,
                       MAX(ss.viewer_count) AS peak_viewers,
                       COUNT(ss.snapshot_id) AS snapshot_count
                FROM stream
                JOIN streamer s ON s.vtuber_id = stream.vtuber_id
                LEFT JOIN stream_snapshot ss ON ss.stream_id = stream.stream_id
                {clause}
                GROUP BY stream.stream_id
                ORDER BY COALESCE(stream.started_at, stream.first_seen_at) DESC
                LIMIT ?
                """,
                values,
            ).fetchall()
        return [self._clean(row) for row in rows]

    def activity(self, days=14):
        cutoff = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT substr(captured_at, 1, 10) AS day,
                       COUNT(DISTINCT stream_id) AS streams,
                       MAX(viewer_count) AS peak_viewers
                FROM stream_snapshot
                WHERE captured_at >= ?
                GROUP BY substr(captured_at, 1, 10)
                ORDER BY day
                """,
                (cutoff,),
            ).fetchall()
        return [dict(row) for row in rows]

    def group_members(self, group_name):
        with self.connect() as db:
            exists = db.execute(
                "SELECT COUNT(*) FROM streamer WHERE group_name = ?", (group_name,)
            ).fetchone()[0]
            if not exists:
                return None
            rows = db.execute(
                """
                WITH per_stream AS (
                  SELECT st.stream_id, st.vtuber_id, st.platform,
                         COALESCE(st.started_at, st.first_seen_at) AS started_at,
                         MAX(ss.viewer_count) AS peak_viewers,
                         CASE WHEN MAX(ss.viewer_count) > 0
                              THEN AVG(ss.viewer_count) END AS average_viewers
                  FROM stream st
                  LEFT JOIN stream_snapshot ss ON ss.stream_id = st.stream_id
                  GROUP BY st.stream_id
                ),
                live_status AS (
                  SELECT vtuber_id, MAX(is_live) AS is_live,
                         MAX(CASE WHEN is_live = 1 THEN viewer_count END) AS viewers_now
                  FROM current_live_status
                  GROUP BY vtuber_id
                )
                SELECT s.vtuber_id, s.name, s.group_name, s.youtube_url,
                       s.twitch_url, s.enabled, s.display_order,
                       COUNT(ps.stream_id) AS stream_count,
                       SUM(CASE WHEN ps.platform = 'youtube' THEN 1 ELSE 0 END) AS youtube_count,
                       SUM(CASE WHEN ps.platform = 'twitch' THEN 1 ELSE 0 END) AS twitch_count,
                       MAX(ps.peak_viewers) AS peak_viewers,
                       CAST(AVG(ps.peak_viewers) AS INTEGER) AS average_peak_viewers,
                       ROUND(AVG(CASE WHEN ps.platform = 'youtube'
                                      THEN ps.average_viewers END), 1) AS youtube_average_viewers,
                       ROUND(AVG(CASE WHEN ps.platform = 'twitch'
                                      THEN ps.average_viewers END), 1) AS twitch_average_viewers,
                       MIN(ps.started_at) AS first_stream_at,
                       MAX(ps.started_at) AS latest_stream_at,
                       COALESCE(cls.is_live, 0) AS is_live,
                       cls.viewers_now
                FROM streamer s
                LEFT JOIN per_stream ps ON ps.vtuber_id = s.vtuber_id
                LEFT JOIN live_status cls ON cls.vtuber_id = s.vtuber_id
                WHERE s.group_name = ?
                GROUP BY s.vtuber_id
                ORDER BY COALESCE(s.display_order, 999999), s.name
                """,
                (group_name,),
            ).fetchall()
        return [self._clean(row) for row in rows]

    def groups(self):
        with self.connect() as db:
            rows = db.execute(
                """
                WITH member_stats AS (
                  SELECT s.vtuber_id, s.group_name, s.enabled,
                         COUNT(DISTINCT st.stream_id) AS stream_count
                  FROM streamer s
                  LEFT JOIN stream st ON st.vtuber_id = s.vtuber_id
                  GROUP BY s.vtuber_id
                ),
                live_status AS (
                  SELECT vtuber_id, MAX(is_live) AS is_live
                  FROM current_live_status
                  GROUP BY vtuber_id
                )
                SELECT ms.group_name,
                       COUNT(*) AS member_count,
                       SUM(CASE WHEN ms.enabled = 1 THEN 1 ELSE 0 END) AS enabled_count,
                       SUM(ms.stream_count) AS stream_count,
                       COALESCE(MAX(ls.is_live), 0) AS has_live
                FROM member_stats ms
                LEFT JOIN live_status ls ON ls.vtuber_id = ms.vtuber_id
                WHERE ms.group_name = 'meridian'
                GROUP BY ms.group_name
                ORDER BY ms.group_name
                """
            ).fetchall()
        return [self._clean(row) for row in rows]

    def member_analysis(self, group_name, vtuber_id):
        with self.connect() as db:
            profile = db.execute(
                """
                SELECT s.*, COALESCE(MAX(cls.is_live), 0) AS is_live,
                       MAX(CASE WHEN cls.is_live = 1 THEN cls.viewer_count END) AS viewers_now,
                       MAX(CASE WHEN cls.is_live = 1 THEN cls.stream_url END) AS live_url
                FROM streamer s
                LEFT JOIN current_live_status cls ON cls.vtuber_id = s.vtuber_id
                WHERE s.group_name = ? AND s.vtuber_id = ?
                GROUP BY s.vtuber_id
                """,
                (group_name, vtuber_id),
            ).fetchone()
            if profile is None:
                return None

            summary = db.execute(
                """
                WITH per_stream AS (
                  SELECT st.stream_id, st.platform,
                         COALESCE(st.started_at, st.first_seen_at) AS started_at,
                         MAX(ss.viewer_count) AS peak_viewers,
                         CASE WHEN MAX(ss.viewer_count) > 0
                              THEN AVG(ss.viewer_count) END AS average_viewers,
                         COUNT(ss.snapshot_id) AS snapshots,
                         MIN(ss.captured_at) AS first_capture,
                         MAX(ss.captured_at) AS last_capture
                  FROM stream st
                  LEFT JOIN stream_snapshot ss ON ss.stream_id = st.stream_id
                  WHERE st.vtuber_id = ?
                  GROUP BY st.stream_id
                )
                SELECT COUNT(*) AS stream_count,
                       SUM(CASE WHEN platform = 'youtube' THEN 1 ELSE 0 END) AS youtube_count,
                       SUM(CASE WHEN platform = 'twitch' THEN 1 ELSE 0 END) AS twitch_count,
                       MAX(peak_viewers) AS peak_viewers,
                       MAX(CASE WHEN platform = 'youtube' THEN peak_viewers END) AS youtube_peak_viewers,
                       MAX(CASE WHEN platform = 'twitch' THEN peak_viewers END) AS twitch_peak_viewers,
                       CAST(AVG(peak_viewers) AS INTEGER) AS average_peak_viewers,
                       ROUND(AVG(CASE WHEN platform = 'youtube'
                                      THEN average_viewers END), 1) AS youtube_average_viewers,
                       ROUND(AVG(CASE WHEN platform = 'twitch'
                                      THEN average_viewers END), 1) AS twitch_average_viewers,
                       SUM(snapshots) AS snapshot_count,
                       MIN(started_at) AS first_stream_at,
                       MAX(started_at) AS latest_stream_at,
                       ROUND(SUM(
                         CASE WHEN first_capture IS NOT NULL AND last_capture IS NOT NULL
                         THEN MAX((julianday(last_capture) - julianday(first_capture)) * 24, 0)
                         ELSE 0 END
                       ), 1) AS observed_hours
                FROM per_stream
                """,
                (vtuber_id,),
            ).fetchone()

            streams = db.execute(
                """
                SELECT st.stream_id, st.platform, st.stream_url,
                       COALESCE(
                         (SELECT title FROM stream_title
                          WHERE title_id = (
                            SELECT ss.title_id FROM stream_snapshot ss
                            WHERE ss.stream_id = st.stream_id AND ss.title_id IS NOT NULL
                            ORDER BY ss.snapshot_id DESC LIMIT 1
                          )),
                         st.title, '未提供標題'
                       ) AS title,
                       COALESCE(
                         (SELECT category FROM stream_category
                          WHERE category_id = (
                            SELECT ss.category_id FROM stream_snapshot ss
                            WHERE ss.stream_id = st.stream_id AND ss.category_id IS NOT NULL
                            ORDER BY ss.snapshot_id DESC LIMIT 1
                          )),
                         st.category
                       ) AS category,
                       COALESCE(st.started_at, st.first_seen_at) AS started_at,
                       st.ended_at, MAX(ss.viewer_count) AS peak_viewers,
                       CASE WHEN MAX(ss.viewer_count) > 0
                            THEN CAST(AVG(ss.viewer_count) AS INTEGER)
                            END AS average_viewers,
                       COUNT(ss.snapshot_id) AS snapshot_count,
                       MIN(ss.captured_at) AS first_capture,
                       MAX(ss.captured_at) AS last_capture
                FROM stream st
                LEFT JOIN stream_snapshot ss ON ss.stream_id = st.stream_id
                WHERE st.vtuber_id = ?
                GROUP BY st.stream_id
                ORDER BY COALESCE(st.started_at, st.first_seen_at) DESC
                LIMIT 50
                """,
                (vtuber_id,),
            ).fetchall()

            daily = db.execute(
                """
                SELECT substr(COALESCE(st.started_at, st.first_seen_at), 1, 10) AS day,
                       COUNT(DISTINCT st.stream_id) AS streams,
                       MAX(ss.viewer_count) AS peak_viewers
                FROM stream st
                LEFT JOIN stream_snapshot ss ON ss.stream_id = st.stream_id
                WHERE st.vtuber_id = ?
                GROUP BY day
                ORDER BY day
                """,
                (vtuber_id,),
            ).fetchall()

            categories = db.execute(
                """
                WITH stream_categories AS (
                  SELECT st.stream_id,
                         COALESCE(
                           (SELECT sc.category
                            FROM stream_snapshot ss
                            JOIN stream_category sc ON sc.category_id = ss.category_id
                            WHERE ss.stream_id = st.stream_id
                            ORDER BY ss.snapshot_id DESC LIMIT 1),
                           st.category
                         ) AS category
                  FROM stream st
                  WHERE st.vtuber_id = ? AND st.platform = 'twitch'
                )
                SELECT category, COUNT(*) AS stream_count
                FROM stream_categories
                WHERE category IS NOT NULL AND trim(category) <> ''
                GROUP BY category
                ORDER BY stream_count DESC, category
                LIMIT 6
                """,
                (vtuber_id,),
            ).fetchall()

            calendar_streams = db.execute(
                """
                SELECT st.stream_id, st.platform,
                       COALESCE(st.started_at, st.first_seen_at) AS started_at,
                       COALESCE(
                         st.ended_at,
                         MAX(ss.captured_at),
                         st.last_seen_at,
                         st.first_seen_at
                       ) AS observed_end_at
                FROM stream st
                LEFT JOIN stream_snapshot ss ON ss.stream_id = st.stream_id
                WHERE st.vtuber_id = ?
                GROUP BY st.stream_id
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
            if row["platform"] in {"youtube", "twitch"}:
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
        }

    def stream_viewer_history(self, stream_id):
        with self.connect() as db:
            stream = db.execute(
                """
                SELECT st.stream_id, st.vtuber_id, s.name, s.group_name,
                       st.platform, st.stream_url, st.title,
                       COALESCE(st.started_at, st.first_seen_at) AS started_at,
                       st.ended_at
                FROM stream st
                JOIN streamer s ON s.vtuber_id = st.vtuber_id
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

    def group_analysis(self, group_name):
        with self.connect() as db:
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
                  SELECT st.stream_id, st.vtuber_id, st.platform,
                         COALESCE(st.started_at, st.first_seen_at) AS started_at,
                         MAX(ss.viewer_count) AS peak_viewers,
                         CASE WHEN MAX(ss.viewer_count) > 0
                              THEN AVG(ss.viewer_count) END AS average_viewers,
                         COUNT(ss.snapshot_id) AS snapshots,
                         MIN(ss.captured_at) AS first_capture,
                         MAX(ss.captured_at) AS last_capture
                  FROM stream st
                  JOIN streamer s ON s.vtuber_id = st.vtuber_id
                  LEFT JOIN stream_snapshot ss ON ss.stream_id = st.stream_id
                  WHERE s.group_name = ?
                  GROUP BY st.stream_id
                ),
                per_member AS (
                  SELECT vtuber_id,
                         AVG(CASE WHEN platform = 'youtube'
                                  THEN average_viewers END) AS youtube_average_viewers,
                         AVG(CASE WHEN platform = 'twitch'
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
                       ), 1) AS observed_hours
                FROM per_stream
                """,
                (group_name,),
            ).fetchone()
            streams = db.execute(
                """
                WITH stream_stats AS (
                  SELECT stream_id, MAX(viewer_count) AS peak_viewers,
                         CASE WHEN MAX(viewer_count) > 0
                              THEN CAST(AVG(viewer_count) AS INTEGER)
                              END AS average_viewers,
                         COUNT(*) AS snapshot_count,
                         MAX(snapshot_id) AS latest_snapshot_id
                  FROM stream_snapshot
                  GROUP BY stream_id
                )
                SELECT st.stream_id, st.vtuber_id, s.name AS member_name,
                       st.platform, st.stream_url,
                       COALESCE(title.title, st.title, '未提供標題') AS title,
                       COALESCE(category.category, st.category) AS category,
                       COALESCE(st.started_at, st.first_seen_at) AS started_at,
                       st.ended_at, stats.peak_viewers,
                       stats.average_viewers,
                       COALESCE(stats.snapshot_count, 0) AS snapshot_count
                FROM stream st
                JOIN streamer s ON s.vtuber_id = st.vtuber_id
                LEFT JOIN stream_stats stats ON stats.stream_id = st.stream_id
                LEFT JOIN stream_snapshot latest
                       ON latest.snapshot_id = stats.latest_snapshot_id
                LEFT JOIN stream_title title ON title.title_id = latest.title_id
                LEFT JOIN stream_category category
                       ON category.category_id = latest.category_id
                WHERE s.group_name = ?
                ORDER BY COALESCE(st.started_at, st.first_seen_at) DESC
                LIMIT 50
                """,
                (group_name,),
            ).fetchall()
            categories = db.execute(
                """
                WITH latest_snapshots AS (
                  SELECT stream_id, MAX(snapshot_id) AS latest_snapshot_id
                  FROM stream_snapshot
                  GROUP BY stream_id
                ),
                stream_categories AS (
                  SELECT st.stream_id, COALESCE(sc.category, st.category) AS category
                  FROM stream st
                  JOIN streamer s ON s.vtuber_id = st.vtuber_id
                  LEFT JOIN latest_snapshots latest ON latest.stream_id = st.stream_id
                  LEFT JOIN stream_snapshot ss
                         ON ss.snapshot_id = latest.latest_snapshot_id
                  LEFT JOIN stream_category sc ON sc.category_id = ss.category_id
                  WHERE s.group_name = ? AND st.platform = 'twitch'
                )
                SELECT category, COUNT(*) AS stream_count
                FROM stream_categories
                WHERE category IS NOT NULL AND trim(category) <> ''
                GROUP BY category
                ORDER BY stream_count DESC, category
                LIMIT 6
                """,
                (group_name,),
            ).fetchall()
            time_streams = db.execute(
                """
                SELECT st.stream_id, st.platform,
                       COALESCE(st.started_at, st.first_seen_at) AS started_at,
                       COALESCE(st.ended_at, MAX(ss.captured_at),
                                st.last_seen_at, st.first_seen_at) AS observed_end_at
                FROM stream st
                JOIN streamer s ON s.vtuber_id = st.vtuber_id
                LEFT JOIN stream_snapshot ss ON ss.stream_id = st.stream_id
                WHERE s.group_name = ?
                GROUP BY st.stream_id
                """,
                (group_name,),
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
        }

    def health(self):
        with self.connect() as db:
            latest = db.execute(
                """
                SELECT w.*
                FROM working w
                JOIN (
                  SELECT job_name, MAX(working_id) AS working_id
                  FROM working
                  GROUP BY job_name
                ) latest ON latest.working_id = w.working_id
                ORDER BY w.job_name
                """
            ).fetchall()
            summary = db.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM working
                WHERE started_at >= datetime('now', 'localtime', '-24 hours')
                GROUP BY status
                """
            ).fetchall()
        return {
            "latest": [self._clean(row) for row in latest],
            "last_24_hours": [dict(row) for row in summary],
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
            if parsed.path == "/api/activity":
                return self.send_json(self.repository.activity())
            if parsed.path == "/api/health":
                return self.send_json(self.repository.health())
            if parsed.path == "/api/streams":
                params = parse_qs(parsed.query)
                limit = int(params.get("limit", ["30"])[0])
                return self.send_json(
                    self.repository.recent_streams(
                        limit=limit,
                        platform=params.get("platform", [None])[0],
                        query=params.get("q", [None])[0],
                    )
                )
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
                data = self.repository.group_members(parts[2])
                return self.send_json(
                    data if data is not None else {"error": "Group not found"},
                    200 if data is not None else 404,
                )
            if (
                len(parts) == 4
                and parts[:2] == ["api", "groups"]
                and parts[3] == "analysis"
            ):
                data = self.repository.group_analysis(parts[2])
                return self.send_json(
                    data if data is not None else {"error": "Group not found"},
                    200 if data is not None else 404,
                )
            if (
                len(parts) == 5
                and parts[:2] == ["api", "groups"]
                and parts[3] == "members"
            ):
                data = self.repository.member_analysis(parts[2], parts[4])
                return self.send_json(
                    data if data is not None else {"error": "Member not found"},
                    200 if data is not None else 404,
                )
            return self.serve_static(parsed.path)
        except (sqlite3.Error, ValueError) as exc:
            return self.send_json({"error": str(exc)}, 500)

    def serve_static(self, request_path):
        parts = [part for part in request_path.split("/") if part]
        if len(parts) == 2 and parts[0] == "groups":
            relative = "group.html"
        elif len(parts) == 3 and parts[0] == "groups" and parts[2] == "analysis":
            relative = "member.html"
        elif len(parts) == 4 and parts[0] == "groups" and parts[2] == "members":
            relative = "member.html"
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
        help="Path to live_data.db (or set LIVE_DATA_DB)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    database = Path(args.database).resolve()
    if not database.is_file():
        raise SystemExit(f"Database not found: {database}")
    DashboardHandler.repository = DashboardRepository(database)
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Dashboard: http://{args.host}:{args.port}")
    print(f"Database:  {database} (read-only)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
