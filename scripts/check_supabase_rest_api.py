"""Exercise every dashboard RPC through the public Supabase REST gateway."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
TEST_ORIGIN = "https://example.github.io"


def read_config() -> tuple[str, str]:
    text = (ROOT / "static" / "supabase-config.js").read_text(encoding="utf-8")
    url = re.search(r'url:\s*"([^"]+)"', text)
    key = re.search(r'publishableKey:\s*"([^"]+)"', text)
    if not url or not url.group(1) or not key or not key.group(1):
        raise RuntimeError("Fill static/supabase-config.js before testing")
    if not key.group(1).startswith(("sb_publishable_", "eyJ")):
        raise RuntimeError("Expected a publishable key or legacy anon key")
    return url.group(1).rstrip("/"), key.group(1)


def sample_ids() -> tuple[str, str, int]:
    database = ROOT / "data" / "merged_live_data.db"
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as db:
        row = db.execute(
            "select s.group_name, s.vtuber_id, st.stream_id "
            "from streamer s join stream st on st.vtuber_id=s.vtuber_id "
            "order by st.started_at desc limit 1"
        ).fetchone()
    if row is None:
        raise RuntimeError("No local sample stream is available")
    return row


def rpc(base_url: str, key: str, name: str, parameters: dict) -> tuple[object, str | None]:
    request = Request(
        f"{base_url}/rest/v1/rpc/{name}",
        data=json.dumps(parameters).encode("utf-8"),
        headers={
            "apikey": key,
            "Content-Type": "application/json",
            "Origin": TEST_ORIGIN,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.load(response), response.headers.get("Access-Control-Allow-Origin")
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"REST RPC {name} failed with HTTP {error.code}: {details}") from error


def main() -> int:
    base_url, key = read_config()
    group, vtuber, stream_id = sample_ids()
    checks = (
        ("dashboard_overview", {}, dict),
        ("dashboard_live", {}, list),
        ("dashboard_weekly_rankings", {}, dict),
        ("dashboard_monthly_average_rankings", {}, dict),
        ("dashboard_groups", {}, list),
        ("dashboard_group_members", {"requested_group": group, "analysis_period": "1m"}, list),
        ("dashboard_stream_snapshots", {"requested_stream_id": stream_id}, dict),
        ("dashboard_member_month_history", {"requested_group": group, "requested_vtuber": vtuber, "requested_month": None}, dict),
        ("dashboard_analysis", {"requested_group": group, "requested_vtuber": vtuber, "analysis_period": "1m"}, dict),
        ("dashboard_analysis", {"requested_group": group, "requested_vtuber": None, "analysis_period": "1m"}, dict),
    )
    cors = None
    for name, parameters, expected_type in checks:
        payload, cors = rpc(base_url, key, name, parameters)
        if not isinstance(payload, expected_type):
            raise RuntimeError(f"REST RPC {name} returned an unexpected JSON type")
        print(f"Public REST RPC {name}: OK")
    if cors not in {"*", TEST_ORIGIN}:
        raise RuntimeError(f"Unexpected CORS header: {cors!r}")
    print("Browser CORS access: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
