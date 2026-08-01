#!/usr/bin/env python3
"""Convert the legacy collector database to the live dashboard schema."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


GROUP_NAMES = {
    "子午": "meridian",
    "春魚": "springfish",
    "箱箱": "thebox",
    "其他": "other",
}
TABLE_ORDER = (
    "streamer",
    "stream_title",
    "stream_category",
    "stream_tags",
    "stream",
    "stream_snapshot",
    "current_live_status",
    "working",
)


def parse_args() -> argparse.Namespace:
    base = Path(__file__).resolve().parents[1] / "data"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=base / "data.db")
    parser.add_argument("--schema", type=Path, default=base / "live_data.db")
    parser.add_argument("--output", type=Path, default=base / "legacy_live_data.db")
    parser.add_argument(
        "--report", type=Path, default=base / "legacy_migration_report.json"
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="replace an existing output database"
    )
    return parser.parse_args()


def clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"space", "none", "null"}:
        return None
    return text


def youtube_channel_id(url: str | None) -> str | None:
    if not url:
        return None
    marker = "/channel/"
    if marker not in url:
        return None
    result = url.split(marker, 1)[1].split("/", 1)[0].split("?", 1)[0]
    return result or None


def twitch_login(url: str | None) -> str | None:
    if not url:
        return None
    result = url.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
    return result or None


class UnionFind:
    def __init__(self, values: list[int]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: int) -> int:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        if left not in self.parent or right not in self.parent:
            return
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        smaller, larger = sorted((left_root, right_root))
        self.parent[larger] = smaller


def create_schema(target: sqlite3.Connection, schema: sqlite3.Connection) -> None:
    for table in TABLE_ORDER:
        row = schema.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not row or not row[0]:
            raise RuntimeError(f"schema database is missing table: {table}")
        target.execute(row[0])
    target.executescript(
        """
        CREATE INDEX idx_snapshot_stream_time
            ON stream_snapshot(stream_id, captured_at);
        CREATE INDEX idx_snapshot_member_platform_time
            ON stream_snapshot(vtuber_id, platform, captured_at);
        CREATE INDEX idx_stream_member_platform_start
            ON stream(vtuber_id, platform, started_at);
        """
    )


def main() -> int:
    args = parse_args()
    source_path = args.source.resolve()
    schema_path = args.schema.resolve()
    output_path = args.output.resolve()
    report_path = args.report.resolve()

    for path, label in ((source_path, "source"), (schema_path, "schema")):
        if not path.is_file():
            raise FileNotFoundError(f"{label} database not found: {path}")
    if output_path in {source_path, schema_path}:
        raise ValueError("output must be different from source and schema databases")
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(
            f"output already exists: {output_path} (use --overwrite to replace it)"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(output_path.name + ".tmp")
    if temp_path.exists():
        temp_path.unlink()

    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    schema = sqlite3.connect(f"file:{schema_path.as_posix()}?mode=ro", uri=True)
    target = sqlite3.connect(temp_path)
    target.execute("PRAGMA foreign_keys=ON")

    stats: dict[str, object] = {
        "source": str(source_path),
        "output": str(output_path),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "warnings": [],
    }

    try:
        create_schema(target, schema)

        streamers = source.execute(
            """
            SELECT id, channel_id, channel_name, yt_url, tw_url, "group"
            FROM streamer ORDER BY id
            """
        ).fetchall()
        id_aliases: dict[str, str] = {}
        for order, channel_id, name, yt_url, tw_url, group_name in streamers:
            vtuber_id = str(channel_id).strip()
            display_name = clean_text(name) or vtuber_id
            yt_url = clean_text(yt_url)
            tw_url = clean_text(tw_url)
            target.execute(
                """
                INSERT INTO streamer (
                    vtuber_id, group_name, name, youtube_url, youtube_channel_id,
                    twitch_url, twitch_login, enabled, display_order, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    vtuber_id,
                    GROUP_NAMES.get(group_name, clean_text(group_name) or "other"),
                    display_name,
                    yt_url,
                    youtube_channel_id(yt_url),
                    tw_url,
                    twitch_login(tw_url),
                    order,
                    "Migrated from legacy data.db",
                ),
            )
            id_aliases[vtuber_id.casefold()] = vtuber_id
            id_aliases[display_name.casefold()] = vtuber_id

        old_streams = source.execute(
            """
            SELECT id, channel_name, name, type, url, start_time, end_time
            FROM stream ORDER BY id
            """
        ).fetchall()
        old_by_id = {row[0]: row for row in old_streams}
        union = UnionFind(list(old_by_id))
        same_stream_rows = source.execute(
            "SELECT from_id, to_id FROM same_stream"
        ).fetchall()
        for from_id, to_id in same_stream_rows:
            union.union(from_id, to_id)

        components: dict[int, list[tuple]] = defaultdict(list)
        for row in old_streams:
            components[union.find(row[0])].append(row)

        old_to_new: dict[int, int] = {}
        intervals: dict[tuple[str, str], list[tuple[str, str, int]]] = defaultdict(list)
        title_ids: dict[str, int] = {}

        def title_id(title: str | None) -> int | None:
            if not title:
                return None
            if title not in title_ids:
                cur = target.execute(
                    "INSERT OR IGNORE INTO stream_title(title) VALUES (?)", (title,)
                )
                if cur.lastrowid:
                    title_ids[title] = cur.lastrowid
                else:
                    title_ids[title] = target.execute(
                        "SELECT title_id FROM stream_title WHERE title=?", (title,)
                    ).fetchone()[0]
            return title_ids[title]

        stream_title_by_new_id: dict[int, int | None] = {}
        for root in sorted(components):
            rows = components[root]
            channel_values = {str(row[1]).casefold() for row in rows}
            platform_values = {str(row[3]).lower() for row in rows}
            if len(channel_values) != 1 or len(platform_values) != 1:
                stats["warnings"].append(
                    f"same_stream component {root} crosses member/platform boundaries"
                )
                rows = [old_by_id[root]]

            channel = str(rows[0][1])
            vtuber_id = id_aliases.get(channel.casefold())
            if not vtuber_id:
                stats["warnings"].append(
                    f"skipped stream component {root}: unknown member {channel!r}"
                )
                continue
            platform = str(rows[0][3]).lower()
            if platform not in {"youtube", "twitch"}:
                stats["warnings"].append(
                    f"skipped stream component {root}: unknown platform {platform!r}"
                )
                continue

            start = min(str(row[5]) for row in rows)
            end = max(str(row[6]) for row in rows)
            titles = [clean_text(row[2]) for row in rows]
            title = next((value for value in reversed(titles) if value), None)
            urls = [clean_text(row[4]) for row in rows]
            url = next((value for value in reversed(urls) if value), None)
            canonical_old_id = min(row[0] for row in rows)
            cur = target.execute(
                """
                INSERT INTO stream (
                    vtuber_id, platform, platform_stream_id, stream_url, title,
                    started_at, ended_at, first_seen_at, last_seen_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vtuber_id,
                    platform,
                    f"legacy-{platform}-{canonical_old_id}",
                    url,
                    title,
                    start,
                    end,
                    start,
                    end,
                    start,
                    end,
                ),
            )
            new_id = cur.lastrowid
            stream_title_by_new_id[new_id] = title_id(title)
            intervals[(vtuber_id, platform)].append((start, end, new_id))
            for row in rows:
                old_to_new[row[0]] = new_id

        for values in intervals.values():
            values.sort()

        resolved_by_id = 0
        resolved_by_time = 0
        unmatched = 0
        ambiguous = 0
        snapshots = 0
        main_rows = source.execute(
            """
            SELECT date, time, channel, youtube, twitch, yt_number, tw_number
            FROM main ORDER BY date, time, id
            """
        )
        for date, clock, channel, youtube, twitch, yt_number, tw_number in main_rows:
            vtuber_id = id_aliases.get(str(channel).casefold())
            captured_at = f"{date} {clock}"
            if not vtuber_id:
                unmatched += int(youtube is not None and youtube >= 0)
                unmatched += int(twitch is not None and twitch >= 0)
                continue
            for platform, viewers, old_id in (
                ("youtube", youtube, yt_number),
                ("twitch", twitch, tw_number),
            ):
                viewers = int(viewers or 0)
                old_id = int(old_id or 0)
                new_id = old_to_new.get(old_id) if old_id else None
                if new_id:
                    resolved_by_id += 1
                else:
                    matches = [
                        stream_id
                        for start, end, stream_id in intervals.get(
                            (vtuber_id, platform), ()
                        )
                        if start <= captured_at <= end
                    ]
                    if len(matches) == 1:
                        new_id = matches[0]
                        resolved_by_time += 1
                    elif len(matches) > 1:
                        new_id = matches[0]
                        resolved_by_time += 1
                        ambiguous += 1
                    else:
                        # A zero means the platform was offline unless a stream interval
                        # proves otherwise, so it is intentionally not a snapshot.
                        if viewers > 0 or old_id > 0:
                            unmatched += 1
                        continue
                target.execute(
                    """
                    INSERT INTO stream_snapshot (
                        stream_id, vtuber_id, platform, viewer_count,
                        captured_at, title_id
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id,
                        vtuber_id,
                        platform,
                        max(0, viewers),
                        captured_at,
                        stream_title_by_new_id.get(new_id),
                    ),
                )
                snapshots += 1

        latest_check = source.execute(
            "SELECT max(date || ' ' || time) FROM main"
        ).fetchone()[0]
        for vtuber_id, yt_url, tw_url in target.execute(
            "SELECT vtuber_id, youtube_url, twitch_url FROM streamer"
        ).fetchall():
            for platform, url in (("youtube", yt_url), ("twitch", tw_url)):
                if not url:
                    continue
                last_live = target.execute(
                    """
                    SELECT max(coalesce(ended_at, last_seen_at))
                    FROM stream WHERE vtuber_id=? AND platform=?
                    """,
                    (vtuber_id, platform),
                ).fetchone()[0]
                target.execute(
                    """
                    INSERT INTO current_live_status (
                        vtuber_id, platform, is_live, stream_url,
                        last_checked_at, last_live_at
                    ) VALUES (?, ?, 0, ?, ?, ?)
                    """,
                    (vtuber_id, platform, url, latest_check, last_live),
                )

        working_rows = source.execute(
            'SELECT time, finish, timer, kind, "create" FROM working ORDER BY id'
        ).fetchall()
        for started_at, finish, timer, kind, create_value in working_rows:
            status = "success" if str(finish).casefold() == "finish" else "failed"
            try:
                elapsed = float(timer) if timer is not None else None
            except (TypeError, ValueError):
                elapsed = None
            target.execute(
                """
                INSERT INTO working (
                    job_name, status, started_at, finished_at, elapsed_seconds,
                    error_count, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"legacy_{clean_text(kind) or 'collector'}",
                    status,
                    started_at,
                    started_at,
                    elapsed,
                    1 if status == "failed" else 0,
                    clean_text(create_value) if status == "failed" else None,
                ),
            )

        target.commit()
        foreign_key_errors = target.execute("PRAGMA foreign_key_check").fetchall()
        integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
        counts = {
            table: target.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in TABLE_ORDER
        }
        stats.update(
            {
                "source_counts": {
                    table: source.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                    for table in ("streamer", "stream", "main", "same_stream", "working")
                },
                "output_counts": counts,
                "stream_components_merged": len(old_streams) - counts["stream"],
                "snapshot_resolution": {
                    "by_legacy_stream_id": resolved_by_id,
                    "by_time_interval": resolved_by_time,
                    "ambiguous_time_matches": ambiguous,
                    "unmatched_live_records": unmatched,
                    "inserted": snapshots,
                },
                "integrity_check": integrity,
                "foreign_key_errors": len(foreign_key_errors),
            }
        )
        if integrity != "ok" or foreign_key_errors:
            raise RuntimeError(
                f"validation failed: integrity={integrity}, "
                f"foreign_key_errors={len(foreign_key_errors)}"
            )
    except Exception:
        target.close()
        source.close()
        schema.close()
        if temp_path.exists():
            temp_path.unlink()
        raise
    else:
        target.close()
        source.close()
        schema.close()

    if output_path.exists():
        os.replace(temp_path, output_path)
    else:
        temp_path.replace(output_path)
    report_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
