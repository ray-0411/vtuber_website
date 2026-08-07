#!/usr/bin/env python3
"""Move members outside selected Groups into `other` in a merged database."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


DEFAULT_GROUPS = ("meridian", "squarelive", "envision", "thebox")


def parse_args() -> argparse.Namespace:
    data_dir = Path(__file__).resolve().parents[1] / "data"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=data_dir / "merged_live_data.db")
    parser.add_argument("--keep", nargs="+", default=DEFAULT_GROUPS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database = args.database.resolve()
    if not database.is_file():
        raise FileNotFoundError(f"Database not found: {database}")
    kept = tuple(dict.fromkeys(group.strip() for group in args.keep if group.strip()))
    if not kept or "other" in kept:
        raise ValueError("--keep must contain named Groups and must not include other")

    placeholders = ", ".join("?" for _ in kept)
    with sqlite3.connect(database) as db:
        db.execute("BEGIN IMMEDIATE")
        before = db.execute(
            f"SELECT COUNT(*) FROM streamer WHERE group_name <> 'other' AND group_name NOT IN ({placeholders})",
            kept,
        ).fetchone()[0]
        db.execute(
            f"UPDATE streamer SET group_name = 'other' WHERE group_name <> 'other' AND group_name NOT IN ({placeholders})",
            kept,
        )
        db.execute(
            f"DELETE FROM group_settings WHERE group_name <> 'other' AND group_name NOT IN ({placeholders})",
            kept,
        )
        db.execute(
            "INSERT OR IGNORE INTO group_settings (group_name) VALUES ('other')"
        )
        db.commit()
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Database integrity check failed: {integrity}")
        groups = db.execute(
            "SELECT group_name, COUNT(*) FROM streamer GROUP BY group_name ORDER BY group_name"
        ).fetchall()

    print(f"Database: {database}")
    print(f"Members moved to other: {before}")
    print(f"Remaining Groups: {groups}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
