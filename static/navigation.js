(() => {
  const button = document.querySelector(".menu-button");
  if (!button) return;
  const drawer = document.querySelector(".nav-drawer");
  const overlay = document.querySelector(".drawer-overlay");
  const close = document.querySelector(".drawer-close");
  const list = document.querySelector(".drawer-groups");
  const foot = document.querySelector(".drawer-foot");
  let loaded = false;

  const topbar = document.querySelector(".topbar");
  if (topbar && !topbar.querySelector(".status")) {
    const status = document.createElement("div");
    const commit = window.DASHBOARD_BUILD?.commit || "local";
    status.className = "status global-status";
    status.innerHTML = `<i></i><span class="global-sync-label">正在連線資料庫…</span><span class="status-divider">·</span><a class="global-build-version">版本 ${commit}</a>`;
    const versionLink = status.querySelector(".global-build-version");
    if (commit !== "local") {
      versionLink.href = `https://github.com/ray-0411/vtuber_website/commit/${encodeURIComponent(commit)}`;
      versionLink.target = "_blank";
      versionLink.rel = "noreferrer";
    }
    const nav = topbar.querySelector("nav");
    if (nav) {
      const meta = document.createElement("div");
      meta.className = "topbar-meta";
      nav.before(meta);
      meta.append(nav, status);
    } else {
      topbar.append(status);
    }
    dashboardFetch("/api/overview").then(response => {
      if (!response.ok) throw new Error("讀取失敗");
      return response.json();
    }).then(data => {
      status.querySelector(".global-sync-label").textContent = `最近更新 ${dashboardDateTime(data.last_checked_at)}`;
    }).catch(() => {
      status.querySelector(".global-sync-label").textContent = "更新時間讀取失敗";
    });
  }

  const safe = value => String(value ?? "").replace(/[&<>"']/g, c => (
    {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]
  ));
  const pretty = value => value.split("_").map(
    word => word.charAt(0).toUpperCase() + word.slice(1)
  ).join(" ");
  const current = dashboardRoutePath().match(/^\/groups\/([^/]+)/)?.[1];
  if (list && !document.querySelector(".drawer-ranking")) {
    const ranking = document.createElement("a");
    const rankingActive = /^\/rankings(?:\.html)?\/?$/.test(dashboardRoutePath());
    ranking.className = `drawer-ranking ${rankingActive ? "active" : ""}`;
    ranking.href = dashboardPath("/rankings");
    ranking.innerHTML = `<span class="drawer-ranking-mark">#</span><span><strong>排行榜</strong><small>各項排名與統計</small></span><small>→</small>`;
    list.after(ranking);
  }
  if (foot && !document.querySelector(".drawer-about")) {
    const about = document.createElement("a");
    about.className = `drawer-about ${dashboardRoutePath() === "/about.html" ? "active" : ""}`;
    about.href = dashboardPath("/about.html");
    about.innerHTML = `<span class="drawer-group-mark">i</span><span><strong>關於網站</strong><small>網站介紹與資料說明</small></span><small>→</small>`;
    foot.before(about);
  }

  async function loadGroups() {
    if (loaded) return;
    loaded = true;
    try {
      const response = await dashboardFetch("/api/groups");
      if (!response.ok) throw new Error("讀取失敗");
      const groups = await response.json();
      list.innerHTML = groups.map(group => `
        <a class="drawer-group ${current === group.group_name ? "active" : ""} ${group.group_name === "other" ? "special" : ""}" href="${dashboardPath(`/groups/${encodeURIComponent(group.group_name)}`)}">
          <span class="drawer-group-mark">${safe(pretty(group.group_name)[0])}</span>
          <span><strong>${safe(pretty(group.group_name))}${group.group_name === "other" ? `<em class="drawer-group-badge">特殊分類</em>` : ""}</strong><small>${group.member_count} 位成員 · ${group.stream_count} 場直播</small></span>
          <small>${group.has_live ? "● LIVE" : "›"}</small>
        </a>`).join("");
    } catch {
      list.innerHTML = `<div class="drawer-loading">無法讀取 Group 列表</div>`;
    }
  }

  function open() {
    drawer.classList.add("open");
    overlay.classList.add("open");
    button.setAttribute("aria-expanded", "true");
    document.body.style.overflow = "hidden";
    loadGroups();
  }
  function shut() {
    drawer.classList.remove("open");
    overlay.classList.remove("open");
    button.setAttribute("aria-expanded", "false");
    document.body.style.overflow = "";
  }

  button.addEventListener("click", open);
  close.addEventListener("click", shut);
  overlay.addEventListener("click", shut);
  document.addEventListener("keydown", event => event.key === "Escape" && shut());
})();
