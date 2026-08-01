@echo off
cd /d "%~dp0"
python scripts\build_analytics_cache.py --source data\merged_live_data.db --output data\merged_analytics_cache.db
if errorlevel 1 exit /b %errorlevel%
python app.py --database data\merged_live_data.db --analytics-cache data\merged_analytics_cache.db
pause
