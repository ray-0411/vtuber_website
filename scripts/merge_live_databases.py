#!/usr/bin/env python3
"""Merge a migrated legacy database into the current live database safely."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


CORE_TABLES = (
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
    data_dir = Path(__file__).resolve().parents[1] / "data"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, default=data_dir / "live_data.db")
    parser.add_argument(
        "--legacy", type=Path, default=data_dir / "legacy_live_data.db"
    )
    parser.add_argument(
        "--output", type=Path, default=data_dir / "merged_live_data.db"
    )
    parser.add_argument(
        "--report", type=Path, default=data_dir / "merge_report.json"
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="replace an existing output database"
    )
    return parser.parse_args()


def database_uri(path: Path, mode: str = "ro") -> str:
    return f"file:{path.resolve().as_posix()}?mode={mode}"


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
    return parsed


def table_sql(db: sqlite3.Connection, table: str) -> str | None:
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row[0] if row else None


def validate_inputs(current: sqlite3.Connection, legacy: sqlite3.Connection) -> None:
    for table in CORE_TABLES:
        current_sql = table_sql(current, table)
        legacy_sql = table_sql(legacy, table)
        if not current_sql or not legacy_sql:
            raise RuntimeError(f"required table is missing: {table}")
        if current_sql != legacy_sql:
            raise RuntimeError(f"core table schema differs: {table}")


def copy_database(source: sqlite3.Connection, destination: Path) -> None:
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()


def get_columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in db.execute(f'PRAGMA table_info("{table}")')]


def copy_missing_streamers(
    target: sqlite3.Connection, legacy: sqlite3.Connection
) -> int:
    columns = get_columns(legacy, "streamer")
    placeholders = ", ".join("?" for _ in columns)
    names = ", ".join(f'"{column}"' for column in columns)
    existing = {
        row[0] for row in target.execute("SELECT vtuber_id FROM streamer").fetchall()
    }
    rows = [
        row
        for row in legacy.execute(f"SELECT {names} FROM streamer").fetchall()
        if row[columns.index("vtuber_id")] not in existing
    ]
    target.executemany(
        f"INSERT INTO streamer ({names}) VALUES ({placeholders})", rows
    )
    return len(rows)


def merge_lookup_table(
    target: sqlite3.Connection,
    legacy: sqlite3.Connection,
    table: str,
    id_column: str,
    value_column: str,
) -> dict[int, int]:
    values = {
        value: identifier
        for identifier, value in target.execute(
            f'SELECT "{id_column}", "{value_column}" FROM "{table}"'
        )
    }
    mapping: dict[int, int] = {}
    for old_id, value in legacy.execute(
        f'SELECT "{id_column}", "{value_column}" FROM "{table}"'
    ):
        new_id = values.get(value)
        if new_id is None:
            cursor = target.execute(
                f'INSERT INTO "{table}" ("{value_column}") VALUES (?)', (value,)
            )
            new_id = cursor.lastrowid
            values[value] = new_id
        mapping[old_id] = new_id
    return mapping


def observed_intervals(
    db: sqlite3.Connection,
) -> tuple[dict[int, tuple[datetime, datetime]], dict[int, datetime | None]]:
    intervals: dict[int, tuple[datetime, datetime]] = {}
    first_captures: dict[int, datetime | None] = {}
    rows = db.execute(
        """
        SELECT stream.stream_id,
               COALESCE(MIN(stream_snapshot.captured_at), stream.started_at,
                        stream.first_seen_at),
               COALESCE(MAX(stream_snapshot.captured_at), stream.ended_at,
                        stream.last_seen_at, stream.started_at,
                        stream.first_seen_at),
               MIN(stream_snapshot.captured_at)
        FROM stream
        LEFT JOIN stream_snapshot USING (stream_id)
        GROUP BY stream.stream_id
        """
    )
    for stream_id, start, end, first_capture in rows:
        parsed_start = parse_time(start)
        parsed_end = parse_time(end)
        if parsed_start is None or parsed_end is None:
            continue
        if parsed_end < parsed_start:
            parsed_end = parsed_start
        intervals[stream_id] = (parsed_start, parsed_end)
        first_captures[stream_id] = parse_time(first_capture)
    return intervals, first_captures


def streams_by_member_platform(
    db: sqlite3.Connection,
) -> dict[tuple[str, str], list[int]]:
    result: dict[tuple[str, str], list[int]] = defaultdict(list)
    for stream_id, vtuber_id, platform in db.execute(
        "SELECT stream_id, vtuber_id, platform FROM stream"
    ):
        result[(vtuber_id, platform)].append(stream_id)
    return result


def merge_streams(
    target: sqlite3.Connection, legacy: sqlite3.Connection
) -> tuple[dict[int, int], dict[int, datetime | None], list[dict[str, object]], int]:
    current_intervals, current_first_captures = observed_intervals(target)
    legacy_intervals, _ = observed_intervals(legacy)
    current_groups = streams_by_member_platform(target)
    stream_columns = [
        column for column in get_columns(legacy, "stream") if column != "stream_id"
    ]
    select_columns = ", ".join(f'"{column}"' for column in stream_columns)
    placeholders = ", ".join("?" for _ in stream_columns)
    stream_mapping: dict[int, int] = {}
    matched_cutoffs: dict[int, datetime | None] = {}
    matches: list[dict[str, object]] = []
    inserted = 0

    legacy_identity = {
        stream_id: (vtuber_id, platform)
        for stream_id, vtuber_id, platform in legacy.execute(
            "SELECT stream_id, vtuber_id, platform FROM stream"
        )
    }
    legacy_rows = legacy.execute(
        f"SELECT stream_id, {select_columns} FROM stream ORDER BY stream_id"
    )
    for old_stream_id, *values in legacy_rows:
        identity = legacy_identity[old_stream_id]
        legacy_interval = legacy_intervals.get(old_stream_id)
        candidates: list[int] = []
        if legacy_interval:
            legacy_start, legacy_end = legacy_interval
            for current_stream_id in current_groups.get(identity, ()):
                current_interval = current_intervals.get(current_stream_id)
                if not current_interval:
                    continue
                current_start, current_end = current_interval
                if current_end >= legacy_start and legacy_end >= current_start:
                    candidates.append(current_stream_id)
        if len(candidates) > 1:
            raise RuntimeError(
                f"ambiguous stream match for legacy stream {old_stream_id}: {candidates}"
            )
        if candidates:
            current_stream_id = candidates[0]
            stream_mapping[old_stream_id] = current_stream_id
            matched_cutoffs[old_stream_id] = current_first_captures.get(current_stream_id)
            matches.append(
                {
                    "legacy_stream_id": old_stream_id,
                    "current_stream_id": current_stream_id,
                    "vtuber_id": identity[0],
                    "platform": identity[1],
                    "current_first_capture": (
                        current_first_captures[current_stream_id].isoformat(sep=" ")
                        if current_first_captures.get(current_stream_id)
                        else None
                    ),
                }
            )
            continue
        cursor = target.execute(
            f"INSERT INTO stream ({select_columns}) VALUES ({placeholders})", values
        )
        stream_mapping[old_stream_id] = cursor.lastrowid
        inserted += 1
    return stream_mapping, matched_cutoffs, matches, inserted


def merge_snapshots(
    target: sqlite3.Connection,
    legacy: sqlite3.Connection,
    stream_mapping: dict[int, int],
    matched_cutoffs: dict[int, datetime | None],
    title_mapping: dict[int, int],
    category_mapping: dict[int, int],
    tags_mapping: dict[int, int],
) -> tuple[int, int]:
    inserted = 0
    skipped_overlap = 0
    rows = legacy.execute(
        """
        SELECT stream_id, vtuber_id, platform, viewer_count, captured_at,
               title_id, category_id, tags_id
        FROM stream_snapshot ORDER BY snapshot_id
        """
    )
    batch: list[tuple[object, ...]] = []
    for old_stream_id, vtuber_id, platform, viewers, captured_at, title_id, category_id, tags_id in rows:
        cutoff = matched_cutoffs.get(old_stream_id)
        if cutoff is not None and parse_time(captured_at) >= cutoff:
            skipped_overlap += 1
            continue
        batch.append(
            (
                stream_mapping[old_stream_id],
                vtuber_id,
                platform,
                viewers,
                captured_at,
                title_mapping.get(title_id),
                category_mapping.get(category_id),
                tags_mapping.get(tags_id),
            )
        )
        if len(batch) >= 5000:
            target.executemany(
                """
                INSERT INTO stream_snapshot (
                    stream_id, vtuber_id, platform, viewer_count, captured_at,
                    title_id, category_id, tags_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                batch,
            )
            inserted += len(batch)
            batch.clear()
    if batch:
        target.executemany(
            """
            INSERT INTO stream_snapshot (
                stream_id, vtuber_id, platform, viewer_count, captured_at,
                title_id, category_id, tags_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            batch,
        )
        inserted += len(batch)
    return inserted, skipped_overlap


def merge_working(target: sqlite3.Connection, legacy: sqlite3.Connection) -> int:
    columns = [
        column for column in get_columns(legacy, "working") if column != "working_id"
    ]
    names = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    rows = legacy.execute(f"SELECT {names} FROM working ORDER BY working_id").fetchall()
    target.executemany(
        f"INSERT INTO working ({names}) VALUES ({placeholders})", rows
    )
    return len(rows)


def counts(db: sqlite3.Connection) -> dict[str, int]:
    return {
        table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        for table in CORE_TABLES
    }


def main() -> int:
    args = parse_args()
    current_path = args.current.resolve()
    legacy_path = args.legacy.resolve()
    output_path = args.output.resolve()
    report_path = args.report.resolve()
    for path, label in ((current_path, "current"), (legacy_path, "legacy")):
        if not path.is_file():
            raise FileNotFoundError(f"{label} database not found: {path}")
    if len({current_path, legacy_path, output_path}) != 3:
        raise ValueError("current, legacy, and output databases must be different")
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(
            f"output already exists: {output_path} (use --overwrite to replace it)"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    if temporary.exists():
        temporary.unlink()

    current = sqlite3.connect(database_uri(current_path), uri=True)
    legacy = sqlite3.connect(database_uri(legacy_path), uri=True)
    try:
        validate_inputs(current, legacy)
        source_counts = {"current": counts(current), "legacy": counts(legacy)}
        copy_database(current, temporary)
    finally:
        current.close()

    target = sqlite3.connect(temporary)
    target.execute("PRAGMA foreign_keys=ON")
    try:
        target.execute("BEGIN IMMEDIATE")
        added_streamers = copy_missing_streamers(target, legacy)
        title_mapping = merge_lookup_table(
            target, legacy, "stream_title", "title_id", "title"
        )
        category_mapping = merge_lookup_table(
            target, legacy, "stream_category", "category_id", "category"
        )
        tags_mapping = merge_lookup_table(
            target, legacy, "stream_tags", "tags_id", "tags"
        )
        stream_mapping, matched_cutoffs, matches, inserted_streams = merge_streams(
            target, legacy
        )
        inserted_snapshots, skipped_snapshots = merge_snapshots(
            target,
            legacy,
            stream_mapping,
            matched_cutoffs,
            title_mapping,
            category_mapping,
            tags_mapping,
        )
        inserted_working = merge_working(target, legacy)
        target.commit()

        integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = target.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_key_errors:
            raise RuntimeError(
                f"validation failed: integrity={integrity}, "
                f"foreign_key_errors={len(foreign_key_errors)}"
            )
        output_counts = counts(target)
        stream_range = target.execute(
            "SELECT MIN(started_at), MAX(COALESCE(ended_at,last_seen_at,started_at)) FROM stream"
        ).fetchone()
        snapshot_range = target.execute(
            "SELECT MIN(captured_at), MAX(captured_at) FROM stream_snapshot"
        ).fetchone()
        report = {
            "current": str(current_path),
            "legacy": str(legacy_path),
            "output": str(output_path),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source_counts": source_counts,
            "merge": {
                "streamers_inserted": added_streamers,
                "legacy_streams_inserted": inserted_streams,
                "legacy_streams_matched": len(matches),
                "legacy_snapshots_inserted": inserted_snapshots,
                "overlapping_legacy_snapshots_skipped": skipped_snapshots,
                "legacy_working_rows_inserted": inserted_working,
                "matched_streams": matches,
            },
            "output_counts": output_counts,
            "stream_range": stream_range,
            "snapshot_range": snapshot_range,
            "integrity_check": integrity,
            "foreign_key_errors": len(foreign_key_errors),
        }
    except Exception:
        target.rollback()
        target.close()
        legacy.close()
        if temporary.exists():
            temporary.unlink()
        raise
    else:
        target.close()
        legacy.close()

    os.replace(temporary, output_path)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Merge failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
