@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
call settings.bat

echo ========================================
echo   Merge collector data and upload
echo ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found in PATH.
  goto :failed
)

if not exist ".env.supabase.local" (
  echo [ERROR] Missing .env.supabase.local
  goto :failed
)
if not exist "%CURRENT_DB%" (
  echo [ERROR] Missing current database: %CURRENT_DB%
  goto :failed
)
if not exist "%LEGACY_DB%" (
  echo [ERROR] Missing legacy database: %LEGACY_DB%
  goto :failed
)
if not exist "%AUDIENCE_DB%" (
  echo [ERROR] Missing audience database: %AUDIENCE_DB%
  goto :failed
)

echo [1/5] Merging live databases...
python scripts\merge_live_databases.py --current "%CURRENT_DB%" --legacy "%LEGACY_DB%" --audience "%AUDIENCE_DB%" --output data\merged_live_data.db --report data\merge_report.json --overwrite
if errorlevel 1 goto :failed

echo.
echo [2/5] Consolidating unlisted Groups into other...
python scripts\consolidate_groups.py --database data\merged_live_data.db
if errorlevel 1 goto :failed

echo.
echo [3/5] Synchronizing Group settings...
python scripts\create_group_settings.py --database data\merged_live_data.db
if errorlevel 1 goto :failed

echo.
echo [4/5] Rebuilding analytics cache...
python scripts\build_analytics_cache.py --source data\merged_live_data.db --output data\merged_analytics_cache.db
if errorlevel 1 goto :failed

echo.
echo [5/5] Uploading to Supabase...
python scripts\sync_merged_to_postgres.py --confirm-replace
if errorlevel 1 goto :failed

echo.
echo ========================================
echo   Update and upload completed
echo ========================================
pause
exit /b 0

:failed
set "RESULT=%errorlevel%"
if "%RESULT%"=="0" set "RESULT=1"
echo.
echo ========================================
echo   Update or upload failed
echo ========================================
echo Existing Supabase data was kept if the upload did not commit.
pause
exit /b %RESULT%
