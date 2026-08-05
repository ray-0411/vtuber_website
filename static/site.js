(() => {
  const onGitHubPages = location.hostname.endsWith(".github.io");
  const basePath = onGitHubPages ? "/vtuber_website" : "";
  window.dashboardPath = path => `${basePath}${path.startsWith("/") ? path : `/${path}`}` || "/";
  window.dashboardRoutePath = () => {
    const routed = new URLSearchParams(location.search).get("route");
    if (routed) return routed.split(/[?#]/, 1)[0];
    const pathname = location.pathname;
    return basePath && pathname.startsWith(basePath)
      ? pathname.slice(basePath.length) || "/"
      : pathname;
  };
  window.dashboardSearchParams = () => {
    const outer = new URLSearchParams(location.search);
    const routed = outer.get("route");
    return routed && routed.includes("?")
      ? new URLSearchParams(routed.slice(routed.indexOf("?") + 1).split("#", 1)[0])
      : outer;
  };

  window.dashboardParseTime = value => {
    if (!value) return null;
    const text = String(value).trim();
    const normalized = /^\d{4}-\d{2}-\d{2}$/.test(text)
      ? `${text}T00:00:00`
      : text.includes("T") ? text : text.replace(" ", "T");
    const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(normalized);
    const parsed = new Date(hasTimezone ? normalized : `${normalized}+08:00`);
    return Number.isNaN(parsed.valueOf()) ? null : parsed;
  };

  function taipeiParts(value) {
    const parsed = dashboardParseTime(value);
    if (!parsed) return null;
    return Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit",
      minute: "2-digit", second: "2-digit", hour12: false,
      timeZone: "Asia/Taipei",
    }).formatToParts(parsed).map(part => [part.type, part.value]));
  }

  window.dashboardDateTime = value => {
    const parts = taipeiParts(value);
    return parts
      ? `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`
      : "—";
  };
  window.dashboardDate = value => {
    const parts = taipeiParts(value);
    return parts ? `${parts.year}-${parts.month}-${parts.day}` : "—";
  };
  window.dashboardClockTime = value => {
    const parts = taipeiParts(value);
    return parts ? `${parts.hour}:${parts.minute}:${parts.second}` : "—";
  };
})();
