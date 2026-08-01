const $ = selector => document.querySelector(selector);
const fmt = new Intl.NumberFormat("zh-TW");
const streamId = location.pathname.split("/").filter(Boolean)[1];
const requestedMonth = new URLSearchParams(location.search).get("month");

const safe = value => String(value ?? "").replace(/[&<>"']/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[character]));
const pretty = value => value.split("_").map(part => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");

function parseTime(value) {
  if (!value) return null;
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const parsed = new Date(normalized.endsWith("Z") ? normalized : `${normalized}+08:00`);
  return Number.isNaN(parsed.valueOf()) ? null : parsed;
}

function fullDateTime(value) {
  const parsed = parseTime(value);
  return parsed ? new Intl.DateTimeFormat("zh-TW", {
    year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hour12:false
  }).format(parsed) : "—";
}

function viewerChart(snapshots, platform) {
  if (!snapshots.length) return `<div class="empty">這場直播沒有觀眾 snapshot</div>`;
  const width = 1000, height = 330, left = 55, right = 22, top = 25, bottom = 44;
  const values = snapshots.map((row, index) => ({...row, time: parseTime(row.captured_at), index}));
  const times = values.map(row => row.time?.valueOf()).filter(value => value != null);
  const firstTime = times.length ? Math.min(...times) : 0;
  const lastTime = times.length ? Math.max(...times) : values.length - 1;
  const x = row => {
    const position = row.time && lastTime > firstTime ? (row.time.valueOf() - firstTime) / (lastTime - firstTime) : values.length === 1 ? .5 : row.index / (values.length - 1);
    return left + position * (width - left - right);
  };
  const max = Math.max(...values.map(row => row.viewer_count), 1);
  const y = value => height - bottom - value / max * (height - top - bottom);
  const path = values.map((row, index) => `${index ? "L" : "M"}${x(row)},${y(row.viewer_count)}`).join(" ");
  const ticks = [0, Math.ceil(max / 2), max].filter((value, index, all) => all.indexOf(value) === index);
  const labelIndexes = [0, Math.floor((values.length - 1) / 2), values.length - 1].filter((value, index, all) => all.indexOf(value) === index);
  const timeText = row => row.time ? new Intl.DateTimeFormat("zh-TW", {month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(row.time) : row.captured_at;
  return `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet">
    ${ticks.map(value => `<g><line class="viewer-grid" x1="${left}" y1="${y(value)}" x2="${width-right}" y2="${y(value)}"/><text class="viewer-axis" x="${left-9}" y="${y(value)+3}" text-anchor="end">${fmt.format(value)}</text></g>`).join("")}
    <path class="viewer-line ${safe(platform)}" d="${path}"/>
    ${values.map(row => `<g class="viewer-point ${safe(platform)}"><circle class="viewer-hit" cx="${x(row)}" cy="${y(row.viewer_count)}" r="10"><title>${timeText(row)}｜${fmt.format(row.viewer_count)} 人</title></circle><circle class="viewer-hover-dot" cx="${x(row)}" cy="${y(row.viewer_count)}" r="4"></circle><text class="viewer-value" x="${x(row)}" y="${y(row.viewer_count) < 40 ? y(row.viewer_count)+20 : y(row.viewer_count)-11}" text-anchor="middle">${fmt.format(row.viewer_count)}</text></g>`).join("")}
    ${labelIndexes.map(index => `<text class="viewer-axis" x="${x(values[index])}" y="${height-11}" text-anchor="${index === 0 ? "start" : index === values.length-1 ? "end" : "middle"}">${timeText(values[index])}</text>`).join("")}
  </svg>`;
}

async function init() {
  const response = await fetch(`/api/streams/${encodeURIComponent(streamId)}/snapshots`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "找不到這場直播");
  const {stream, snapshots} = data;
  const historyMonth = requestedMonth || (stream.started_at ? stream.started_at.slice(0, 7) : "");
  const memberPath = `/groups/${encodeURIComponent(stream.group_name)}/members/${encodeURIComponent(stream.vtuber_id)}`;
  const historyPath = `${memberPath}/history${historyMonth ? `?month=${encodeURIComponent(historyMonth)}` : ""}`;
  document.title = `${stream.title}｜Live Observatory`;
  $("#group-nav").href = $("#group-link").href = `/groups/${encodeURIComponent(stream.group_name)}`;
  $("#group-link").textContent = pretty(stream.group_name);
  $("#member-link").href = memberPath;
  $("#member-link").textContent = stream.name;
  $("#history-link").href = $("#back-history").href = historyPath;
  $("#stream-detail-title").textContent = stream.title;
  $("#stream-detail-labels").innerHTML = `<span class="chip ${safe(stream.platform)}">${safe(stream.platform)}</span>${stream.category ? `<span class="stream-detail-category">${safe(stream.category)}</span>` : ""}`;
  $("#stream-detail-meta").textContent = `${stream.name} · ${fullDateTime(stream.started_at)}`;
  if (stream.stream_url) {
    $("#stream-original-link").href = stream.stream_url;
    $("#stream-original-link").hidden = false;
  }
  const peak = snapshots.length ? Math.max(...snapshots.map(row => row.viewer_count)) : null;
  const peakSnapshot = snapshots.find(row => row.viewer_count === peak);
  const average = snapshots.length && peak > 0 ? Math.round(snapshots.reduce((sum, row) => sum + row.viewer_count, 0) / snapshots.length) : null;
  $("#stream-detail-stats").innerHTML = `
    <article><small>Snapshots</small><strong>${fmt.format(snapshots.length)}</strong></article>
    <article><small>平均觀眾</small><strong>${average == null ? "—" : fmt.format(average)}</strong></article>
    <article><small>最高觀眾</small><strong>${peak == null ? "—" : fmt.format(peak)}</strong></article>
    <article><small>開始時間</small><strong class="stat-time">${fullDateTime(stream.started_at || snapshots[0]?.captured_at)}</strong></article>
    <article><small>${stream.ended_at ? "結束時間" : "最後觀測時間"}</small><strong class="stat-time">${fullDateTime(stream.ended_at || stream.observed_end_at || snapshots.at(-1)?.captured_at)}</strong></article>
    <article><small>最高觀眾時間</small><strong class="stat-time">${fullDateTime(peakSnapshot?.captured_at)}</strong></article>`;
  $("#stream-detail-chart").innerHTML = viewerChart(snapshots, stream.platform);
}

init().catch(error => {
  $("#stream-detail-title").textContent = error.message;
  $("#stream-detail-chart").innerHTML = `<div class="empty">${safe(error.message)}</div>`;
});
