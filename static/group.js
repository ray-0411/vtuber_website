const $ = s => document.querySelector(s);
const fmt = new Intl.NumberFormat("zh-TW");
const parts = location.pathname.split("/").filter(Boolean);
const group = parts[1] || "meridian";
const validPeriods = new Set(["1m", "3m", "6m", "1y", "all"]);
const requestedPeriod = new URLSearchParams(location.search).get("period");
let selectedPeriod = validPeriods.has(requestedPeriod) ? requestedPeriod : "1m";
let members = [];

const safe = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pretty = value => value.split("_").map(x => x.charAt(0).toUpperCase() + x.slice(1)).join(" ");
const shortDate = value => value ? value.slice(0, 10).replaceAll("-", "/") : "尚無資料";

function render() {
  const query = $("#member-search").value.trim().toLowerCase();
  const sort = $("#member-sort").value;
  let rows = members.filter(x => `${x.name} ${x.vtuber_id}`.toLowerCase().includes(query));
  rows = [...rows].sort((a, b) => {
    if (sort === "streams") return b.stream_count - a.stream_count;
    if (sort === "average") {
      const average = row => {
        const values = [row.youtube_average_viewers, row.twitch_average_viewers].filter(x => x != null);
        return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
      };
      return average(b) - average(a);
    }
    if (sort === "latest") return (b.latest_stream_at || "").localeCompare(a.latest_stream_at || "");
    return (a.display_order ?? 99999) - (b.display_order ?? 99999);
  });
  $("#member-list").innerHTML = rows.map(row => `
    <a class="member-row" href="/groups/${encodeURIComponent(group)}/members/${encodeURIComponent(row.vtuber_id)}?period=${encodeURIComponent(selectedPeriod)}">
      <span class="member-avatar"><span>${safe(row.name?.slice(0,1) || "V")}</span>${row.youtube_avatar_url || row.twitch_avatar_url ? `<img src="${safe(row.youtube_avatar_url || row.twitch_avatar_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}</span>
      <span class="member-name"><strong>${safe(row.name)}</strong><small>${safe(row.vtuber_id)}${row.enabled ? "" : " · 未啟用"}</small></span>
      <span class="member-stat dual-stat">
        <small>直播場數</small>
        <span><b>YT</b><strong>${fmt.format(row.youtube_count || 0)}</strong></span>
        <span><b>TW</b><strong>${fmt.format(row.twitch_count || 0)}</strong></span>
      </span>
      <span class="member-stat dual-stat">
        <small>平均觀看</small>
        <span><b>YT</b><strong>${row.youtube_average_viewers == null ? "—" : fmt.format(Math.round(row.youtube_average_viewers))}</strong></span>
        <span><b>TW</b><strong>${row.twitch_average_viewers == null ? "—" : fmt.format(Math.round(row.twitch_average_viewers))}</strong></span>
      </span>
      <span class="member-stat"><strong class="${row.is_live ? "now-live" : ""}">${row.is_live ? `直播中 · ${fmt.format(row.viewers_now || 0)}` : shortDate(row.latest_stream_at)}</strong><small>${row.is_live ? "目前觀眾" : "最近直播"}</small></span>
      <span class="arrow">›</span>
    </a>`).join("") || `<div class="empty">找不到符合條件的成員</div>`;
}

async function init() {
  selectedPeriod = $("#group-period").value;
  const isOtherGroup = group === "other";
  const title = pretty(group);
  document.title = `${title} 成員｜Live Observatory`;
  $("#group-title").textContent = title;
  $("#crumb-group").textContent = title;
  $("#seal-letter").textContent = title[0];
  $("#group-nav").href = `/groups/${encodeURIComponent(group)}`;
  if (isOtherGroup) {
    document.body.classList.add("other-group-page");
    $("#group-special-label").hidden = false;
    $("#group-description").textContent = "未歸入特定團體的創作者集合。成員依平均觀眾排序，僅供個別頻道資料查閱。";
    $("#group-average-card").hidden = true;
    $("#member-sort").value = "average";
  }
  $("#group-analysis-link").href = `/groups/${encodeURIComponent(group)}/analysis?period=${encodeURIComponent(selectedPeriod)}`;
  const response = await fetch(`/api/groups/${encodeURIComponent(group)}?period=${encodeURIComponent(selectedPeriod)}`);
  if (!response.ok) throw new Error("找不到這個 Group");
  members = await response.json();
  $("#member-count").textContent = fmt.format(members.length);
  $("#available-count").textContent = fmt.format(members.filter(x => x.enabled).length);
  $("#stream-count").textContent = fmt.format(members.reduce((n, x) => n + x.stream_count, 0));
  $("#live-count").textContent = fmt.format(members.filter(x => x.is_live).length);
  const youtubeMembers = members.filter(x => x.youtube_average_viewers != null);
  const twitchMembers = members.filter(x => x.twitch_average_viewers != null);
  const memberAverage = (rows, key) => rows.length
    ? rows.reduce((sum, row) => sum + row[key], 0) / rows.length
    : null;
  const youtubeAverage = memberAverage(youtubeMembers, "youtube_average_viewers");
  const twitchAverage = memberAverage(twitchMembers, "twitch_average_viewers");
  $("#youtube-average").textContent = youtubeAverage == null ? "—" : fmt.format(Math.round(youtubeAverage));
  $("#twitch-average").textContent = twitchAverage == null ? "—" : fmt.format(Math.round(twitchAverage));
  render();
}

$("#member-search").addEventListener("input", render);
$("#member-sort").addEventListener("change", render);
$("#group-period").value = selectedPeriod;
$("#group-period").addEventListener("change", () => {
  selectedPeriod = $("#group-period").value;
  $("#member-list").innerHTML = `<div class="empty">載入分析資料…</div>`;
  init().catch(error => {
    $("#member-list").innerHTML = `<div class="empty">${safe(error.message)}</div>`;
  });
});
init().catch(error => $("#member-list").innerHTML = `<div class="empty">${safe(error.message)}</div>`);
