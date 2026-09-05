# VTuber Live Observatory

台灣 VTuber 的 YouTube、Twitch 直播資料觀測網站，提供即時直播、觀看排行、
Group 與成員分析、直播月曆及單場觀看人數變化。

## 公開網站

**[開啟 VTuber Live Observatory](https://ray-0411.github.io/vtuber_website/)**

網站部署於 GitHub Pages，資料由 Supabase 的唯讀 API 提供。網站不需要登入，
使用手機或電腦瀏覽器皆可開啟。

## 網站功能

- 上週 YouTube、Twitch 平均／最高觀看人數 Top 10。
- 上個完整月份的平均觀看人數排行。
- 顯示目前正在直播的頻道、頭像、標題與觀看人數。
- 依 Group 查看成員、直播次數及平台平均觀看人數。
- 查看個別成員的直播統計、常見分類、活動時段與近期直播。
- 依月份查看開台月曆與直播紀錄。
- 點選直播紀錄，以彈出視窗查看該場直播的觀看人數快照曲線。
- 從左側導覽開啟「關於網站」，查看網站與資料說明。

「關於網站」的公開文字位於 `static/about.html`；搜尋 `about-card` 即可修改各段內容。

統計平均值時，快照數不超過 3 筆的直播不納入平均；週排行則要求至少 5 筆
快照，避免觀測時間太短造成排名失真。

## 資料與架構

```text
抓取器 SQLite
   ↓ 合併及建立分析快取
Supabase PostgreSQL
   ↓ 受控唯讀 RPC
GitHub Pages 靜態網站
```

- `dashboard`、`analytics` 原始資料表啟用 Row Level Security。
- 匿名訪客無法直接讀取原始資料表，只能執行公開的唯讀 RPC。
- GitHub Pages 前端僅使用可公開的 Supabase publishable key。
- 資料庫密碼、secret key 與本機資料庫不會提交到 Git。

## 維護資料

一般更新建議在抓取器電腦使用
[`collector_supabase_tool`](collector_supabase_tool/README.md)：

1. 第一次使用先執行 `setup.bat`。
2. 抓取器完成資料更新後執行 `update_and_upload.bat`。
3. 工具會合併資料庫、重建分析快取、上傳 Supabase、重建全站排行榜快取並核對筆數。
4. 上傳完成後，公開網站重新整理即可取得新資料，不需要重新部署。

Dashboard 專案內也可以分開執行：

```powershell
refresh_merged_data.bat
upload_to_supabase.bat
```

Supabase 同步使用 Git 忽略的 `.env.supabase.local`：

```dotenv
SUPABASE_DB_URL=postgresql://...
```

此連線字串包含資料庫密碼，不可上傳或分享。

## 本機預覽

需要 Python 3，並先準備：

- `data/merged_live_data.db`
- `data/merged_analytics_cache.db`

啟動方式：

```powershell
python app.py
```

或雙擊：

```text
start_dashboard.bat
```

接著開啟 <http://127.0.0.1:8000>。

前端的 `static/supabase-config.js` 若已填入 Project URL 與 publishable key，會直接
讀取 Supabase；將兩個值留空則使用本機 Python `/api`。

## 主要目錄

```text
static/                       GitHub Pages 網頁與前端程式
supabase/migrations/          PostgreSQL schema、RLS 與唯讀 RPC
scripts/                      合併、分析、同步與驗證工具
collector_supabase_tool/      可搬至抓取器端的一鍵更新工具
.github/workflows/pages.yml   GitHub Pages 自動部署
```

## 版本紀錄

版本更新內容請參閱 [CHANGELOG.md](CHANGELOG.md)。
