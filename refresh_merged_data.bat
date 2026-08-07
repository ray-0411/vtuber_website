@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"

echo [1/4] Merging legacy_live_data.db with the latest live_data.db...
python scripts\merge_live_databases.py --current data\live_data.db --legacy data\legacy_live_data.db --audience data\streamer_audience.db --output data\merged_live_data.db --report data\merge_report.json --overwrite
if errorlevel 1 goto :failed

echo.
echo [2/4] Consolidating unlisted Groups into other...
python scripts\consolidate_groups.py --database data\merged_live_data.db
if errorlevel 1 goto :failed

echo.
echo [3/4] Synchronizing Group settings...
python scripts\create_group_settings.py --database data\merged_live_data.db
if errorlevel 1 goto :failed

echo.
echo [4/4] Rebuilding analytics cache...
python scripts\build_analytics_cache.py --source data\merged_live_data.db --output data\merged_analytics_cache.db
if errorlevel 1 goto :failed

echo.
echo Refresh completed successfully.
echo The dashboard will use the updated merged database on its next start.
pause
exit /b 0

:failed
set "RESULT=%errorlevel%"
echo.
echo Refresh failed. Existing completed database files were kept whenever possible.
pause
exit /b %RESULT%
