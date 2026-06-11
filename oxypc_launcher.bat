@echo off
setlocal EnableDelayedExpansion
title OxyPC Inventory — UAT Server
color 0B
cd /d "%~dp0"

REM ── Find Python ───────────────────────────────────────────
set PYTHON=
if exist "%~dp0venv\Scripts\python.exe"       set "PYTHON=%~dp0venv\Scripts\python.exe"
if "!PYTHON!"=="" if exist "C:\Python313\python.exe" set "PYTHON=C:\Python313\python.exe"
if "!PYTHON!"=="" if exist "C:\Python312\python.exe" set "PYTHON=C:\Python312\python.exe"
if "!PYTHON!"=="" if exist "C:\Python311\python.exe" set "PYTHON=C:\Python311\python.exe"
if "!PYTHON!"=="" (
    for /f "tokens=*" %%p in ('where python 2^>nul') do if "!PYTHON!"=="" set "PYTHON=%%p"
)
if "!PYTHON!"=="" (
    echo ERROR: Python not found. Install Python 3.11+ from https://python.org
    pause & exit /b 1
)

echo.
echo  ============================================================
echo    OxyPC Inventory  ^|  UAT Server Starting...
echo  ============================================================
echo  Python : !PYTHON!
echo  Keep this window open during the UAT session.
echo  ============================================================
echo.

REM ── Run the unified launcher ──────────────────────────────
"!PYTHON!" "%~dp0launcher.py"

echo.
echo  Server stopped. Press any key to close.
pause >nul
