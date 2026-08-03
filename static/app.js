const $ = (selector) => document.querySelector(selector);
const fmt = new Intl.NumberFormat("zh-TW");

async function getJSON(url) {
  const response = await dashboardFetch(url);
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

function equalizeRankingRowHeights() {
  document.querySelectorAll(".platform-rankings").forEach(container => {
    const rows = [...container.querySelectorAll(".ranking-row")];
    rows.forEach(row => { row.style.height = "auto"; });
    const tallest = Math.max(0, ...rows.map(row => row.getBoundingClientRect().height));
    rows.forEach(row => { row.style.height = `${Math.ceil(tallest)}px`; });
  });
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

async function loadWeeklyRanking() {
  const data = await getJSON("/api/rankings/weekly");
  let selectedMetric = "average_viewers";
  $("#ranking-period").textContent = `${data.week_start.replaceAll("-", "/")} — ${data.week_end.replaceAll("-", "/")}`;
  const renderRanking = (platform, uniqueOnly) => {
    const ranking = data.platforms[platform]?.[selectedMetric] || { streams: [], unique_streams: [] };
    const rows = uniqueOnly ? ranking.unique_streams : ranking.streams;
    $(`#${platform}-ranking`).innerHTML = rows.length ? rows.map((row, index) => {
    const avatarUrl = platform === "youtube"
      ? (row.youtube_avatar_url || row.twitch_avatar_url)
      : (row.twitch_avatar_url || row.youtube_avatar_url);
    const profileUrl = dashboardPath(`/groups/${encodeURIComponent(row.group_name)}/members/${encodeURIComponent(row.vtuber_id)}?period=1m`);
    return `
    <article class="ranking-row rank-${index + 1}">
      <strong class="ranking-number">${index + 1}</strong>
      <a class="ranking-avatar" href="${safe(profileUrl)}" aria-label="查看 ${safe(row.name)} 的個人頁面"><span>${safe(row.name?.slice(0, 1) || "V")}</span>${avatarUrl ? `<img src="${safe(avatarUrl)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}</a>
      <div class="ranking-stream">
        <small><a class="ranking-person" href="${safe(profileUrl)}">${safe(row.name)}</a> · ${dateTime(row.started_at)} · ${safe(row.group_name)}</small>
        <h3><a href="${safe(row.stream_url || "#")}" target="_blank" rel="noreferrer">${safe(row.title)}</a></h3>
      </div>
      <div class="ranking-stat"><small>${selectedMetric === "average_viewers" ? "平均觀眾" : "最高觀眾"}</small><strong>${fmt.format(row[selectedMetric] || 0)}</strong></div>
      <div class="ranking-stat peak"><small>${selectedMetric === "average_viewers" ? "最高觀眾" : "平均觀眾"}</small><strong>${fmt.format(row[selectedMetric === "average_viewers" ? "peak_viewers" : "average_viewers"] || 0)}</strong></div>
    </article>`;
    }).join("") : `<div class="empty">上週沒有可計算平均觀眾的直播</div>`;
  };
  const renderAll = () => {
    const uniqueOnly = !$("#ranking-allow-duplicates").checked;
    renderRanking("youtube", uniqueOnly);
    renderRanking("twitch", uniqueOnly);
    requestAnimationFrame(equalizeRankingRowHeights);
  };
  $("#ranking-allow-duplicates").addEventListener("change", renderAll);
  document.querySelectorAll("[data-ranking-metric]").forEach(button => button.addEventListener("click", () => {
    selectedMetric = button.dataset.rankingMetric;
    document.querySelectorAll("[data-ranking-metric]").forEach(item => item.classList.toggle("active", item === button));
    $("#ranking-heading").textContent = `上週${selectedMetric === "average_viewers" ? "平均" : "最高"}觀看 Top 10`;
    renderAll();
  }));
  let resizeFrame;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(equalizeRankingRowHeights);
  });
  renderAll();
}

async function loadMonthlyAverageRanking() {
  const data = await getJSON("/api/rankings/monthly-average");
  $("#monthly-ranking-period").textContent = `${data.month_start.replaceAll("-", "/")} — ${data.month_end.replaceAll("-", "/")}`;
  for (const platform of ["youtube", "twitch"]) {
    const rows = data.platforms[platform] || [];
    $(`#${platform}-monthly-ranking`).innerHTML = rows.length ? rows.map((row, index) => {
      const avatarUrl = platform === "youtube"
        ? (row.youtube_avatar_url || row.twitch_avatar_url)
        : (row.twitch_avatar_url || row.youtube_avatar_url);
      const profileUrl = dashboardPath(`/groups/${encodeURIComponent(row.group_name)}/members/${encodeURIComponent(row.vtuber_id)}?period=1m`);
      return `
      <article class="ranking-row rank-${index + 1}">
        <strong class="ranking-number">${index + 1}</strong>
        <a class="ranking-avatar" href="${safe(profileUrl)}" aria-label="查看 ${safe(row.name)} 的個人頁面"><span>${safe(row.name?.slice(0, 1) || "V")}</span>${avatarUrl ? `<img src="${safe(avatarUrl)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}</a>
        <div class="ranking-stream">
          <h3><a class="ranking-person" href="${safe(profileUrl)}">${safe(row.name)}</a></h3>
          <small>${safe(row.group_name)} · ${fmt.format(row.stream_count)} 場有效直播</small>
        </div>
        <div class="ranking-stat"><small>月平均觀眾</small><strong>${fmt.format(row.average_viewers || 0)}</strong></div>
      </article>`;
    }).join("") : `<div class="empty">該月沒有足夠的直播資料</div>`;
  }
  requestAnimationFrame(equalizeRankingRowHeights);
}

async function loadStreams() {
  const platform = $("#platform").value;
  const query = $("#search").value.trim().toLowerCase();
  const liveRows = await getJSON("/api/live");
  const rows = liveRows.filter(row =>
    (!platform || row.platform === platform) &&
    (!query || `${row.name} ${row.group_name} ${row.title}`.toLowerCase().includes(query))
  );
  $("#stream-table").innerHTML = rows.map(row => {
    const profileUrl = dashboardPath(`/groups/${encodeURIComponent(row.group_name)}/members/${encodeURIComponent(row.vtuber_id)}?period=1m`);
    const avatarUrl = row.platform === "youtube"
      ? (row.youtube_avatar_url || row.twitch_avatar_url)
      : (row.twitch_avatar_url || row.youtube_avatar_url);
    return `
    <tr>
      <td><div class="live-table-channel">
        <a class="live-table-avatar" href="${safe(profileUrl)}"><span>${safe(row.name?.slice(0, 1) || "V")}</span>${avatarUrl ? `<img src="${safe(avatarUrl)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}</a>
        <span><a class="channel" href="${safe(profileUrl)}">${safe(row.name)}</a><span class="group">${safe(row.group_name)}</span></span>
      </div></td>
      <td class="title-cell"><a href="${safe(row.stream_url || "#")}" target="_blank" rel="noreferrer">${safe(row.title || "未提供標題")}</a></td>
      <td><span class="badge ${safe(row.platform)}">${safe(row.platform)}</span></td>
      <td>${dateTime(row.started_at)}</td>
      <td class="number">${fmt.format(row.viewer_count || 0)}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="5">目前沒有符合條件的即時直播</td></tr>`;
}

let timer;
$("#search").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(loadStreams, 250); });
$("#platform").addEventListener("change", loadStreams);

Promise.all([loadOverview(), loadWeeklyRanking(), loadMonthlyAverageRanking(), loadStreams()])
  .catch(error => { $("#sync-label").textContent = `讀取失敗：${error.message}`; });
