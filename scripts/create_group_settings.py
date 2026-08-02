#!/usr/bin/env python3
"""Create and synchronize editable Group ordering settings in a live database."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def parse_args() -> argparse.Namespace:
    data_dir = Path(__file__).resolve().parents[1] / "data"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=data_dir / "merged_live_data.db")
    parser.add_argument(
        "--order-by-members",
        action="store_true",
        help="set display_order by member count descending, then group name",
    )
    parser.add_argument(
        "--order-by-average",
        action="store_true",
        help="place other first, then order Groups by member-weighted average viewers",
    )
    parser.add_argument(
        "--analytics-cache",
        type=Path,
        help="analytics cache used by --order-by-average",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database = args.database.resolve()
    if not database.is_file():
        raise SystemExit(f"Database not found: {database}")

    db = sqlite3.connect(database)
    try:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS group_settings (
                group_name TEXT PRIMARY KEY,
                display_order INTEGER,
                note TEXT
            )
            """
        )
        db.execute(
            """
            INSERT OR IGNORE INTO group_settings (group_name)
            SELECT DISTINCT group_name
            FROM streamer
            WHERE group_name IS NOT NULL AND trim(group_name) <> ''
            """
        )
        if args.order_by_members:
            ordered_groups = db.execute(
                """
                SELECT group_name
                FROM streamer
                WHERE group_name IS NOT NULL AND trim(group_name) <> ''
                GROUP BY group_name
                ORDER BY COUNT(*) DESC, group_name
                """
            ).fetchall()
            db.executemany(
                "UPDATE group_settings SET display_order = ? WHERE group_name = ?",
                [
                    (display_order, group_name)
                    for display_order, (group_name,) in enumerate(
                        ordered_groups, start=1
                    )
                ],
            )
        if args.order_by_average:
            cache = args.analytics_cache
            if cache is None:
                cache_name = (
                    "merged_analytics_cache.db"
                    if database.name == "merged_live_data.db"
                    else "analytics_cache.db"
                )
                cache = database.with_name(cache_name)
            cache = cache.resolve()
            if not cache.is_file():
                raise FileNotFoundError(f"Analytics cache not found: {cache}")
            db.execute("ATTACH DATABASE ? AS analytics", (str(cache),))
            ordered_groups = db.execute(
                """
                WITH per_member_platform AS (
                    SELECT group_name, vtuber_id,
                           AVG(CASE WHEN platform = 'youtube'
                                    THEN average_viewers END) AS youtube_average,
                           AVG(CASE WHEN platform = 'twitch'
                                    THEN average_viewers END) AS twitch_average
                    FROM analytics.stream_stats
                    WHERE snapshot_count > 3
                    GROUP BY group_name, vtuber_id
                ),
                per_member AS (
                    SELECT group_name,
                           CASE
                             WHEN youtube_average IS NOT NULL
                                  AND twitch_average IS NOT NULL
                               THEN (youtube_average + twitch_average) / 2.0
                             ELSE COALESCE(youtube_average, twitch_average)
                           END AS average_viewers
                    FROM per_member_platform
                ),
                group_average AS (
                    SELECT group_name, AVG(average_viewers) AS average_viewers
                    FROM per_member
                    WHERE average_viewers IS NOT NULL
                    GROUP BY group_name
                )
                SELECT settings.group_name, group_average.average_viewers
                FROM group_settings settings
                LEFT JOIN group_average USING (group_name)
                ORDER BY CASE WHEN settings.group_name = 'other' THEN 0 ELSE 1 END,
                         CASE WHEN group_average.average_viewers IS NULL THEN 1 ELSE 0 END,
                         group_average.average_viewers DESC,
                         settings.group_name
                """
            ).fetchall()
            db.executemany(
                "UPDATE group_settings SET display_order = ? WHERE group_name = ?",
                [
                    (display_order, group_name)
                    for display_order, (group_name, _) in enumerate(
                        ordered_groups, start=1
                    )
                ],
            )
        db.commit()
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Database integrity check failed: {integrity}")
        count = db.execute("SELECT COUNT(*) FROM group_settings").fetchone()[0]
    finally:
        db.close()

    print(f"Database: {database}")
    print(f"Group settings: {count}")
    if args.order_by_members:
        print("Display order updated by member count descending.")
    if args.order_by_average:
        print("Display order updated by average viewers (other stays first).")
    print("Edit group_settings.display_order to control navigation order.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
