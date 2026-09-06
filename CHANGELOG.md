# 版本紀錄

此檔案記錄每個正式版本的功能與資料計算規則。版本號採用
[Semantic Versioning](https://semver.org/)：

- 第一位：不相容的大型改版
- 第二位：新增功能
- 第三位：修正與小幅調整

## [Unreleased]

### Fixed

- Use a plain white background and black text for the Rankings drawer item.
- Move the calendar-period selector to the single-stream ranking while restoring
  the lower section to the previous complete month's member-average ranking.
- Show the actual ranked month in the monthly-average heading.
- Standardize displayed timestamps across all pages as `YYYY-MM-DD HH:mm:ss`
  in Taiwan time (UTC+8), including ISO values with explicit offsets.

### Added

- Add an editable About page and a persistent link at the bottom of the left
  navigation drawer.
- Treat Groups without a numeric `display_order` as `other` in the query layer,
  while preserving every source Group name in the uploaded database.
- Add period-aware viewer hours to member analytics, calculated from each
  stream's average viewers and observed snapshot duration.
- Show period-aware viewer hours in Group member lists, abbreviated with `k`
  for values of 1,000 hours or more.
- Split the member detail viewer-hours total into compact YouTube and Twitch
  subtotals.
- Add a dedicated Rankings page below a separated navigation section, with
  metric, platform, and analysis-period selectors.
- Precompute all five member-ranking periods in a materialized view and refresh
  it transactionally after each Supabase upload.
- Keep the dedicated member ranking selector focused on average viewers and
  viewer hours.
- Show regular-weight YouTube and Twitch subtotals beside combined ranking
  values while keeping single-platform rankings compact.
- Align combined, YouTube, and Twitch ranking values in fixed table-like
  columns with consistent regular-weight typography.
- Replace the ranking value grid with a fixed-layout table so numeric columns
  remain aligned and visible at narrow viewport widths.
- Remove ranking `colgroup` sizing that could create hidden columns and offset
  the YouTube and Twitch headings in narrow layouts.
- Display the exact deployed Git commit beside the homepage update time, with
  the value generated automatically by the GitHub Pages workflow.
- Show the shared latest-update time and deployed commit status in the top bar
  of every dashboard page.

## [1.5.0] - 2026-08-05

### Added

- Add last-week, current-week, and current-month calendar-period options to the
  homepage average-viewer ranking.

## [1.4.4] - 2026-08-04

### Fixed

- Recognize ISO timestamps ending in an explicit offset such as `+00:00`
  instead of appending a second timezone offset and returning the raw value.

## [1.4.3] - 2026-08-04

### Fixed

- Format the homepage update timestamp as `YYYY-MM-DD HH:mm:ss` in Taiwan time.
- Bump the homepage script version so browsers do not retain the old timestamp formatter.

## [1.4.2] - 2026-08-04

### Fixed

- Display the homepage's latest-update time in Taiwan time (UTC+8) without a
  visible timezone suffix.

## [1.4.1] - 2026-08-04

### Added

- Portable collector-side toolkit for merging databases, rebuilding analytics,
  and uploading completed data to Supabase with one BAT file.
- Standalone dashboard-side Supabase upload BAT.

### Documentation

- Reworked the GitHub README around the public website, features, data flow,
  maintenance workflow, security model, and relevant links.

## [1.4.0] - 2026-08-04

Supabase-backed public dashboard and GitHub Pages deployment support.

### Added

- PostgreSQL migrations for private dashboard and analytics source tables.
- Transactional SQLite-to-Supabase synchronization with validation and row-count checks.
- Nine reviewed read-only RPCs for homepage, Group, member, history, and snapshot data.
- Browser REST adapter using a Supabase publishable key while preserving the local API fallback.
- GitHub Pages subpath routing, dynamic-page fallback, and Actions deployment workflow.

### Security

- Raw tables use RLS and remain inaccessible to anonymous and authenticated browser roles.
- Browser clients receive only explicitly granted RPC results.
- Local database connection credentials remain excluded from Git.

## [1.3.1] - 2026-08-02

清理首頁改版後不再使用的程式、API 與樣式，降低維護成本與多餘查詢。

### 程式清理

- 移除已無前端呼叫的活動、抓取器狀態及近期直播 API。
- 移除已由彈出視窗取代的獨立單場直播頁面與路由。
- 保留個人頁及歷史頁仍使用的單場觀看快照 API。
- 移除首頁 API 未使用的欄位與即時直播分類 JOIN。
- 清除舊直播卡片、圖表、抓取器狀態、歷史彈窗及時段長條圖樣式。
- 整理首頁基礎樣式，只保留目前頁面實際使用的元件。
- 更新 README API 清單，使文件與現行路由一致。

## [1.3.0] - 2026-08-02

重新設計首頁排行榜與即時直播資訊，並統一平均觀眾的有效資料規則。

### 週排行榜

- 首頁新增上個完整星期的 YouTube、Twitch 個別 Top 10。
- 支援依平均觀看或最高觀看切換排序。
- 預設每位實況主在各平台只出現一次，可切換為允許單場直播重複上榜。
- 週排行只納入至少 5 筆觀看快照的直播。
- 頭像及實況主名稱可連到完整個人檢視頁面。

### 月平均排行榜

- 新增上一個完整月份的 YouTube、Twitch 月平均觀眾 Top 10。
- 以實況主當月有效直播的單場平均觀眾彙整排名。
- 顯示每位實況主納入計算的有效直播場數。

### 平均觀眾規則

- 除週排行外，所有平均值統一排除只有 3 筆以下觀看快照的直播。
- 團體列表、個人摘要、團體分析、群組排序及分析快取皆套用相同規則。
- 低採樣直播仍保留於歷史場次、直播數、最高觀看及直播時數中。

### 即時直播

- 首頁近期直播紀錄改為即時直播清單，顯示頭像、直播標題與即時觀眾。
- 頭像與名稱可前往個人頁面，直播標題可前往原直播網址。
- 即時直播的開始時間統一使用該場直播第一筆觀看快照時間。
- 移除首頁直播活動圖表與抓取器狀態區塊，停止對應的前端 API 查詢。

## [1.2.0] - 2026-08-02

新增多 Group 導覽設定、Audience 資料整合與一鍵更新流程。

### Group 導覽與排序

- 左側導覽改為讀取資料庫中的全部 Group，不再限於 Meridian。
- 新增 `group_settings` 資料表，可用 `display_order` 手動設定優先順序。
- 有排序值的 Group 優先顯示，其餘 Group 接在後方並依名稱排列。
- `other` 加入特殊分類標示，隱藏全體平均觀眾並預設依成員平均觀眾排序。

### Audience 與頭像

- 合併 `streamer_audience.db` 的 YouTube 訂閱數及 Twitch 追隨數。
- 個人分析頁顯示各平台 Audience 數字；來源缺少數字時顯示尚無資料。
- Group 成員列表及個人分析頁支援 YouTube／Twitch 頭像。
- 頭像優先使用 YouTube，其次 Twitch，載入失敗時退回文字首字。
- 合併資料庫不再保留 Dashboard 未使用的 YouTube API、WebSub 與 build info 輔助表。

### 更新流程

- 新增 `refresh_merged_data.bat`，可一次合併直播、舊版及 Audience 資料並重建分析快取。
- 重新合併時保留 `group_settings` 的手動排序與備註。
- 新增 Group 設定同步工具，支援依成員人數或平均觀眾產生初始排序。

## [1.1.0] - 2026-08-01

新增歷史資料合併、分析快取與月份直播紀錄功能。

### 歷史資料與分析快取

- 新增舊版資料庫遷移工具，將舊資料轉換為目前的直播資料 schema。
- 新增資料庫合併工具，以目前資料庫為基底匯入歷史直播與 snapshots。
- 合併時依成員、平台及觀測時間辨認交界處的同場直播，避免重複加權。
- 新增可重建的分析快取，預先計算每場直播的觀眾統計、時段及營運日。
- 網站預設切換至合併版資料庫與分析快取。

### 分析期間

- Group、成員列表及個人分析新增近 1 個月、3 個月、6 個月、1 年與全部期間選項。
- 統計數字、開台時段及 Twitch 分類會依選取期間重新計算。
- 近期直播與營運日月曆仍保留對應頁面的完整顯示規則。

### 月份歷史紀錄

- 個人分析頁新增「歷史紀錄」入口。
- 新增完整月份歷史頁，可切換月份並查看整月開台月曆。
- 顯示當月所有直播資料，並支援 YouTube、Twitch 平台篩選。
- 點擊直播資料列可用彈出視窗查看觀眾 snapshots 走勢與單場統計。
- 直播標題可直接開啟原始直播頁面。

## [1.0.0] - 2026-07-25

第一個可使用的 VTuber 直播資料分析網站版本。

### 網站基礎

- 建立獨立的 `live_dashboard` Git repository。
- 使用 Python 標準函式庫提供本機 HTTP 服務，不需安裝額外套件。
- 以唯讀模式讀取 `data/live_data.db`。
- SQLite 資料庫、WAL、SHM 與環境設定檔不會提交至 Git。
- 提供白色數據分析介面及響應式版面。
- 新增漢堡導覽選單，目前只顯示 Meridian。

### 直播總覽

- 顯示目前直播、即時觀眾、追蹤頻道及歷史直播數量。
- 顯示正在直播的頻道卡片。
- 顯示最近 14 天直播活動。
- 顯示抓取器工作狀態。
- 提供直播紀錄搜尋及平台篩選。

### Meridian 成員列表

- 顯示成員總數及 Available 成員數。
- 顯示 YouTube、Twitch 各自的直播場數。
- 顯示各成員兩平台的平均觀看人數。
- 顯示最近直播或目前直播狀態。
- 支援成員搜尋，以及依官方順序、場數、平均觀看與最近直播排序。

### 個人分析

- 顯示兩平台直播場數、最高觀眾及平均觀眾。
- 顯示觀測直播時數。
- 顯示每半小時的直播涵蓋時段折線圖：
  - 橫軸從 12:00 開始，跨過午夜後到 11:30。
  - 直播只要碰到該半小時區間就計入。
  - 同一場直播對相同鐘點最多計算一次。
  - YouTube 使用紅線，Twitch 使用紫線。
- 顯示 Twitch 分類統計，不包含 YouTube 未分類資料。
- 顯示本週與前三週的營運日月曆：
  - 每日區間為當天 12:00 至隔天 11:59。
  - 跨過中午的直播會同時計入相鄰兩日。
  - YouTube 使用紅色、Twitch 使用紫色、雙平台使用 `#28FF28` 綠色。
- 近期直播表格最多載入 50 場，但上方分析使用全部歷史資料。

### Group 整體分析

- 彙整 Meridian 全部成員及所有歷史直播。
- Group 平均觀眾採用「先算每位成員平均，再平均所有有資料成員」。
- 顯示 Group 的直播涵蓋時段、Twitch 分類及近期 50 場直播。
- Group 月曆將 YouTube 與 Twitch 分格顯示並分別計算色階：
  - YouTube：1–2、3–4、5–6、7 場以上。
  - Twitch：1–3、4–6、7–9、10 場以上。
- Group 整體分析 API 經過彙整查詢最佳化。

### 單場直播分析

- 點擊近期直播資料列可開啟 snapshot 觀眾人數折線圖。
- YouTube 使用紅線，Twitch 使用紫線。
- 滑鼠移到資料位置才顯示圓點、觀眾人數及時間提示。
- 顯示 snapshot 數、平均觀眾、最高觀眾、開始時間、結束／最後觀測時間及最高觀眾時間。
- 可從分析視窗開啟原直播。

### 平均觀眾計算規則

- 先計算每場直播所有 snapshots 的平均觀眾。
- 每場直播在成員平均中具有相同權重，不依 snapshot 數量加權。
- Group 平均先計算各成員平均，再對有資料成員進行不加權平均。
- 所有 snapshots 都是 0 的直播：
  - 仍計入開台場數、時段圖、月曆與歷史資料。
  - 不參與任何平均觀眾計算，避免異常資料拉低平均。
- 一場直播只要有一筆大於 0，該場平均仍包含其餘數值為 0 的 snapshots。

### 已知限制

- 使用複製到網站專案的 SQLite 快照，不會與抓取器自動同步。
- 部分舊資料可能含有無法完整還原的文字編碼。
- 缺少正式結束時間時，以最後 snapshot 或最後觀測時間代替。
