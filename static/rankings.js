const $ = selector => document.querySelector(selector);
const numberFormat = new Intl.NumberFormat("zh-TW", {maximumFractionDigits: 1});
const integerFormat = new Intl.NumberFormat("zh-TW", {maximumFractionDigits: 0});
const metricLabels = {
  average_viewers: "平均觀眾數",
  peak_viewers: "最高觀眾數",
  viewer_hours: "觀眾小時",
};

const safe = value => String(value ?? "").replace(/[&<>"']/g, char => (
  {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]
));
const pretty = value => String(value || "").split("_").map(
  word => word.charAt(0).toUpperCase() + word.slice(1)
).join(" ");

function selectedSource(row, metric, platform) {
  if (platform !== "combined") return platform;
  const youtubeValue = row[`youtube_${metric}`];
  const twitchValue = row[`twitch_${metric}`];
  if (youtubeValue == null) return "twitch";
  if (twitchValue == null) return "youtube";
  const youtube = Number(youtubeValue);
  const twitch = Number(twitchValue);
  return youtube >= twitch ? "youtube" : "twitch";
}

function displayValue(value, metric) {
  if (value == null) return "—";
  return metric === "peak_viewers" ? integerFormat.format(value) : numberFormat.format(value);
}

async function loadRankings() {
  const metric = $("#ranking-metric").value;
  const platform = $("#ranking-platform").value;
  const period = $("#ranking-period").value;
  const list = $("#ranking-list");
  list.innerHTML = `<div class="ranking-empty">正在載入排行榜…</div>`;
  $("#ranking-title").textContent = `${metricLabels[metric]}排行榜`;
  const query = new URLSearchParams({metric, platform, period});
  try {
    const response = await dashboardFetch(`/api/rankings/members?${query}`);
    if (!response.ok) throw new Error("排行榜讀取失敗");
    const rows = await response.json();
    $("#ranking-count").textContent = `${integerFormat.format(rows.length)} 位成員`;
    list.innerHTML = rows.map(row => {
      const source = selectedSource(row, metric, platform);
      const avatar = row[`${source}_avatar_url`] || row.youtube_avatar_url || row.twitch_avatar_url;
      const profile = dashboardPath(`/groups/${encodeURIComponent(row.group_name)}/members/${encodeURIComponent(row.vtuber_id)}?period=${encodeURIComponent(period)}`);
      const breakdown = platform === "combined" ? `<span class="ranking-breakdown">
        <span><b>YT</b>${displayValue(row[`youtube_${metric}`], metric)}</span>
        <span><b>TW</b>${displayValue(row[`twitch_${metric}`], metric)}</span>
      </span>` : "";
      return `<a class="ranking-row" href="${safe(profile)}">
        <span class="ranking-position">${row.rank}</span>
        <span class="ranking-avatar">${avatar ? `<img src="${safe(avatar)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : safe(row.name?.slice(0,1) || "V")}</span>
        <span class="ranking-person"><strong>${safe(row.name)}</strong><small>${safe(row.vtuber_id)}</small></span>
        <span class="ranking-group">${safe(pretty(row.group_name))}</span>
        <span class="ranking-value"><span class="ranking-primary">${displayValue(row.metric_value, metric)}<small class="ranking-source">${source === "youtube" ? "YT" : "TW"}${metric === "viewer_hours" ? " · h" : ""}</small></span>${breakdown}</span>
      </a>`;
    }).join("") || `<div class="ranking-empty">這個條件目前沒有可排名的資料</div>`;
  } catch (error) {
    $("#ranking-count").textContent = "讀取失敗";
    list.innerHTML = `<div class="ranking-empty">${safe(error.message)}</div>`;
  }
}

document.querySelectorAll(".ranking-controls select").forEach(select => {
  select.addEventListener("change", loadRankings);
});
loadRankings();
