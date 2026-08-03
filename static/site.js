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
})();
