const $ = selector => document.querySelector(selector);
const fmt = new Intl.NumberFormat("zh-TW");
const parts = location.pathname.split("/").filter(Boolean);
const group = parts[1] || "meridian";
const memberId = parts[3];
let historyData;

const safe = value => String(value ?? "").replace(/[&<>"']/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[character]));
const pretty = value => value.split("_").map(part => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
const displayDate = value => value ? value.slice(0, 10).replaceAll("-", "/") : "—";

function snapshotTime(value) {
  if (!value) return null;
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const parsed = new Date(normalized.endsWith("Z") ? normalized : `${normalized}+08:00`);
  return Number.isNaN(parsed.valueOf()) ? null : parsed;
}

function fullDateTime(value) {
  const parsed = snapshotTime(value);
  return parsed ? new Intl.DateTimeFormat("zh-TW", {
    month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hour12:false
  }).format(parsed) : "—";
}

function viewerChart(snapshots, platform) {
  if (!snapshots.length) return `<div class="empty">這場直播沒有觀眾 snapshot</div>`;
  const width = 1000, height = 290, left = 52, right = 20, top = 20, bottom = 42;
  const values = snapshots.map((row, index) => ({...row, time: snapshotTime(row.captured_at), index}));
  const times = values.map(row => row.time?.valueOf()).filter(value => value != null);
  const firstTime = times.length ? Math.min(...times) : 0;
  const lastTime = times.length ? Math.max(...times) : values.length - 1;
  const x = row => {
    const position = row.time && lastTime > firstTime
      ? (row.time.valueOf() - firstTime) / (lastTime - firstTime)
      : values.length === 1 ? .5 : row.index / (values.length - 1);
    return left + position * (width - left - right);
  };
  const max = Math.max(...values.map(row => row.viewer_count), 1);
  const y = value => height - bottom - value / max * (height - top - bottom);
  const path = values.map((row, index) => `${index ? "L" : "M"}${x(row)},${y(row.viewer_count)}`).join(" ");
  const ticks = [0, Math.ceil(max / 2), max].filter((value, index, all) => all.indexOf(value) === index);
  const labelIndexes = [0, Math.floor((values.length - 1) / 2), values.length - 1].filter((value, index, all) => all.indexOf(value) === index);
  const timeText = row => row.time
    ? new Intl.DateTimeFormat("zh-TW", {hour:"2-digit", minute:"2-digit", hour12:false}).format(row.time)
    : row.captured_at;
  return `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet">
    ${ticks.map(value => `<g><line class="viewer-grid" x1="${left}" y1="${y(value)}" x2="${width-right}" y2="${y(value)}"/><text class="viewer-axis" x="${left-9}" y="${y(value)+3}" text-anchor="end">${fmt.format(value)}</text></g>`).join("")}
    <path class="viewer-line ${safe(platform)}" d="${path}"/>
    ${values.map(row => `<g class="viewer-point ${safe(platform)}"><circle class="viewer-hit" cx="${x(row)}" cy="${y(row.viewer_count)}" r="10"><title>${timeText(row)}｜${fmt.format(row.viewer_count)} 人</title></circle><circle class="viewer-hover-dot" cx="${x(row)}" cy="${y(row.viewer_count)}" r="4"></circle><text class="viewer-value" x="${x(row)}" y="${y(row.viewer_count) < 35 ? y(row.viewer_count)+20 : y(row.viewer_count)-11}" text-anchor="middle">${fmt.format(row.viewer_count)}</text></g>`).join("")}
    ${labelIndexes.map(index => `<text class="viewer-axis" x="${x(values[index])}" y="${height-11}" text-anchor="${index === 0 ? "start" : index === values.length-1 ? "end" : "middle"}">${timeText(values[index])}</text>`).join("")}
  </svg>`;
}

async function openStreamModal(streamId) {
  $("#stream-modal").classList.add("open");
  $("#stream-modal").setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  $("#stream-modal-title").textContent = "直播觀眾走勢";
  $("#stream-modal-meta").innerHTML = "正在載入 snapshot…";
  $("#viewer-chart").innerHTML = `<div class="empty">載入中…</div>`;
  $("#stream-modal-stats").innerHTML = "";
  try {
    const response = await fetch(`/api/streams/${encodeURIComponent(streamId)}/snapshots`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "無法讀取這場直播");
    const {stream, snapshots} = data;
    $("#stream-modal-title").textContent = stream.title || "未提供標題";
    $("#stream-modal-meta").innerHTML = `<span class="chip ${safe(stream.platform)}">${safe(stream.platform)}</span><span>${displayDate(stream.started_at)}</span>${stream.stream_url ? `<a href="${safe(stream.stream_url)}" target="_blank" rel="noreferrer">開啟原直播 ↗</a>` : ""}`;
    $("#viewer-chart").innerHTML = viewerChart(snapshots, stream.platform);
    const peak = snapshots.length ? Math.max(...snapshots.map(row => row.viewer_count)) : null;
    const peakSnapshot = snapshots.find(row => row.viewer_count === peak);
    const average = snapshots.length && peak > 0 ? Math.round(snapshots.reduce((sum, row) => sum + row.viewer_count, 0) / snapshots.length) : null;
    $("#stream-modal-stats").innerHTML = `
      <span><small>Snapshots</small><strong>${fmt.format(snapshots.length)}</strong></span>
      <span><small>平均觀眾</small><strong>${average == null ? "—" : fmt.format(average)}</strong></span>
      <span><small>最高觀眾</small><strong>${peak == null ? "—" : fmt.format(peak)}</strong></span>
      <span><small>開始時間</small><strong class="stat-time">${fullDateTime(stream.started_at || snapshots[0]?.captured_at)}</strong></span>
      <span><small>${stream.ended_at ? "結束時間" : "最後觀測時間"}</small><strong class="stat-time">${fullDateTime(stream.ended_at || stream.observed_end_at || snapshots.at(-1)?.captured_at)}</strong></span>
      <span><small>最高觀眾時間</small><strong class="stat-time">${fullDateTime(peakSnapshot?.captured_at)}</strong></span>`;
  } catch (error) {
    $("#viewer-chart").innerHTML = `<div class="empty">${safe(error.message)}</div>`;
  }
}

function closeStreamModal() {
  $("#stream-modal").classList.remove("open");
  $("#stream-modal").setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}

function streamRows(rows) {
  return rows.map(row => `
    <tr class="history-row" data-stream-id="${row.stream_id}" tabindex="0" title="點擊查看觀眾人數走勢">
      <td>${displayDate(row.started_at)}</td>
      <td class="stream-title"><a href="${safe(row.stream_url || "#")}" target="_blank" rel="noreferrer" onclick="event.stopPropagation()">${safe(row.title)}</a></td>
      <td>${safe(row.category || "未分類")}</td>
      <td><span class="chip ${safe(row.platform)}">${safe(row.platform)}</span></td>
      <td class="number">${row.peak_viewers == null ? "—" : fmt.format(row.peak_viewers)}</td>
      <td class="number">${row.average_viewers == null ? "—" : fmt.format(row.average_viewers)}</td>
      <td class="number">${fmt.format(row.snapshot_count)}</td>
    </tr>`).join("") || `<tr><td colspan="7">這個月份沒有直播資料</td></tr>`;
}

function render() {
  const weekdays = ["一", "二", "三", "四", "五", "六", "日"];
  const firstDay = historyData.calendar[0]?.day;
  const leadingDays = firstDay ? (new Date(`${firstDay}T00:00:00+08:00`).getDay() + 6) % 7 : 0;
  const intensity = count => Math.min(count, 4);
  $("#history-calendar").innerHTML = `
    ${weekdays.map(day => `<span class="calendar-weekday">週${day}</span>`).join("")}
    ${Array.from({length: leadingDays}, () => `<span class="calendar-blank" aria-hidden="true"></span>`).join("")}
    ${historyData.calendar.map(row => {
      const total = row.youtube + row.twitch;
      const platform = row.youtube && row.twitch ? "dual" : row.youtube ? "youtube" : row.twitch ? "twitch" : "none";
      return `<div class="calendar-day" title="${row.day} 12:00 至隔日 11:59｜YouTube ${row.youtube} 場、Twitch ${row.twitch} 場">
        <span class="calendar-date">${Number(row.day.slice(-2))}</span>
        <div class="calendar-activity ${platform} level-${intensity(total)}"><b>${total || ""}</b></div>
      </div>`;
    }).join("")}`;
  const selectedPlatform = $("#history-month-platform").value;
  const rows = historyData.streams.filter(row => !selectedPlatform || row.platform === selectedPlatform);
  $("#history-month-table").innerHTML = streamRows(rows);
  const youtube = historyData.streams.filter(row => row.platform === "youtube").length;
  const twitch = historyData.streams.filter(row => row.platform === "twitch").length;
  $("#history-month-summary").textContent = `${historyData.month.replace("-", " 年 ")} 月 · ${fmt.format(historyData.streams.length)} 場直播 · YouTube ${fmt.format(youtube)} · Twitch ${fmt.format(twitch)}`;
}

async function load(month = "") {
  $("#history-calendar").innerHTML = `<div class="empty history-loading">載入月份資料…</div>`;
  $("#history-month-table").innerHTML = `<tr><td colspan="7">載入中…</td></tr>`;
  const query = month ? `?month=${encodeURIComponent(month)}` : "";
  const response = await fetch(`/api/groups/${encodeURIComponent(group)}/members/${encodeURIComponent(memberId)}/history${query}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "無法讀取歷史紀錄");
  historyData = data;
  document.title = `${data.profile.name}的歷史紀錄｜Live Observatory`;
  $("#history-member-name").textContent = data.profile.name;
  $("#member-link").textContent = data.profile.name;
  $("#history-month").value = data.month;
  $("#history-month").min = data.available.first || data.month;
  $("#history-month").max = data.available.last || data.month;
  $("#history-prev-month").disabled = Boolean(data.available.first && data.month <= data.available.first);
  $("#history-next-month").disabled = Boolean(data.available.last && data.month >= data.available.last);
  render();
}

function moveMonth(offset) {
  if (!historyData) return;
  const [year, month] = historyData.month.split("-").map(Number);
  const target = new Date(year, month - 1 + offset, 1);
  load(`${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, "0")}`).catch(showError);
}

function showError(error) {
  $("#history-calendar").innerHTML = `<div class="empty history-loading">${safe(error.message)}</div>`;
  $("#history-month-table").innerHTML = `<tr><td colspan="7">${safe(error.message)}</td></tr>`;
}

const memberPath = `/groups/${encodeURIComponent(group)}/members/${encodeURIComponent(memberId)}`;
$("#group-nav").href = $("#group-link").href = `/groups/${encodeURIComponent(group)}`;
$("#group-link").textContent = pretty(group);
$("#member-link").href = $("#back-member").href = memberPath;
$("#history-month").addEventListener("change", event => event.target.value && load(event.target.value).catch(showError));
$("#history-prev-month").addEventListener("click", () => moveMonth(-1));
$("#history-next-month").addEventListener("click", () => moveMonth(1));
$("#history-month-platform").addEventListener("change", render);
$("#history-month-table").addEventListener("click", event => {
  const row = event.target.closest("[data-stream-id]");
  if (row) openStreamModal(row.dataset.streamId);
});
$("#history-month-table").addEventListener("keydown", event => {
  const row = event.target.closest("[data-stream-id]");
  if (row && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    openStreamModal(row.dataset.streamId);
  }
});
document.querySelectorAll("[data-close-modal]").forEach(element => element.addEventListener("click", closeStreamModal));
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && $("#stream-modal").classList.contains("open")) closeStreamModal();
});
load(new URLSearchParams(location.search).get("month") || "").catch(showError);
