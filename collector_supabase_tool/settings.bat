@echo off
rem This folder is expected to sit directly inside the collector folder.
rem Change SOURCE_DIR if the three source databases are stored elsewhere.
set "SOURCE_DIR=.."

set "CURRENT_DB=%SOURCE_DIR%\live_data.db"
set "LEGACY_DB=%SOURCE_DIR%\legacy_live_data.db"
set "AUDIENCE_DB=%SOURCE_DIR%\streamer_audience.db"
