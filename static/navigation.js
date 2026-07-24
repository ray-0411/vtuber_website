(() => {
  const button = document.querySelector(".menu-button");
  if (!button) return;
  const drawer = document.querySelector(".nav-drawer");
  const overlay = document.querySelector(".drawer-overlay");
  const close = document.querySelector(".drawer-close");
  const list = document.querySelector(".drawer-groups");
  let loaded = false;

  const safe = value => String(value ?? "").replace(/[&<>"']/g, c => (
    {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]
  ));
  const pretty = value => value.split("_").map(
    word => word.charAt(0).toUpperCase() + word.slice(1)
  ).join(" ");
  const current = location.pathname.match(/^\/groups\/([^/]+)/)?.[1];

  async function loadGroups() {
    if (loaded) return;
    loaded = true;
    try {
      const response = await fetch("/api/groups");
      if (!response.ok) throw new Error("讀取失敗");
      const groups = await response.json();
      list.innerHTML = groups.map(group => `
        <a class="drawer-group ${current === group.group_name ? "active" : ""}" href="/groups/${encodeURIComponent(group.group_name)}">
          <span class="drawer-group-mark">${safe(pretty(group.group_name)[0])}</span>
          <span><strong>${safe(pretty(group.group_name))}</strong><small>${group.member_count} 位成員 · ${group.stream_count} 場直播</small></span>
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
