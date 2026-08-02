#!/usr/bin/env python3
"""Build a replaceable analytics cache from live_data.db."""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    data_dir = Path(__file__).resolve().parents[1] / "data"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=data_dir / "live_data.db")
    parser.add_argument(
        "--output", type=Path, default=data_dir / "analytics_cache.db"
    )
    return parser.parse_args()


def parse_database_time(value: str) -> datetime:
    if value.endswith("Z"):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
    return parsed


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_file():
        raise SystemExit(f"Source database not found: {source}")
    if source == output:
        raise SystemExit("Cache output must differ from the source database")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        temporary.unlink()

    db = sqlite3.connect(temporary)
    try:
        db.execute("ATTACH DATABASE ? AS source", (str(source),))
        db.executescript(
            """
            PRAGMA journal_mode = OFF;
            PRAGMA synchronous = OFF;

            CREATE TABLE cache_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE stream_stats (
                stream_id INTEGER PRIMARY KEY,
                vtuber_id TEXT NOT NULL,
                group_name TEXT NOT NULL,
                member_name TEXT NOT NULL,
                platform TEXT NOT NULL,
                stream_url TEXT,
                title TEXT,
                category TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                observed_end_at TEXT,
                peak_viewers INTEGER,
                average_viewers REAL,
                snapshot_count INTEGER NOT NULL,
                first_capture TEXT,
                last_capture TEXT,
                observed_hours REAL NOT NULL
            );

            CREATE INDEX idx_stats_member_start
                ON stream_stats(vtuber_id, started_at);
            CREATE INDEX idx_stats_group_start
                ON stream_stats(group_name, started_at);
            CREATE INDEX idx_stats_group_platform_start
                ON stream_stats(group_name, platform, started_at);

            CREATE TABLE stream_active_interval (
                stream_id INTEGER NOT NULL,
                minute_of_day INTEGER NOT NULL,
                PRIMARY KEY (stream_id, minute_of_day)
            ) WITHOUT ROWID;

            CREATE INDEX idx_interval_stream
                ON stream_active_interval(stream_id);

            CREATE TABLE stream_calendar_day (
                stream_id INTEGER NOT NULL,
                broadcast_day TEXT NOT NULL,
                PRIMARY KEY (stream_id, broadcast_day)
            ) WITHOUT ROWID;

            CREATE INDEX idx_calendar_day
                ON stream_calendar_day(broadcast_day, stream_id);
            """
        )

        db.execute(
            """
            INSERT INTO stream_stats (
                stream_id, vtuber_id, group_name, member_name, platform,
                stream_url, title, category, started_at, ended_at,
                observed_end_at, peak_viewers, average_viewers, snapshot_count,
                first_capture, last_capture, observed_hours
            )
            WITH snapshot_stats AS (
                SELECT stream_id,
                       MAX(viewer_count) AS peak_viewers,
                       CASE WHEN COUNT(*) > 3 AND MAX(viewer_count) > 0
                            THEN AVG(viewer_count) END AS average_viewers,
                       COUNT(*) AS snapshot_count,
                       MIN(captured_at) AS first_capture,
                       MAX(captured_at) AS last_capture,
                       MAX(snapshot_id) AS latest_snapshot_id
                FROM source.stream_snapshot
                GROUP BY stream_id
            )
            SELECT st.stream_id, st.vtuber_id, member.group_name, member.name,
                   st.platform, st.stream_url,
                   COALESCE(title.title, st.title, '未提供標題'),
                   COALESCE(category.category, st.category),
                   COALESCE(st.started_at, st.first_seen_at),
                   st.ended_at,
                   COALESCE(st.ended_at, stats.last_capture,
                            st.last_seen_at, st.first_seen_at),
                   stats.peak_viewers, stats.average_viewers,
                   COALESCE(stats.snapshot_count, 0),
                   stats.first_capture, stats.last_capture,
                   CASE WHEN stats.first_capture IS NOT NULL
                              AND stats.last_capture IS NOT NULL
                        THEN MAX(
                          (julianday(stats.last_capture)
                           - julianday(stats.first_capture)) * 24,
                          0
                        )
                        ELSE 0 END
            FROM source.stream st
            JOIN source.streamer member ON member.vtuber_id = st.vtuber_id
            LEFT JOIN snapshot_stats stats ON stats.stream_id = st.stream_id
            LEFT JOIN source.stream_snapshot latest
                   ON latest.snapshot_id = stats.latest_snapshot_id
            LEFT JOIN source.stream_title title ON title.title_id = latest.title_id
            LEFT JOIN source.stream_category category
                   ON category.category_id = latest.category_id
            """
        )

        rows = db.execute(
            """
            SELECT stream_id, started_at, observed_end_at
            FROM stream_stats
            WHERE started_at IS NOT NULL
            """
        ).fetchall()
        intervals: list[tuple[int, int]] = []
        calendar_days: list[tuple[int, str]] = []
        for stream_id, start_value, end_value in rows:
            start = parse_database_time(start_value)
            end = parse_database_time(end_value) if end_value else start
            if end < start:
                end = start

            cursor = start.replace(
                minute=0 if start.minute < 30 else 30, second=0, microsecond=0
            )
            final = end.replace(
                minute=0 if end.minute < 30 else 30, second=0, microsecond=0
            )
            touched: set[int] = set()
            while cursor <= final and len(touched) < 48:
                touched.add(cursor.hour * 60 + cursor.minute)
                cursor += timedelta(minutes=30)
            intervals.extend((stream_id, minute) for minute in touched)

            first_day = (start - timedelta(hours=12)).date()
            last_day = (end - timedelta(hours=12)).date()
            day = first_day
            while day <= last_day:
                calendar_days.append((stream_id, day.isoformat()))
                day += timedelta(days=1)

        db.executemany(
            "INSERT INTO stream_active_interval VALUES (?, ?)", intervals
        )
        db.executemany(
            "INSERT INTO stream_calendar_day VALUES (?, ?)", calendar_days
        )

        source_stat = source.stat()
        metadata = {
            "schema_version": "1",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source_path": str(source),
            "source_size": str(source_stat.st_size),
            "source_mtime_ns": str(source_stat.st_mtime_ns),
            "stream_count": str(
                db.execute("SELECT COUNT(*) FROM stream_stats").fetchone()[0]
            ),
        }
        db.executemany(
            "INSERT INTO cache_metadata(key, value) VALUES (?, ?)", metadata.items()
        )
        db.commit()
        result = db.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"Cache integrity check failed: {result}")
    except Exception:
        db.close()
        if temporary.exists():
            temporary.unlink()
        raise
    else:
        db.close()

    os.replace(temporary, output)
    print(f"Analytics cache: {output}")
    print(f"Streams cached: {metadata['stream_count']}")
    print(f"Active intervals: {len(intervals)}")
    print(f"Calendar entries: {len(calendar_days)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
