const $ = (selector) => document.querySelector(selector);
const fmt = new Intl.NumberFormat("zh-TW");

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error((await response.json()).error || response.statusText);
  return response.json();
}

function dateTime(value) {
  if (!value) return "—";
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const date = new Date(normalized.endsWith("Z") ? normalized : `${normalized}+08:00`);
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("zh-TW", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false
  }).format(date);
}

function safe(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
}

async function loadOverview() {
  const data = await getJSON("/api/overview");
  $("#live-now").textContent = fmt.format(data.live_now);
  $("#viewers-now").textContent = fmt.format(data.viewers_now);
  $("#streamers").textContent = fmt.format(data.streamers);
  $("#streams").textContent = fmt.format(data.streams);
  $("#platform-mix").textContent = data.platforms.map(x => `${x.platform} ${fmt.format(x.count)}`).join(" · ");
  $("#sync-label").textContent = `最近更新 ${dateTime(data.last_checked_at)}`;
}

async function loadLive() {
  const rows = await getJSON("/api/live");
  $("#live-grid").innerHTML = rows.length ? rows.map(row => `
    <article class="live-card">
      <div class="top"><span class="avatar">${safe(row.name?.slice(0, 1) || "V")}</span><span class="viewer">◉ ${fmt.format(row.viewer_count || 0)} 人</span></div>
      <h3><a href="${safe(row.stream_url || "#")}" target="_blank" rel="noreferrer">${safe(row.title)}</a></h3>
      <p>${safe(row.name)} · ${safe(row.category || row.group_name)}</p>
      <div class="card-foot"><span>${dateTime(row.started_at)} 開始</span><span class="platform">${safe(row.platform)}</span></div>
    </article>`).join("") : `<div class="empty">目前沒有偵測到直播</div>`;
}

async function loadActivity() {
  const rows = await getJSON("/api/activity");
  const max = Math.max(...rows.map(x => x.streams), 1);
  $("#activity-chart").innerHTML = rows.map(row => `
    <div class="bar-group" title="${safe(row.day)}：${fmt.format(row.streams)} 場直播，最高 ${fmt.format(row.peak_viewers)} 人">
      <div class="bar" style="height:${Math.max((row.streams / max) * 92, 3)}%"></div>
      <small>${row.day.slice(5).replace("-", "/")}</small>
    </div>`).join("");
}

async function loadHealth() {
  const data = await getJSON("/api/health");
  const bad = data.latest.filter(x => !["success", "running"].includes(x.status));
  $("#health-badge").textContent = bad.length ? `${bad.length} 項需留意` : "運作正常";
  $("#health-list").innerHTML = data.latest.map(row => `
    <div class="health-row">
      <i class="${["success", "running"].includes(row.status) ? "" : "bad"}"></i>
      <div><strong>${safe(row.job_name)}</strong><small>${safe(row.status)} · 檢查 ${fmt.format(row.checked_count)} 個</small></div>
      <time>${dateTime(row.finished_at || row.started_at)}</time>
    </div>`).join("");
}

async function loadStreams() {
  const params = new URLSearchParams({limit: "40"});
  if ($("#platform").value) params.set("platform", $("#platform").value);
  if ($("#search").value.trim()) params.set("q", $("#search").value.trim());
  const rows = await getJSON(`/api/streams?${params}`);
  $("#stream-table").innerHTML = rows.map(row => `
    <tr>
      <td><span class="channel">${safe(row.name)}</span><span class="group">${safe(row.group_name)}</span></td>
      <td class="title-cell"><a href="${safe(row.stream_url || "#")}" target="_blank" rel="noreferrer">${safe(row.title || "未提供標題")}</a></td>
      <td><span class="badge ${safe(row.platform)}">${safe(row.platform)}</span></td>
      <td>${dateTime(row.started_at)}</td>
      <td class="number">${fmt.format(row.peak_viewers || 0)}</td>
    </tr>`).join("") || `<tr><td colspan="5">找不到符合條件的直播</td></tr>`;
}

let timer;
$("#search").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(loadStreams, 250); });
$("#platform").addEventListener("change", loadStreams);

Promise.all([loadOverview(), loadLive(), loadActivity(), loadHealth(), loadStreams()])
  .catch(error => { $("#sync-label").textContent = `讀取失敗：${error.message}`; });
