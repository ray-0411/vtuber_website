"""Apply one reviewed SQL migration to the configured Supabase database."""

from __future__ import annotations

import argparse
from pathlib import Path

from sync_merged_to_postgres import load_local_environment, postgres_driver_and_url


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("migration", type=Path)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    migration = args.migration.resolve()
    migrations_root = (root / "supabase" / "migrations").resolve()
    if migrations_root not in migration.parents or migration.suffix.lower() != ".sql":
        raise RuntimeError("Migration must be a .sql file in supabase/migrations")
    if not args.confirm:
        raise RuntimeError("Review the migration, then run again with --confirm")

    load_local_environment()
    psycopg, database_url = postgres_driver_and_url()
    sql = migration.read_text(encoding="utf-8")
    with psycopg.connect(database_url) as connection:
        connection.execute(sql)
        connection.commit()
    print(f"Applied {migration.name} successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
