@echo off
setlocal EnableDelayedExpansion
title OxyPC — Building Standalone EXE
color 0E
cd /d "%~dp0"

echo.
echo  ╔═══════════════════════════════════════════════════════════╗
echo  ║   OxyPC Inventory  ^|  Build Standalone Installer EXE    ║
echo  ║                                                           ║
echo  ║   OUTPUT:  dist\OxyPC_UAT_Setup.exe                      ║
echo  ║   SIZE:    ~200-300 MB (fully self-contained)            ║
echo  ║   TIME:    15-30 minutes (mostly download time)          ║
echo  ╚═══════════════════════════════════════════════════════════╝
echo.

REM ─── Check for Inno Setup first (need it before doing long downloads) ──────
set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe"       set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
where ISCC >nul 2>&1 && set ISCC=ISCC

if "!ISCC!"=="" (
    echo  ╔══════════════════════════════════════════════════════╗
    echo  ║  Inno Setup 6 not found.                            ║
    echo  ║                                                      ║
    echo  ║  Download FREE from:                                 ║
    echo  ║    https://jrsoftware.org/isdl.php                   ║
    echo  ║                                                      ║
    echo  ║  Install with default settings then re-run this.    ║
    echo  ╚══════════════════════════════════════════════════════╝
    echo.
    echo  Opening download page...
    start https://jrsoftware.org/isdl.php
    pause
    exit /b 1
)
echo  [✓] Inno Setup found: !ISCC!
echo.

REM ─── Step 1: Prepare bundle (downloads Python, PG, cloudflared, inits DB) ──
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║  PHASE 1 of 2 : Preparing bundle                        ║
echo  ║  (Downloads ~500 MB on first run — cached after that)   ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

if exist "bundle\pgdata\PG_VERSION" (
    if exist "bundle\python\python.exe" (
        if exist "bundle\pgsql\bin\pg_ctl.exe" (
            echo  [✓] Bundle already prepared — skipping download phase.
            echo      Delete the bundle\ folder to re-download from scratch.
            goto :compile
        )
    )
)

call prepare_bundle.bat
if errorlevel 1 (
    echo.
    echo  ERROR: Bundle preparation failed. Cannot build installer.
    pause
    exit /b 1
)

:compile
REM ─── Step 2: Compile Inno Setup ───────────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║  PHASE 2 of 2 : Compiling installer EXE                 ║
echo  ║  (Compressing ~500 MB into a single exe — 3-10 min)     ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

if not exist "dist" mkdir dist

echo  Running Inno Setup compiler...
"!ISCC!" oxypc_setup.iss
if errorlevel 1 (
    echo.
    echo  BUILD FAILED. Check error output above.
    pause
    exit /b 1
)

REM ─── Done ─────────────────────────────────────────────────────────────────
echo.
echo  ╔═══════════════════════════════════════════════════════════╗
echo  ║   BUILD SUCCESSFUL!                                       ║
echo  ╠═══════════════════════════════════════════════════════════╣
echo  ║                                                           ║
echo  ║   File:  dist\OxyPC_UAT_Setup.exe                        ║
echo  ║                                                           ║
echo  ║   Distribute this ONE file to any Windows 10/11 machine. ║
echo  ║   No Python, PostgreSQL, or any other software needed.   ║
echo  ║                                                           ║
echo  ║   End-user experience:                                    ║
echo  ║     1. Double-click OxyPC_UAT_Setup.exe                  ║
echo  ║     2. Click Next → Install (takes ~2 minutes)           ║
echo  ║     3. Launch OxyPC from desktop shortcut                 ║
echo  ║     4. Share the internet URL shown in the console        ║
echo  ║     5. UAT testers log in from anywhere                   ║
echo  ║                                                           ║
echo  ╚═══════════════════════════════════════════════════════════╝
echo.

REM Show file size
for %%f in ("dist\OxyPC_UAT_Setup.exe") do (
    set /a SIZE_MB=%%~zf / 1048576
    echo   File size: !SIZE_MB! MB
)
echo.

REM Open dist folder
explorer dist
pause
