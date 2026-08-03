@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo   Upload merged databases to Supabase
echo ========================================
echo.

if not exist ".env.supabase.local" (
  echo [ERROR] Missing .env.supabase.local
  echo Add SUPABASE_DB_URL before running this file.
  goto :failed
)

if not exist "data\merged_live_data.db" (
  echo [ERROR] Missing data\merged_live_data.db
  echo Run refresh_merged_data.bat first.
  goto :failed
)

if not exist "data\merged_analytics_cache.db" (
  echo [ERROR] Missing data\merged_analytics_cache.db
  echo Run refresh_merged_data.bat first.
  goto :failed
)

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found in PATH.
  goto :failed
)

echo Uploading data. Existing managed Supabase rows will be replaced.
echo.
python scripts\sync_merged_to_postgres.py --confirm-replace
if errorlevel 1 goto :failed

echo.
echo ========================================
echo   Supabase upload completed successfully
echo ========================================
pause
exit /b 0

:failed
echo.
echo ========================================
echo   Supabase upload failed
echo ========================================
pause
exit /b 1
