# VTuber Live Observatory

## GitHub Pages

The `static` directory is deployed by `.github/workflows/pages.yml`. The public
site reads only reviewed Supabase RPC functions with the publishable browser
key in `static/supabase-config.js`; database passwords and secret/service-role
keys must never be committed.

Project Pages uses the `/vtuber_website/` base path. `static/404.html` routes
Group, member, analysis, and history URLs to their matching static templates.

以唯讀方式呈現 VTuber 直播資料的第一版檢視網頁。這是獨立專案，不依賴抓取器
repository 的路徑或程式碼。後端採用 Python 標準函式庫，不需安裝額外套件。

## 啟動

先準備資料庫。以下方式擇一：

1. 將相同 schema 的資料庫放在 `data/live_data.db`。
2. 用環境變數指定外部資料庫：

```powershell
$env:LIVE_DATA_DB = "C:\path\to\live_data.db"
```

3. 啟動時用參數指定。開發時若抓取器剛好放在相鄰目錄，可以執行：

```powershell
python app.py --database ..\yt_dlp\live_data.db
```

接著在本專案根目錄執行：

```powershell
python scripts\build_analytics_cache.py
python app.py
```

然後開啟 <http://127.0.0.1:8000>。

也可以直接執行 `start_dashboard.bat`。它會先以原子替換方式重建
`data/analytics_cache.db`，成功後才啟動網站。分析頁從快取讀取每場直播的
平均、最高、snapshot 數量、分類與時間區間；只有點開單場觀看曲線時才讀取
`live_data.db` 的原始 snapshot。快取可以隨時刪除並重新建立。

目前頁面：

- `/`：即時直播總覽
- `/groups/meridian`：Meridian 成員列表
- `/groups/meridian/members/<vtuber_id>`：成員個人分析與直播歷史

指定其他同 schema 的 SQLite 資料庫：

```powershell
python app.py --database C:\path\to\live_data.db --port 8080
```

若指定其他來源資料庫，也要用相同來源重建並指定快取：

```powershell
python scripts\build_analytics_cache.py --source C:\path\to\live_data.db --output C:\path\to\analytics_cache.db
python app.py --database C:\path\to\live_data.db --analytics-cache C:\path\to\analytics_cache.db
```

程式以 SQLite `mode=ro` 開啟資料庫，不會更動資料。資料庫檔案不會提交到
本專案 Git。

## API

- `GET /api/overview`：總覽數字
- `GET /api/live`：目前直播
- `GET /api/rankings/weekly`：上週 YouTube／Twitch 直播排行
- `GET /api/rankings/monthly-average`：上個完整月份平均觀眾排行
- `GET /api/streams/<stream_id>/snapshots`：單場直播與觀看快照
- `GET /api/groups`：Group 導覽清單
- `GET /api/groups/<group_name>`：Group 成員與基礎統計
- `GET /api/groups/<group_name>/members/<vtuber_id>`：成員分析與直播歷史

之後改用雲端資料庫時，可保留這組 API 回應格式，只替換
`DashboardRepository` 的查詢實作。

## Group 排序

左側導覽會顯示 `streamer` 資料表中的所有 Group，並依
`group_settings.display_order` 由小到大排序。第一次使用或新增 Group 後執行：

```powershell
python scripts\create_group_settings.py --database data\merged_live_data.db
```

接著可直接在 SQLite 編輯排序值，例如：

```sql
UPDATE group_settings SET display_order = 1 WHERE group_name = 'meridian';
UPDATE group_settings SET display_order = 2 WHERE group_name = 'thebox';
```

填寫 `display_order` 的 Group 會優先顯示並依數字排序；未填寫的 Group 會接在
後方，依 `group_name` 字母排序。新增的 Group 可重新執行上述腳本補進設定表，
既有排序不會被覆蓋。

## 更新合併資料庫

當 `data/live_data.db` 或 `data/streamer_audience.db` 更新後，可直接雙擊
`refresh_merged_data.bat`。它會重新合併 `legacy_live_data.db`、`live_data.db` 與
訂閱／追隨資料，保留 `group_settings` 的手動排序，並重建
`merged_analytics_cache.db`。完成後重新啟動網站即可使用最新資料。
