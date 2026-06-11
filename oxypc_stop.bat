@echo off
title OxyPC — Stopping
color 0C
cd /d "%~dp0"

echo.
echo  Stopping OxyPC Inventory...
echo.

REM Stop uvicorn (Python processes)
taskkill /f /fi "WINDOWTITLE eq OxyPC Inventory*" >nul 2>&1

REM Stop cloudflared
taskkill /f /im cloudflared.exe >nul 2>&1

REM Stop PostgreSQL gracefully using bundled pg_ctl
if exist "%~dp0pgsql\bin\pg_ctl.exe" (
    "%~dp0pgsql\bin\pg_ctl.exe" -D "%~dp0pgdata" stop -m fast >nul 2>&1
    echo  [OK] PostgreSQL stopped.
)

REM Kill any remaining Python on port 8000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do (
    taskkill /f /pid %%a >nul 2>&1
)

echo  [OK] OxyPC Inventory stopped.
echo.
timeout /t 2 /nobreak >nul
