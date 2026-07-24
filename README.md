# VTuber Live Observatory

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
python app.py
```

然後開啟 <http://127.0.0.1:8000>。

目前頁面：

- `/`：即時直播總覽
- `/groups/meridian`：Meridian 成員列表
- `/groups/meridian/members/<vtuber_id>`：成員個人分析與直播歷史

指定其他同 schema 的 SQLite 資料庫：

```powershell
python app.py --database C:\path\to\live_data.db --port 8080
```

程式以 SQLite `mode=ro` 開啟資料庫，不會更動資料。資料庫檔案不會提交到
本專案 Git。

## API

- `GET /api/overview`：總覽數字
- `GET /api/live`：目前直播
- `GET /api/activity`：最近 14 日活動
- `GET /api/streams?platform=&q=&limit=40`：直播紀錄
- `GET /api/health`：抓取器最新狀態
- `GET /api/groups/<group_name>`：Group 成員與基礎統計
- `GET /api/groups/<group_name>/members/<vtuber_id>`：成員分析與直播歷史

之後改用雲端資料庫時，可保留這組 API 回應格式，只替換
`DashboardRepository` 的查詢實作。
