const $ = s => document.querySelector(s);
const fmt = new Intl.NumberFormat("zh-TW");
const parts = dashboardRoutePath().split("/").filter(Boolean);
const group = parts[1] || "meridian";
const isGroupAnalysis = parts[2] === "analysis";
const memberId = isGroupAnalysis ? null : parts[3];
const validPeriods = new Set(["1m", "3m", "6m", "1y", "all"]);
const requestedPeriod = dashboardSearchParams().get("period");
let analysis;

const safe = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pretty = value => value.split("_").map(x => x.charAt(0).toUpperCase() + x.slice(1)).join(" ");
const date = value => dashboardDate(value);

function hourChart(rows) {
  const order = [...Array.from({length: 24}, (_, i) => 720 + i * 30), ...Array.from({length: 24}, (_, i) => i * 30)];
  const intervals = order.map(minute => {
    const value = rows.find(row => row.minute_of_day === minute);
    return {
      minute,
      youtube: value?.youtube || 0,
      twitch: value?.twitch || 0
    };
  });
  const max = Math.max(...intervals.flatMap(row => [row.youtube, row.twitch]), 1);
  if (!rows.some(row => row.youtube || row.twitch)) return `<div class="empty">尚無直播時段資料</div>`;
  const width = 1000, height = 260, left = 36, right = 18, top = 20, bottom = 34;
  const x = index => left + index * (width - left - right) / (intervals.length - 1);
  const y = value => height - bottom - value / max * (height - top - bottom);
  const points = platform => intervals.map((row, index) => ({
    x: x(index), y: y(row[platform]), value: row[platform], minute: row.minute
  }));
  const youtube = points("youtube");
  const twitch = points("twitch");
  const path = values => values.map((point, index) => `${index ? "L" : "M"}${point.x},${point.y}`).join(" ");
  const gridValues = [0, Math.ceil(max / 2), max].filter((value, index, all) => all.indexOf(value) === index);
  const timeLabel = minute => `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
  const series = (values, platform, label) => `
    <path class="hour-line ${platform}" d="${path(values)}"/>
    ${values.filter(point => point.value > 0).map(point => `<g class="hour-point ${platform}">
      <circle class="hour-hit" cx="${point.x}" cy="${point.y}" r="9">
        <title>${timeLabel(point.minute)}｜${label} ${point.value} 場</title>
      </circle>
      <circle class="hour-hover-dot" cx="${point.x}" cy="${point.y}" r="4"></circle>
    </g>`).join("")}`;
  return `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" aria-label="各時段開台次數折線圖">
    ${gridValues.map(value => `<g><line class="hour-grid" x1="${left}" y1="${y(value)}" x2="${width-right}" y2="${y(value)}"/><text class="hour-axis-label" x="${left-8}" y="${y(value)+3}" text-anchor="end">${value}</text></g>`).join("")}
    ${series(youtube, "youtube", "YouTube")}
    ${series(twitch, "twitch", "Twitch")}
    ${intervals.map((row, index) => row.minute % 120 === 0 ? `<text class="hour-axis-label" x="${x(index)}" y="${height-9}" text-anchor="middle">${timeLabel(row.minute)}</text>` : "").join("")}
  </svg>`;
}

function streamRows(rows, emptyMessage = "尚無直播資料") {
  return rows.map(row => `
    <tr class="history-row" data-stream-id="${row.stream_id}" tabindex="0" title="點擊查看觀眾人數走勢">
      <td>${date(row.started_at)}</td>
      <td class="stream-title"><a href="${safe(row.stream_url || "#")}" target="_blank" rel="noreferrer" onclick="event.stopPropagation()">${row.member_name ? `<small class="stream-owner">${safe(row.member_name)}</small>` : ""}${safe(row.title)}</a></td>
      <td>${safe(row.category || "未分類")}</td>
      <td><span class="chip ${safe(row.platform)}">${safe(row.platform)}</span></td>
      <td class="number">${row.peak_viewers == null ? "—" : fmt.format(row.peak_viewers)}</td>
      <td class="number">${row.average_viewers == null ? "—" : fmt.format(row.average_viewers)}</td>
      <td class="number">${fmt.format(row.snapshot_count)}</td>
    </tr>`).join("") || `<tr><td colspan="7">${safe(emptyMessage)}</td></tr>`;
}

function renderHistory(platform = "") {
  const rows = analysis.streams.filter(x => !platform || x.platform === platform);
  $("#history-table").innerHTML = streamRows(rows, "此平台尚無直播資料");
}

function snapshotTime(value) {
  return dashboardParseTime(value);
}

function fullDateTime(value) {
  return dashboardDateTime(value);
}

function viewerChart(snapshots, platform) {
  if (!snapshots.length) return `<div class="empty">這場直播沒有觀眾 snapshot</div>`;
  const width = 1000, height = 290, left = 52, right = 20, top = 20, bottom = 42;
  const values = snapshots.map((row, index) => ({
    ...row, time: snapshotTime(row.captured_at), index
  }));
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
  const labelIndexes = [0, Math.floor((values.length - 1) / 2), values.length - 1]
    .filter((value, index, all) => all.indexOf(value) === index);
  const timeText = row => dashboardClockTime(row.captured_at);
  return `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet">
    ${ticks.map(value => `<g><line class="viewer-grid" x1="${left}" y1="${y(value)}" x2="${width-right}" y2="${y(value)}"/><text class="viewer-axis" x="${left-9}" y="${y(value)+3}" text-anchor="end">${fmt.format(value)}</text></g>`).join("")}
    <path class="viewer-line ${safe(platform)}" d="${path}"/>
    ${values.map(row => `<g class="viewer-point ${safe(platform)}">
      <circle class="viewer-hit" cx="${x(row)}" cy="${y(row.viewer_count)}" r="10"><title>${timeText(row)}｜${fmt.format(row.viewer_count)} 人</title></circle>
      <circle class="viewer-hover-dot" cx="${x(row)}" cy="${y(row.viewer_count)}" r="4"></circle>
      <text class="viewer-value" x="${x(row)}" y="${y(row.viewer_count) < 35 ? y(row.viewer_count) + 20 : y(row.viewer_count) - 11}" text-anchor="middle">${fmt.format(row.viewer_count)}</text>
    </g>`).join("")}
    ${labelIndexes.map(index => `<text class="viewer-axis" x="${x(values[index])}" y="${height-11}" text-anchor="${index === 0 ? "start" : index === values.length-1 ? "end" : "middle"}">${timeText(values[index])}</text>`).join("")}
  </svg>`;
}

async function openStreamModal(streamId) {
  const modal = $("#stream-modal");
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  $("#stream-modal-title").textContent = "直播觀眾走勢";
  $("#stream-modal-meta").innerHTML = "正在載入 snapshot…";
  $("#viewer-chart").innerHTML = `<div class="empty">載入中…</div>`;
  $("#stream-modal-stats").innerHTML = "";
  try {
    const response = await dashboardFetch(`/api/streams/${encodeURIComponent(streamId)}/snapshots`);
    if (!response.ok) throw new Error("無法讀取這場直播");
    const data = await response.json();
    const {stream, snapshots} = data;
    $("#stream-modal-title").textContent = stream.title || "未提供標題";
    $("#stream-modal-meta").innerHTML = `
      <span class="chip ${safe(stream.platform)}">${safe(stream.platform)}</span>
      <span>${fullDateTime(stream.started_at)}</span>
      ${stream.stream_url ? `<a href="${safe(stream.stream_url)}" target="_blank" rel="noreferrer">開啟原直播 ↗</a>` : ""}`;
    $("#viewer-chart").innerHTML = viewerChart(snapshots, stream.platform);
    const peak = snapshots.length ? Math.max(...snapshots.map(row => row.viewer_count)) : null;
    const peakSnapshot = snapshots.find(row => row.viewer_count === peak);
    const average = snapshots.length && peak > 0
      ? Math.round(snapshots.reduce((sum, row) => sum + row.viewer_count, 0) / snapshots.length)
      : null;
    const observedEnd = stream.ended_at || snapshots.at(-1)?.captured_at;
    $("#stream-modal-stats").innerHTML = `
      <span><small>Snapshots</small><strong>${fmt.format(snapshots.length)}</strong></span>
      <span><small>平均觀眾</small><strong>${average == null ? "—" : fmt.format(average)}</strong></span>
      <span><small>最高觀眾</small><strong>${peak == null ? "—" : fmt.format(peak)}</strong></span>
      <span><small>開始時間</small><strong class="stat-time">${fullDateTime(stream.started_at || snapshots[0]?.captured_at)}</strong></span>
      <span><small>${stream.ended_at ? "結束時間" : "最後觀測時間"}</small><strong class="stat-time">${fullDateTime(observedEnd)}</strong></span>
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

async function init() {
  const selectedPeriod = $("#analysis-period").value;
  const endpoint = isGroupAnalysis
    ? `/api/groups/${encodeURIComponent(group)}/analysis?period=${encodeURIComponent(selectedPeriod)}`
    : `/api/groups/${encodeURIComponent(group)}/members/${encodeURIComponent(memberId)}?period=${encodeURIComponent(selectedPeriod)}`;
  const response = await dashboardFetch(endpoint);
  if (!response.ok) throw new Error(isGroupAnalysis ? "找不到這個 Group" : "找不到這位成員");
  analysis = await response.json();
  const {profile, summary, streams, daily, categories, active_intervals, calendar} = analysis;
  const groupName = pretty(group);
  if (isGroupAnalysis) {
    document.body.classList.add("group-analysis-page");
    $("#open-history").hidden = true;
  } else {
    $("#open-history").href = dashboardPath(`/groups/${encodeURIComponent(group)}/members/${encodeURIComponent(memberId)}/history`);
  }
  const displayName = isGroupAnalysis ? `${groupName} 整體分析` : profile.name;
  document.title = `${displayName}｜Live Observatory`;
  $("#group-nav").href = $("#group-link").href = $("#back-group").href = dashboardPath(
    `/groups/${encodeURIComponent(group)}?period=${encodeURIComponent(selectedPeriod)}`);
  $("#group-link").textContent = $("#group-label").textContent = groupName;
  $("#member-crumb").textContent = $("#member-name").textContent = displayName;
  $("#member-id").textContent = isGroupAnalysis
    ? `${fmt.format(profile.enabled_count)} available / ${fmt.format(profile.member_count)} 位成員`
    : `@${profile.vtuber_id}${profile.enabled ? "" : " · 目前未啟用追蹤"}`;
  const avatarUrl = profile.youtube_avatar_url || profile.twitch_avatar_url;
  $("#profile-avatar").innerHTML = `<span>${safe(displayName?.slice(0, 1) || "V")}</span>${avatarUrl ? `<img src="${safe(avatarUrl)}" alt="${safe(displayName)}" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}`;
  if (profile.is_live) {
    $("#live-status").className = "live";
    $("#live-status").textContent = `LIVE · ${fmt.format(profile.viewers_now || 0)}`;
  }
  $("#profile-links").innerHTML = [
    profile.youtube_url && `<a href="${safe(profile.youtube_url)}" target="_blank" rel="noreferrer">YouTube ↗</a>`,
    profile.twitch_url && `<a href="${safe(profile.twitch_url)}" target="_blank" rel="noreferrer">Twitch ↗</a>`,
    profile.live_url && `<a href="${safe(profile.live_url)}" target="_blank" rel="noreferrer">觀看直播 ↗</a>`
  ].filter(Boolean).join("");
  $("#profile-audience").innerHTML = [
    profile.youtube_url && `<span><b>YT</b>${profile.youtube_subscribers == null ? "尚無資料" : `${fmt.format(profile.youtube_subscribers)} 訂閱`}</span>`,
    profile.twitch_url && `<span><b>TW</b>${profile.twitch_followers == null ? "尚無資料" : `${fmt.format(profile.twitch_followers)} 追隨`}</span>`
  ].filter(Boolean).join("");
  $("#period").textContent = summary.first_stream_at ? `${date(summary.first_stream_at)} — ${date(summary.latest_stream_at)}` : "尚無直播資料";
  $("#total-streams").textContent = fmt.format(summary.stream_count);
  $("#platform-counts").textContent = `YouTube ${fmt.format(summary.youtube_count || 0)} · Twitch ${fmt.format(summary.twitch_count || 0)}`;
  $("#youtube-peak").textContent = summary.youtube_peak_viewers == null ? "—" : fmt.format(summary.youtube_peak_viewers);
  $("#twitch-peak").textContent = summary.twitch_peak_viewers == null ? "—" : fmt.format(summary.twitch_peak_viewers);
  $("#youtube-viewers").textContent = summary.youtube_average_viewers == null ? "—" : fmt.format(Math.round(summary.youtube_average_viewers));
  $("#twitch-viewers").textContent = summary.twitch_average_viewers == null ? "—" : fmt.format(Math.round(summary.twitch_average_viewers));
  $("#observed-hours").textContent = `${fmt.format(summary.observed_hours || 0)}h`;
  $("#hour-chart").innerHTML = hourChart(active_intervals);
  const maxCategory = Math.max(...categories.map(x => x.stream_count), 1);
  $("#category-list").innerHTML = categories.map(row => `
    <div class="category-row"><span>${safe(row.category)}</span><span class="category-bar"><i style="width:${row.stream_count/maxCategory*100}%"></i></span><strong>${fmt.format(row.stream_count)}</strong></div>`).join("") || `<div class="empty">尚無分類資料</div>`;
  const weekdays = ["一", "二", "三", "四", "五", "六", "日"];
  const intensity = count => {
    return Math.min(count, 4);
  };
  const groupIntensity = (count, platform) => {
    if (count <= 0) return 0;
    const thresholds = platform === "youtube" ? [2, 4, 6] : [3, 6, 9];
    if (count <= thresholds[0]) return 1;
    if (count <= thresholds[1]) return 2;
    if (count <= thresholds[2]) return 3;
    return 4;
  };
  if (isGroupAnalysis) {
    $("#calendar-legend").innerHTML = `
      <i class="youtube"></i>YT 1–2 / 3–4 / 5–6 / 7+
      <i class="twitch"></i>TW 1–3 / 4–6 / 7–9 / 10+`;
  }
  $("#broadcast-calendar").innerHTML = `
    ${weekdays.map(day => `<span class="calendar-weekday">週${day}</span>`).join("")}
    ${calendar.map(row => {
      const [, month, day] = row.day.split("-");
      const total = row.youtube + row.twitch;
      const platformClass = row.youtube && row.twitch ? "dual" : row.youtube ? "youtube" : row.twitch ? "twitch" : "none";
      return `<div class="calendar-day" title="${row.day} 12:00 至隔日 11:59｜YouTube ${row.youtube} 場、Twitch ${row.twitch} 場">
        <span class="calendar-date">${Number(month)}/${Number(day)}</span>
        ${isGroupAnalysis ? `
          <div class="calendar-platforms">
            <i class="youtube level-${groupIntensity(row.youtube, "youtube")}"><b>${row.youtube || ""}</b></i>
            <i class="twitch level-${groupIntensity(row.twitch, "twitch")}"><b>${row.twitch || ""}</b></i>
          </div>` : `
          <div class="calendar-activity ${platformClass} level-${intensity(total)}"><b>${total || ""}</b></div>`}
      </div>`;
    }).join("")}`;
  renderHistory();
}

$("#history-platform").addEventListener("change", event => renderHistory(event.target.value));
$("#analysis-period").value = validPeriods.has(requestedPeriod) ? requestedPeriod : "1m";
$("#analysis-period").addEventListener("change", () => {
  $("#hour-chart").innerHTML = `<div class="empty">載入分析資料…</div>`;
  init().catch(error => {
    $("#hour-chart").innerHTML = `<div class="empty">${safe(error.message)}</div>`;
  });
});
$("#history-table").addEventListener("click", event => {
  const row = event.target.closest("[data-stream-id]");
  if (row) openStreamModal(row.dataset.streamId);
});
$("#history-table").addEventListener("keydown", event => {
  const row = event.target.closest("[data-stream-id]");
  if (row && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    openStreamModal(row.dataset.streamId);
  }
});
document.querySelectorAll("[data-close-modal]").forEach(element => element.addEventListener("click", closeStreamModal));
document.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;
  if ($("#stream-modal").classList.contains("open")) closeStreamModal();
});
init().catch(error => {
  $("#member-name").textContent = error.message;
  $("#hour-chart").innerHTML = `<div class="empty">${safe(error.message)}</div>`;
});
