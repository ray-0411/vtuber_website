# 抓取器資料合併與 Supabase 上傳工具

這個資料夾可以整包移到抓取器資料夾內。它不需要 dashboard 專案的其他檔案。

## 預設放置方式

```text
抓取器資料夾/
├─ live_data.db
├─ legacy_live_data.db
├─ streamer_audience.db
└─ collector_supabase_tool/
   ├─ update_and_upload.bat
   ├─ upload_only.bat
   ├─ setup.bat
   ├─ settings.bat
   ├─ .env.supabase.local
   ├─ scripts/
   └─ data/
```

如果三個來源資料庫不在工具資料夾的上一層，請修改 `settings.bat` 的
`SOURCE_DIR`。可以使用完整路徑，例如：

```bat
set "SOURCE_DIR=C:\Users\Ray\Desktop\collector"
```

## 第一次使用

1. 執行 `setup.bat` 安裝 PostgreSQL 上傳套件。
2. 確認 `.env.supabase.local` 存在。
3. 確認 `settings.bat` 指向正確的來源資料庫資料夾。

## 平常更新

抓取器完成資料更新後，雙擊 `update_and_upload.bat`。它會依序：

1. 合併 `live_data.db`、`legacy_live_data.db` 與 `streamer_audience.db`。
2. 更新 Group 排序資料。
3. 重建分析快取。
4. 在單一交易中上傳 Supabase 並核對所有資料表筆數。

網站會在查詢時把 `group_settings.display_order` 沒有數字的 Group 視為
`other`；來源資料庫內的原始 Group 名稱不會被修改。

看到 `Update and upload completed` 才表示全部完成。公開網站不需要重新部署，
重新整理後就會讀到 Supabase 的新資料。

`upload_only.bat` 只會重新上傳 `data` 內已經合併完成的資料，不會重新合併。

## 安全注意事項

`.env.supabase.local` 含有 Supabase 資料庫密碼。此工具資料夾可以在自己的電腦間
搬移，但不可上傳 GitHub、雲端公開連結或傳給其他人。若不小心外洩，請立刻在
Supabase 重設資料庫密碼。

上傳會取代 Supabase 中由 dashboard 管理的資料表，但使用交易處理；若中途失敗，
未完成的變更不會提交。
