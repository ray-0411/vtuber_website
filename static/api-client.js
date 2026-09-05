(() => {
  const nativeFetch = window.fetch.bind(window);
  const config = window.DASHBOARD_SUPABASE || {};
  const enabled = Boolean(config.url && config.publishableKey);

  function rpcFor(input) {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    const path = url.pathname;
    if (path === "/api/overview") return ["dashboard_overview", {}];
    if (path === "/api/live") return ["dashboard_live", {}];
    if (path === "/api/rankings/weekly") return ["dashboard_stream_rankings", {
      ranking_period: url.searchParams.get("period") || "last_week",
    }];
    if (path === "/api/rankings/monthly-average") return ["dashboard_monthly_average_rankings", {}];
    if (path === "/api/rankings/members") return ["dashboard_member_rankings", {
      ranking_metric: url.searchParams.get("metric") || "average_viewers",
      ranking_platform: url.searchParams.get("platform") || "combined",
      analysis_period: url.searchParams.get("period") || "1m",
    }];
    if (path === "/api/groups") return ["dashboard_groups", {}];

    let match = path.match(/^\/api\/streams\/(\d+)\/snapshots$/);
    if (match) return ["dashboard_stream_snapshots", {requested_stream_id: Number(match[1])}];

    match = path.match(/^\/api\/groups\/([^/]+)$/);
    if (match) return ["dashboard_group_members", {
      requested_group: decodeURIComponent(match[1]),
      analysis_period: url.searchParams.get("period") || "1m",
    }];

    match = path.match(/^\/api\/groups\/([^/]+)\/analysis$/);
    if (match) return ["dashboard_analysis", {
      requested_group: decodeURIComponent(match[1]),
      requested_vtuber: null,
      analysis_period: url.searchParams.get("period") || "1m",
    }];

    match = path.match(/^\/api\/groups\/([^/]+)\/members\/([^/]+)\/history$/);
    if (match) return ["dashboard_member_month_history", {
      requested_group: decodeURIComponent(match[1]),
      requested_vtuber: decodeURIComponent(match[2]),
      requested_month: url.searchParams.get("month") || null,
    }];

    match = path.match(/^\/api\/groups\/([^/]+)\/members\/([^/]+)$/);
    if (match) return ["dashboard_analysis", {
      requested_group: decodeURIComponent(match[1]),
      requested_vtuber: decodeURIComponent(match[2]),
      analysis_period: url.searchParams.get("period") || "1m",
    }];
    return null;
  }

  window.dashboardFetch = async (input, init) => {
    const rpc = rpcFor(input);
    if (!enabled || !rpc) return nativeFetch(input, init);
    const [name, parameters] = rpc;
    const response = await nativeFetch(
      `${config.url.replace(/\/$/, "")}/rest/v1/rpc/${name}`,
      {
        method: "POST",
        headers: {
          apikey: config.publishableKey,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(parameters),
      },
    );
    if (response.ok) return response;
    let error;
    try {
      const details = await response.clone().json();
      error = details.message || details.hint || details.code;
    } catch {
      error = response.statusText;
    }
    return new Response(JSON.stringify({error}), {
      status: response.status,
      headers: {"Content-Type": "application/json"},
    });
  };
})();
