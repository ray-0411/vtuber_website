"""Check public dashboard RPCs as Supabase's anonymous database role."""

from __future__ import annotations

from sync_merged_to_postgres import load_local_environment, postgres_driver_and_url


def main() -> int:
    load_local_environment()
    psycopg, database_url = postgres_driver_and_url()
    checks = (
        ("dashboard_overview", "select public.dashboard_overview()"),
        ("dashboard_live", "select public.dashboard_live()"),
        ("dashboard_weekly_rankings", "select public.dashboard_weekly_rankings()"),
        (
            "dashboard_monthly_average_rankings",
            "select public.dashboard_monthly_average_rankings()",
        ),
        ("dashboard_groups", "select public.dashboard_groups()"),
    )
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "select s.group_name, s.vtuber_id, stats.stream_id "
                "from dashboard.streamer s "
                "join analytics.stream_stats stats on stats.vtuber_id=s.vtuber_id "
                "order by stats.started_at desc limit 1"
            )
            sample_group, sample_vtuber, sample_stream = cursor.fetchone()
            cursor.execute("set local role anon")
            for name, query in checks:
                cursor.execute(query)
                payload = cursor.fetchone()[0]
                size = len(payload) if isinstance(payload, list) else len(payload.keys())
                print(f"Anonymous RPC {name}: OK ({size} top-level items)")
            detail_checks = (
                (
                    "dashboard_group_members",
                    "select public.dashboard_group_members(%s, %s)",
                    (sample_group, "1m"),
                    {"list"},
                ),
                (
                    "dashboard_stream_snapshots",
                    "select public.dashboard_stream_snapshots(%s)",
                    (sample_stream,),
                    {"stream", "snapshots"},
                ),
                (
                    "dashboard_member_month_history",
                    "select public.dashboard_member_month_history(%s, %s, null)",
                    (sample_group, sample_vtuber),
                    {"profile", "month", "available", "calendar", "streams"},
                ),
                (
                    "dashboard_member_analysis",
                    "select public.dashboard_analysis(%s, %s, %s)",
                    (sample_group, sample_vtuber, "1m"),
                    {"profile", "summary", "streams", "daily", "categories", "active_intervals", "calendar", "period"},
                ),
                (
                    "dashboard_group_analysis",
                    "select public.dashboard_analysis(%s, null, %s)",
                    (sample_group, "1m"),
                    {"profile", "summary", "streams", "daily", "categories", "active_intervals", "calendar", "period"},
                ),
            )
            for name, query, parameters, required_keys in detail_checks:
                cursor.execute(query, parameters)
                payload = cursor.fetchone()[0]
                if payload is None:
                    raise RuntimeError(f"{name} unexpectedly returned null")
                if required_keys == {"list"}:
                    if not isinstance(payload, list):
                        raise RuntimeError(f"{name} did not return a list")
                elif not required_keys.issubset(payload):
                    raise RuntimeError(f"{name} is missing expected keys")
                print(f"Anonymous RPC {name}: OK")
            try:
                cursor.execute("select count(*) from dashboard.streamer")
            except psycopg.errors.InsufficientPrivilege:
                print("Anonymous raw-table access: blocked as expected")
                connection.rollback()
            else:
                raise RuntimeError("Anonymous role can unexpectedly read raw tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
