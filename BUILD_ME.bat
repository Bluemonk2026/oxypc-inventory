@echo off
setlocal EnableDelayedExpansion
title OxyPC — Building Standalone EXE
color 0E
cd /d "%~dp0"

echo.
echo  ================================================================
echo    OxyPC Inventory  ^|  One-Click Standalone EXE Builder
echo  ================================================================
echo.
echo  This script will:
echo    1. Download and install Inno Setup 6  (free, ~5 MB)
echo    2. Download Python 3.11 embedded       (~25 MB)
echo    3. Install all Python packages          (~80 MB)
echo    4. Download PostgreSQL 16 portable     (~360 MB)
echo    5. Download Cloudflare Tunnel           (~45 MB)
echo    6. Pre-initialise database + UAT users
echo    7. Compile everything into ONE .exe file
echo    8. Place OxyPC_UAT_Setup.exe in this folder
echo.
echo  Total download : ~450 MB
echo  Estimated time : 20-30 minutes (cached on re-run)
echo  Requires       : Internet connection + Windows 10/11
echo.
echo  Press any key to begin, or close this window to cancel.
pause >nul

REM ── Verify curl.exe is available (built into Windows 10 1803+) ───────────
where curl.exe >nul 2>&1
if errorlevel 1 (
    echo.
    echo  ERROR: curl.exe not found.
    echo  This script requires Windows 10 version 1803 or later.
    pause & exit /b 1
)
echo  [OK] curl.exe available.

REM ── Create directories ───────────────────────────────────────────────────
mkdir bundle        2>nul
mkdir bundle\tmp    2>nul
mkdir bundle\logs   2>nul
mkdir dist          2>nul

REM ── Version pins ─────────────────────────────────────────────────────────
set PY_VER=3.11.9
set PY_ZIP=python-%PY_VER%-embed-amd64.zip
set PY_URL=https://www.python.org/ftp/python/%PY_VER%/%PY_ZIP%
set PIP_URL=https://bootstrap.pypa.io/get-pip.py

set PG_VER=16.6-1
set PG_ZIP=postgresql-%PG_VER%-windows-x64-binaries.zip
set PG_URL=https://get.enterprisedb.com/postgresql/%PG_ZIP%

set CF_URL=https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe

set PGPORT=5433

REM ================================================================
echo.
echo  ================================================================
echo   PHASE 1 of 3  ^|  Inno Setup 6
echo  ================================================================
echo.

REM ── Check if already installed ───────────────────────────────────────────
set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe"       set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
where ISCC >nul 2>&1 && set "ISCC=ISCC"

if not "!ISCC!"=="" (
    echo  [OK] Inno Setup already installed.
    goto :phase2
)

echo  Inno Setup not found. Downloading...
REM curl -L follows redirects; jrsoftware.org/download.php/is.exe redirects to latest
curl.exe -L --progress-bar --retry 3 --retry-delay 3 ^
    -o "bundle\tmp\innosetup.exe" ^
    "https://jrsoftware.org/download.php/is.exe"

if not exist "bundle\tmp\innosetup.exe" goto :is_fallback
for %%F in ("bundle\tmp\innosetup.exe") do if %%~zF LSS 1000000 goto :is_fallback
goto :is_install

:is_fallback
REM Primary URL failed — try the direct GitHub release
echo  Primary download failed. Trying alternate source...
curl.exe -L --progress-bar --retry 3 --retry-delay 3 ^
    -o "bundle\tmp\innosetup.exe" ^
    "https://github.com/jrsoftware/issrc/releases/download/is-6_3_3/innosetup-6.3.3.exe"

if not exist "bundle\tmp\innosetup.exe" goto :is_manual
for %%F in ("bundle\tmp\innosetup.exe") do if %%~zF LSS 1000000 goto :is_manual
goto :is_install

:is_manual
echo.
echo  ┌─────────────────────────────────────────────────────┐
echo  │  Auto-download failed. Manual install needed.       │
echo  │                                                     │
echo  │  1. Download page is opening in your browser now.   │
echo  │  2. Click the first download link (innosetup-x.exe) │
echo  │  3. Install it with default settings.               │
echo  │  4. Come back here and press any key.               │
echo  └─────────────────────────────────────────────────────┘
echo.
start https://jrsoftware.org/isdl.php
echo  Waiting for you to install Inno Setup...
pause >nul
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe"       set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if "!ISCC!"=="" (
    echo  ERROR: Still not found. Please install Inno Setup 6 and re-run BUILD_ME.bat.
    pause & exit /b 1
)
goto :phase2

:is_install
echo  Installing Inno Setup silently...
"bundle\tmp\innosetup.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-
timeout /t 10 /nobreak >nul
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe"       set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if "!ISCC!"=="" (
    echo  ERROR: Installation did not complete. Try running as Administrator.
    pause & exit /b 1
)
echo  [OK] Inno Setup installed.

REM ================================================================
:phase2
echo.
echo  ================================================================
echo   PHASE 2 of 3  ^|  Building bundle (Python + PG + packages)
echo  ================================================================
echo.

set PY=%~dp0bundle\python
set PGSQL=%~dp0bundle\pgsql
set PGDATA=%~dp0bundle\pgdata

REM ── Step 1: Python embedded ───────────────────────────────────────────────
echo  [1/8] Python %PY_VER% embedded...
if exist "%PY%\python.exe" (
    echo        Already done — skipping.
) else (
    if not exist "bundle\tmp\%PY_ZIP%" (
        echo        Downloading...
        curl.exe -L --progress-bar --retry 3 -o "bundle\tmp\%PY_ZIP%" "%PY_URL%"
        if errorlevel 1 ( echo  ERROR: Python download failed. & pause & exit /b 1 )
    )
    mkdir "%PY%" 2>nul
    echo        Extracting...
    powershell -NoProfile -Command "Expand-Archive -Path 'bundle\tmp\%PY_ZIP%' -DestinationPath '%PY%' -Force"
    REM Enable site-packages in _pth file
    powershell -NoProfile -Command ^
        "(Get-Content '%PY%\python311._pth') -replace '#import site','import site' | Set-Content '%PY%\python311._pth'"
    powershell -NoProfile -Command "Add-Content '%PY%\python311._pth' 'Lib\site-packages'"
    mkdir "%PY%\Lib\site-packages" 2>nul
    echo        Done.
)

REM ── Step 2: pip ───────────────────────────────────────────────────────────
echo  [2/8] pip for embedded Python...
if exist "%PY%\Scripts\pip.exe" (
    echo        Already done — skipping.
) else (
    if not exist "bundle\tmp\get-pip.py" (
        curl.exe -L --silent --retry 3 -o "bundle\tmp\get-pip.py" "%PIP_URL%"
    )
    "%PY%\python.exe" "bundle\tmp\get-pip.py" --no-warn-script-location >"bundle\logs\pip.log" 2>&1
    echo        Done.
)

REM ── Step 3: Python packages ───────────────────────────────────────────────
echo  [3/8] Python packages  (fastapi, uvicorn, sqlalchemy, asyncpg ...) ^~5 min...
if exist "%PY%\Lib\site-packages\fastapi" (
    echo        Already done — skipping.
) else (
    "%PY%\python.exe" -m pip install -r requirements.txt ^
        --no-warn-script-location --ignore-requires-python ^
        >"bundle\logs\packages.log" 2>&1
    if errorlevel 1 ( echo  ERROR: pip install failed. See bundle\logs\packages.log & pause & exit /b 1 )
    "%PY%\python.exe" -m pip uninstall -y pyinstaller >nul 2>&1
    echo        Done.
)

REM ── Step 4: PostgreSQL portable ───────────────────────────────────────────
echo  [4/8] PostgreSQL %PG_VER% portable binaries  (^~360 MB)...
if exist "%PGSQL%\bin\pg_ctl.exe" (
    echo        Already done — skipping.
) else (
    if not exist "bundle\tmp\%PG_ZIP%" (
        echo        Downloading (large file — please wait)...
        curl.exe -L --progress-bar --retry 3 -o "bundle\tmp\%PG_ZIP%" "%PG_URL%"
        if errorlevel 1 ( echo  ERROR: PostgreSQL download failed. & pause & exit /b 1 )
    )
    echo        Extracting (^~1 min)...
    powershell -NoProfile -Command "Expand-Archive -Path 'bundle\tmp\%PG_ZIP%' -DestinationPath 'bundle' -Force"
    echo        Done.
)

REM ── Step 5: Initialise PostgreSQL data directory ──────────────────────────
echo  [5/8] Initialising PostgreSQL data directory...
if exist "%PGDATA%\PG_VERSION" (
    echo        Already done — skipping.
) else (
    "%PGSQL%\bin\initdb.exe" -D "%PGDATA%" -U postgres ^
        --locale=en-US --encoding=UTF8 --no-sync >"bundle\logs\initdb.log" 2>&1
    if errorlevel 1 ( echo  ERROR: initdb failed. See bundle\logs\initdb.log & pause & exit /b 1 )

    REM Configure port 5433 and trust auth for seeding
    powershell -NoProfile -Command ^
        "(Get-Content '%PGDATA%\postgresql.conf') -replace '#port = 5432','port = %PGPORT%' | Set-Content '%PGDATA%\postgresql.conf'"
    powershell -NoProfile -Command ^
        "(Get-Content '%PGDATA%\postgresql.conf') -replace ""#listen_addresses = 'localhost'"",""listen_addresses = 'localhost'"" | Set-Content '%PGDATA%\postgresql.conf'"
    (
        echo local   all  all  trust
        echo host    all  all  127.0.0.1/32  trust
        echo host    all  all  ::1/128       trust
    ) > "%PGDATA%\pg_hba.conf"
    echo        Done.
)

REM ── Step 6: Start PG, seed DB, stop PG ───────────────────────────────────
echo  [6/8] Seeding database with tables and UAT users...
REM Check if already seeded by looking at pgdata/global (populated after first run)
if exist "%PGDATA%\global\pg_filenode.map" (
    REM Check if oxypc_db exists — if yes, skip seeding
    "%PGSQL%\bin\pg_ctl.exe" -D "%PGDATA%" -l "bundle\logs\pg_check.log" -o "-p %PGPORT%" start >nul 2>&1
    timeout /t 5 /nobreak >nul
    "%PGSQL%\bin\pg_isready.exe" -h localhost -p %PGPORT% -U postgres >nul 2>&1
    if not errorlevel 1 (
        "%PGSQL%\bin\psql.exe" -h localhost -p %PGPORT% -U postgres ^
            -c "SELECT 1 FROM pg_database WHERE datname='oxypc_db'" 2>nul | findstr "1 row" >nul
        if not errorlevel 1 (
            echo        Already seeded — skipping.
            "%PGSQL%\bin\pg_ctl.exe" -D "%PGDATA%" stop -m fast >nul 2>&1
            goto :step7
        )
    )
    "%PGSQL%\bin\pg_ctl.exe" -D "%PGDATA%" stop -m fast >nul 2>&1
    timeout /t 3 /nobreak >nul
)

REM Start PostgreSQL
"%PGSQL%\bin\pg_ctl.exe" -D "%PGDATA%" -l "bundle\logs\pg_seed.log" -o "-p %PGPORT%" start >nul 2>&1
:waitpg
"%PGSQL%\bin\pg_isready.exe" -h localhost -p %PGPORT% -U postgres >nul 2>&1
if errorlevel 1 ( timeout /t 2 /nobreak >nul & goto :waitpg )

REM Create DB user + database
"%PGSQL%\bin\psql.exe" -h localhost -p %PGPORT% -U postgres ^
    -c "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='oxypc') THEN CREATE USER oxypc WITH PASSWORD 'oxypc123'; END IF; END $$;" >nul 2>&1
"%PGSQL%\bin\psql.exe" -h localhost -p %PGPORT% -U postgres ^
    -c "SELECT 1 FROM pg_database WHERE datname='oxypc_db'" 2>nul | findstr "1 row" >nul
if errorlevel 1 (
    "%PGSQL%\bin\psql.exe" -h localhost -p %PGPORT% -U postgres ^
        -c "CREATE DATABASE oxypc_db OWNER oxypc;" >nul 2>&1
)
"%PGSQL%\bin\psql.exe" -h localhost -p %PGPORT% -U postgres ^
    -c "GRANT ALL PRIVILEGES ON DATABASE oxypc_db TO oxypc;" >nul 2>&1

REM Write bundle config.ini
(
    echo [database]
    echo url = postgresql+asyncpg://oxypc:oxypc123@localhost:%PGPORT%/oxypc_db
    echo.
    echo [security]
    echo secret_key = d5dc8129d740ba6a685b070f9b33410bb96e08cca6cfe3e561a16bf06b8d8b0a
    echo access_token_expire_minutes = 60
    echo refresh_token_expire_days = 7
    echo.
    echo [app]
    echo port = 8000
    echo host = 0.0.0.0
) > bundle\config.ini

REM Run setup + migrations + UAT seed
set PYTHONPATH=%~dp0
"%PY%\python.exe" setup_db.py < setup_uat_input.txt >"bundle\logs\setup_db.log"  2>&1
"%PY%\python.exe" upgrade_db.py                     >"bundle\logs\upgrade_db.log" 2>&1
"%PY%\python.exe" seed_uat_users.py                 >"bundle\logs\seed.log"       2>&1

REM Stop PostgreSQL
"%PGSQL%\bin\pg_ctl.exe" -D "%PGDATA%" stop -m fast >nul 2>&1
timeout /t 4 /nobreak >nul
echo        Done.

:step7
REM ── Step 7: Cloudflared ───────────────────────────────────────────────────
echo  [7/8] Cloudflare Tunnel (cloudflared.exe)...
if exist "bundle\cloudflared.exe" (
    echo        Already done — skipping.
) else (
    curl.exe -L --progress-bar --retry 3 -o "bundle\cloudflared.exe" "%CF_URL%"
    if errorlevel 1 (
        echo        WARNING: cloudflared download failed.
        echo        Internet tunnel will not work but local LAN access will still function.
    ) else (
        echo        Done.
    )
)

REM ── Step 8: Create logs placeholder ──────────────────────────────────────
echo  [8/8] Finalising bundle structure...
echo.>bundle\logs\.gitkeep 2>nul
echo        Done.

REM ================================================================
echo.
echo  ================================================================
echo   PHASE 3 of 3  ^|  Compiling installer EXE
echo  ================================================================
echo.
echo  Compressing ~500 MB into a single .exe (5-10 minutes)...
echo.

"!ISCC!" oxypc_setup.iss

if errorlevel 1 (
    echo.
    echo  BUILD FAILED.
    echo  Check the error shown above by Inno Setup.
    pause & exit /b 1
)

REM ── Copy final EXE to this folder ────────────────────────────────────────
if exist "dist\OxyPC_UAT_Setup.exe" (
    copy /y "dist\OxyPC_UAT_Setup.exe" "%~dp0OxyPC_UAT_Setup.exe" >nul
    echo  [OK] OxyPC_UAT_Setup.exe copied to this folder.
) else (
    echo  WARNING: dist\OxyPC_UAT_Setup.exe not found after build.
)

REM ── Cleanup temp files ────────────────────────────────────────────────────
rd /s /q bundle\tmp >nul 2>&1

echo.
echo  ================================================================
echo    BUILD COMPLETE
echo  ================================================================
echo.

for %%f in ("%~dp0OxyPC_UAT_Setup.exe") do (
    if exist "%%f" (
        set /a SZ=%%~zf / 1048576
        echo    File   : OxyPC_UAT_Setup.exe
        echo    Size   : !SZ! MB
    )
)

echo.
echo    HOW TO DISTRIBUTE:
echo    ─────────────────────────────────────────────────────────
echo    1. Send OxyPC_UAT_Setup.exe to the UAT server laptop
echo    2. Double-click it  (no Python or PostgreSQL needed)
echo    3. Click Next  →  Install   (takes about 2 minutes)
echo    4. Double-click "OxyPC Inventory" shortcut on Desktop
echo    5. A console appears with an internet URL — share it
echo    6. All 9 UAT testers open the URL in any browser
echo    ─────────────────────────────────────────────────────────
echo.
echo    All credentials are in: UAT_Credentials_Sheet.txt
echo    Full guide is in      : OxyPC_Installation_UAT_Guide_v1.0.docx
echo.
echo  ================================================================
echo.

REM Open the release folder
explorer "%~dp0"
pause
