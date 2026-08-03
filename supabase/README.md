# Supabase migration

This directory contains the staged migration from the local merged SQLite
databases to Supabase PostgreSQL.

## Data flow

1. `refresh_merged_data.bat` remains the source-of-truth build process.
2. `data/merged_live_data.db` provides the `dashboard` schema tables.
3. `data/merged_analytics_cache.db` provides the `analytics` schema tables.
4. A later sync command will upload both completed files in one PostgreSQL
   transaction.

The local dashboard continues to use SQLite until the public Supabase API and
GitHub Pages frontend have both been verified.

## Excluded local tables

- `working`: collector execution history; no current dashboard feature uses it.
- `cache_metadata`: describes the replaceable local cache file, not website data.

## Security boundary

Raw tables live in the non-public `dashboard` and `analytics` schemas. Browser
clients will not receive database credentials or direct table grants. A later
migration will expose only reviewed, read-only views and RPC functions through
the `public` schema.

Do not commit the Supabase database password, direct connection URL, service
role key, or `.env` files.

## Local validation

The synchronization command includes a network-free validation mode. It checks
every configured table and converts all boolean, date, and timestamp values:

```powershell
python scripts\sync_merged_to_postgres.py --dry-run
```

`working` and `cache_metadata` are never part of the synchronization manifest.
Snapshots are included by default to preserve the viewer-history modal. They can
be omitted explicitly in a future deployment with `--skip-snapshots`.

## Real synchronization (later step)

Install the official Psycopg binary package and provide the connection string
through either the current process environment or the Git-ignored local file
`.env.supabase.local`:

```powershell
python -m pip install -r requirements-sync.txt
python scripts\sync_merged_to_postgres.py --check-connection
python scripts\sync_merged_to_postgres.py --confirm-replace
```

Local file format:

```dotenv
SUPABASE_DB_URL=postgresql://...
```

The connection check verifies all target tables without changing data. The
explicit confirmation flag is required for the real synchronization because it
replaces all data in the managed Supabase tables.

The PostgreSQL schema migration must be applied before the first real sync. The
command obtains a transaction-scoped advisory lock, truncates the managed target
tables, uploads with PostgreSQL COPY, verifies row counts, and commits only when
all checks pass.
