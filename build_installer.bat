@echo off
title Build OxyPC Installer EXE
color 0E

echo.
echo  =====================================================
echo    OxyPC Inventory  ^|  Building Installer EXE
echo  =====================================================
echo.

REM ── Create dist folder ─────────────────────────────────
if not exist "dist" mkdir dist

REM ── Create a placeholder .gitkeep for logs folder ──────
if not exist "logs\.gitkeep" (
    mkdir logs 2>nul
    type nul > logs\.gitkeep
)

REM ── Find Inno Setup compiler ───────────────────────────
set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe
) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set ISCC=C:\Program Files\Inno Setup 6\ISCC.exe
) else (
    where ISCC >nul 2>&1
    if not errorlevel 1 set ISCC=ISCC
)

if "%ISCC%"=="" (
    echo.
    echo  ERROR: Inno Setup 6 not found.
    echo.
    echo  Please install it from:
    echo    https://jrsoftware.org/isdl.php
    echo.
    echo  Download: innosetup-6.x.x.exe  (free, ~5 MB)
    echo  Install with defaults, then re-run this script.
    echo.
    pause
    exit /b 1
)

echo  Found Inno Setup: %ISCC%
echo.
echo  Compiling oxypc_setup.iss ...
echo.

"%ISCC%" oxypc_setup.iss

if errorlevel 1 (
    echo.
    echo  BUILD FAILED. Check the error above.
    pause
    exit /b 1
)

echo.
echo  =====================================================
echo    BUILD SUCCESSFUL
echo  =====================================================
echo.
echo    Installer saved to:
echo      %CD%\dist\OxyPC_UAT_Setup.exe
echo.
echo    Share this .exe with any Windows machine to install
echo    OxyPC Inventory (requires Python + PostgreSQL).
echo  =====================================================
echo.
pause
