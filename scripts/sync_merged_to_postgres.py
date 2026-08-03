#!/usr/bin/env python3
"""Synchronize completed merged SQLite databases to Supabase PostgreSQL."""

from __future__ import annotations

import argparse
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Iterator


TAIPEI = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class TableSpec:
    source: str
    target: str
    columns: tuple[str, ...]
    boolean_columns: frozenset[str] = frozenset()
    timestamp_columns: frozenset[str] = frozenset()
    date_columns: frozenset[str] = frozenset()


TIMESTAMPS = {
    "started_at",
    "ended_at",
    "first_seen_at",
    "last_seen_at",
    "created_at",
    "updated_at",
    "captured_at",
    "last_checked_at",
    "last_live_at",
    "synced_at",
    "youtube_count_at",
    "twitch_count_at",
    "youtube_avatar_at",
    "twitch_avatar_at",
    "observed_end_at",
    "first_capture",
    "last_capture",
}


def spec(source: str, target: str, columns: str, **kwargs) -> TableSpec:
    names = tuple(columns.split())
    timestamps = frozenset(name for name in names if name in TIMESTAMPS)
    return TableSpec(
        source=source,
        target=target,
        columns=names,
        timestamp_columns=timestamps,
        **kwargs,
    )


DASHBOARD_TABLES = (
    spec(
        "streamer",
        "dashboard.streamer",
        "vtuber_id group_name name youtube_url youtube_channel_id twitch_url "
        "twitch_login enabled display_order note synced_at",
        boolean_columns=frozenset({"enabled"}),
    ),
    spec("group_settings", "dashboard.group_settings", "group_name display_order note"),
    spec("stream_title", "dashboard.stream_title", "title_id title"),
    spec("stream_category", "dashboard.stream_category", "category_id category"),
    spec("stream_tags", "dashboard.stream_tags", "tags_id tags"),
    spec(
        "stream",
        "dashboard.stream",
        "stream_id vtuber_id platform platform_stream_id stream_url title category "
        "tags started_at ended_at first_seen_at last_seen_at created_at updated_at",
    ),
    spec(
        "stream_snapshot",
        "dashboard.stream_snapshot",
        "snapshot_id stream_id vtuber_id platform viewer_count captured_at title_id "
        "category_id tags_id",
    ),
    spec(
        "current_live_status",
        "dashboard.current_live_status",
        "vtuber_id platform is_live stream_id viewer_count stream_url title_id "
        "category_id tags_id started_at last_checked_at last_live_at",
        boolean_columns=frozenset({"is_live"}),
    ),
    spec(
        "streamer_audience",
        "dashboard.streamer_audience",
        "vtuber_id name group_table youtube_channel_id youtube_subscribers "
        "youtube_source youtube_count_at youtube_error twitch_login twitch_followers "
        "twitch_source twitch_count_at twitch_error updated_at youtube_url "
        "youtube_avatar_url youtube_avatar_width youtube_avatar_height "
        "youtube_avatar_source youtube_avatar_at youtube_avatar_error "
        "twitch_avatar_url twitch_avatar_source twitch_avatar_at twitch_avatar_error",
    ),
)


ANALYTICS_TABLES = (
    spec(
        "stream_stats",
        "analytics.stream_stats",
        "stream_id vtuber_id group_name member_name platform stream_url title category "
        "started_at ended_at observed_end_at peak_viewers average_viewers snapshot_count "
        "first_capture last_capture observed_hours",
    ),
    spec(
        "stream_calendar_day",
        "analytics.stream_calendar_day",
        "stream_id broadcast_day",
        date_columns=frozenset({"broadcast_day"}),
    ),
    spec(
        "stream_active_interval",
        "analytics.stream_active_interval",
        "stream_id minute_of_day",
    ),
)


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=root / "data" / "merged_live_data.db",
    )
    parser.add_argument(
        "--analytics-cache",
        type=Path,
        default=root / "data" / "merged_analytics_cache.db",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate all source rows and print counts without connecting",
    )
    parser.add_argument(
        "--check-connection",
        action="store_true",
        help="connect and verify target tables without changing data",
    )
    parser.add_argument(
        "--confirm-replace",
        action="store_true",
        help="confirm replacing all managed Supabase table data",
    )
    parser.add_argument(
        "--skip-snapshots",
        action="store_true",
        help="do not upload stream_snapshot rows",
    )
    return parser.parse_args()


def load_local_environment() -> None:
    env_file = Path(__file__).resolve().parents[1] / ".env.supabase.local"
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value.startswith(("'", '"')):
            value = value[1:-1]
        if key == "SUPABASE_DB_URL":
            os.environ.setdefault(key, value)


def connect_sqlite(path: Path) -> sqlite3.Connection:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"SQLite database not found: {resolved}")
    connection = sqlite3.connect(
        f"file:{resolved.as_posix()}?mode=ro", uri=True, timeout=10
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def parse_timestamp(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    text = str(value)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TAIPEI)
    return parsed.astimezone(timezone.utc)


def convert_value(specification: TableSpec, column: str, value: object) -> object:
    if value is None:
        return None
    if column in specification.boolean_columns:
        return bool(value)
    if column in specification.timestamp_columns:
        return parse_timestamp(value)
    if column in specification.date_columns:
        return date.fromisoformat(str(value))
    return value


def source_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def validate_spec(connection: sqlite3.Connection, specification: TableSpec) -> None:
    available = source_columns(connection, specification.source)
    if not available:
        raise RuntimeError(f"Source table is missing: {specification.source}")
    missing = set(specification.columns) - available
    if missing:
        raise RuntimeError(
            f"{specification.source} is missing columns: {', '.join(sorted(missing))}"
        )


def rows(
    connection: sqlite3.Connection, specification: TableSpec
) -> Iterator[tuple[object, ...]]:
    names = ", ".join(f'"{column}"' for column in specification.columns)
    cursor = connection.execute(f'SELECT {names} FROM "{specification.source}"')
    for row in cursor:
        yield tuple(
            convert_value(specification, column, row[column])
            for column in specification.columns
        )


def selected_tables(skip_snapshots: bool) -> tuple[TableSpec, ...]:
    dashboard = tuple(
        table
        for table in DASHBOARD_TABLES
        if not (skip_snapshots and table.source == "stream_snapshot")
    )
    return dashboard + ANALYTICS_TABLES


def validate_sources(
    main: sqlite3.Connection,
    analytics: sqlite3.Connection,
    tables: tuple[TableSpec, ...],
    report: Callable[[str], None] = print,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        source = analytics if table in ANALYTICS_TABLES else main
        validate_spec(source, table)
        count = 0
        for _ in rows(source, table):
            count += 1
        counts[table.target] = count
        report(f"Validated {table.target}: {count:,} rows")
    return counts


def copy_table(cursor, source, specification: TableSpec) -> int:
    columns = ", ".join(f'"{column}"' for column in specification.columns)
    count = 0
    with cursor.copy(
        f"COPY {specification.target} ({columns}) FROM STDIN"
    ) as copy:
        for row in rows(source, specification):
            copy.write_row(row)
            count += 1
    return count


def postgres_driver_and_url():
    database_url = os.environ.get("SUPABASE_DB_URL")
    if not database_url:
        raise RuntimeError(
            "SUPABASE_DB_URL is required; set it in .env.supabase.local"
        )
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            'Install sync dependencies with: pip install -r requirements-sync.txt'
        ) from exc
    return psycopg, database_url


def check_postgres(tables: tuple[TableSpec, ...]) -> None:
    psycopg, database_url = postgres_driver_and_url()
    with psycopg.connect(database_url) as postgres:
        with postgres.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user")
            database_name, database_user = cursor.fetchone()
            print(f"Connected to database {database_name} as {database_user}.")
            for table in tables:
                cursor.execute("SELECT to_regclass(%s)", (table.target,))
                if cursor.fetchone()[0] is None:
                    raise RuntimeError(f"Target table is missing: {table.target}")
                cursor.execute(f"SELECT COUNT(*) FROM {table.target}")
                print(f"Found {table.target}: {cursor.fetchone()[0]:,} rows")
    print("Connection check completed; no data was changed.")


def sync_postgres(
    main: sqlite3.Connection,
    analytics: sqlite3.Connection,
    tables: tuple[TableSpec, ...],
    expected: dict[str, int],
) -> None:
    psycopg, database_url = postgres_driver_and_url()

    targets = ", ".join(table.target for table in reversed(tables))
    with psycopg.connect(database_url) as postgres:
        with postgres.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (847_041_103,))
            cursor.execute(f"TRUNCATE TABLE {targets} CASCADE")
            for table in tables:
                source = analytics if table in ANALYTICS_TABLES else main
                copied = copy_table(cursor, source, table)
                print(f"Copied {table.target}: {copied:,} rows")
            for target, source_count in expected.items():
                cursor.execute(f"SELECT COUNT(*) FROM {target}")
                target_count = cursor.fetchone()[0]
                if target_count != source_count:
                    raise RuntimeError(
                        f"Count mismatch for {target}: source={source_count}, "
                        f"target={target_count}"
                    )
        postgres.commit()


def main() -> int:
    args = parse_args()
    load_local_environment()
    tables = selected_tables(args.skip_snapshots)
    if args.check_connection:
        check_postgres(tables)
        return 0
    if not args.dry_run and not args.confirm_replace:
        raise RuntimeError(
            "Real synchronization replaces managed Supabase data; "
            "run again with --confirm-replace"
        )
    with connect_sqlite(args.database) as main_db, connect_sqlite(
        args.analytics_cache
    ) as analytics_db:
        expected = validate_sources(main_db, analytics_db, tables)
        if args.dry_run:
            print("Dry run completed; no network connection was made.")
            return 0
        sync_postgres(main_db, analytics_db, tables, expected)
    print("Supabase synchronization completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
