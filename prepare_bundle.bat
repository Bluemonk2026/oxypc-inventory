@echo off
setlocal EnableDelayedExpansion
title OxyPC — Preparing Standalone Bundle
color 0E

echo.
echo  =====================================================================
echo    OxyPC Inventory  ^|  Bundle Preparation (Run once on DEV machine)
echo  =====================================================================
echo  This downloads Python, PostgreSQL and cloudflared into bundle\
echo  then pre-initialises the database so the final EXE is 100%% self-contained.
echo  Estimated download: ~500 MB  ^|  Time: 5-15 minutes
echo  =====================================================================
echo.
pause

set ROOT=%~dp0
set BUNDLE=%ROOT%bundle
set PY=%BUNDLE%\python
set PGSQL=%BUNDLE%\pgsql
set PGDATA=%BUNDLE%\pgdata
set LOGS=%BUNDLE%\logs
set PGPORT=5433

REM ── versions / URLs ────────────────────────────────────────
set PY_VER=3.11.9
set PY_ZIP=python-%PY_VER%-embed-amd64.zip
set PY_URL=https://www.python.org/ftp/python/%PY_VER%/%PY_ZIP%
set PIP_URL=https://bootstrap.pypa.io/get-pip.py

set PG_VER=16.6-1
set PG_ZIP=postgresql-%PG_VER%-windows-x64-binaries.zip
set PG_URL=https://get.enterprisedb.com/postgresql/%PG_ZIP%

set CF_URL=https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe

REM ── create directory structure ─────────────────────────────
echo [1/11] Creating bundle directory structure...
mkdir "%BUNDLE%"       2>nul
mkdir "%PY%"           2>nul
mkdir "%PGSQL%"        2>nul
mkdir "%PGDATA%"       2>nul
mkdir "%LOGS%"         2>nul
mkdir "%BUNDLE%\tmp"   2>nul
echo         Done.

REM ═══════════════════════════════════════════════════════════
REM  STEP 1 — Download Python embedded
REM ═══════════════════════════════════════════════════════════
echo.
echo [2/11] Downloading Python %PY_VER% embedded (^~25 MB)...
if exist "%BUNDLE%\tmp\%PY_ZIP%" (
    echo         Already downloaded — skipping.
) else (
    powershell -NoProfile -Command ^
      "& { $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%BUNDLE%\tmp\%PY_ZIP%' }"
    if errorlevel 1 ( echo  ERROR: Download failed. & pause & exit /b 1 )
    echo         Downloaded.
)

echo         Extracting Python...
powershell -NoProfile -Command ^
  "Expand-Archive -Path '%BUNDLE%\tmp\%PY_ZIP%' -DestinationPath '%PY%' -Force"
echo         Extracted.

REM Enable site-packages in embedded Python
echo         Configuring embedded Python...
set PTH_FILE=%PY%\python311._pth
powershell -NoProfile -Command ^
  "(Get-Content '%PTH_FILE%') -replace '#import site','import site' | Set-Content '%PTH_FILE%'"
REM Add Lib/site-packages line
powershell -NoProfile -Command ^
  "Add-Content '%PTH_FILE%' 'Lib\site-packages'"
mkdir "%PY%\Lib\site-packages" 2>nul
echo         Python configured.

REM ── Download and install pip ───────────────────────────────
echo.
echo [3/11] Installing pip into embedded Python...
powershell -NoProfile -Command ^
  "& { $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%PIP_URL%' -OutFile '%BUNDLE%\tmp\get-pip.py' }"
"%PY%\python.exe" "%BUNDLE%\tmp\get-pip.py" --no-warn-script-location >"%LOGS%\pip_install.log" 2>&1
if errorlevel 1 (
    echo  ERROR: pip install failed. See %LOGS%\pip_install.log
    pause & exit /b 1
)
echo         pip installed.

REM ── Install all app requirements ───────────────────────────
echo.
echo [4/11] Installing Python packages into embedded Python (^~5 min)...
echo         (fastapi, uvicorn, sqlalchemy, asyncpg, passlib, jose ...)
"%PY%\python.exe" -m pip install -r "%ROOT%requirements.txt" --no-warn-script-location ^
    --ignore-requires-python >"%LOGS%\packages.log" 2>&1
if errorlevel 1 (
    echo  ERROR: Package install failed. See %LOGS%\packages.log
    pause & exit /b 1
)
REM Remove PyInstaller from the bundle (not needed at runtime)
"%PY%\python.exe" -m pip uninstall -y pyinstaller >nul 2>&1
echo         All packages installed.

REM ═══════════════════════════════════════════════════════════
REM  STEP 2 — Download PostgreSQL 16 portable binaries
REM ═══════════════════════════════════════════════════════════
echo.
echo [5/11] Downloading PostgreSQL %PG_VER% binaries (^~360 MB) ...
if exist "%BUNDLE%\tmp\%PG_ZIP%" (
    echo         Already downloaded — skipping.
) else (
    powershell -NoProfile -Command ^
      "& { $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%PG_URL%' -OutFile '%BUNDLE%\tmp\%PG_ZIP%' }"
    if errorlevel 1 ( echo  ERROR: Download failed. & pause & exit /b 1 )
    echo         Downloaded.
)

echo         Extracting PostgreSQL (this may take a minute)...
if not exist "%PGSQL%\bin\pg_ctl.exe" (
    powershell -NoProfile -Command ^
      "Expand-Archive -Path '%BUNDLE%\tmp\%PG_ZIP%' -DestinationPath '%BUNDLE%' -Force"
    echo         Extracted.
) else (
    echo         Already extracted — skipping.
)

REM ── Initialise PostgreSQL data directory ──────────────────
echo.
echo [6/11] Initialising PostgreSQL data directory...
if exist "%PGDATA%\PG_VERSION" (
    echo         Already initialised — skipping.
) else (
    "%PGSQL%\bin\initdb.exe" -D "%PGDATA%" -U postgres ^
        --locale=en-US --encoding=UTF8 --no-sync >"%LOGS%\initdb.log" 2>&1
    if errorlevel 1 (
        echo  ERROR: initdb failed. See %LOGS%\initdb.log
        pause & exit /b 1
    )
    echo         Data directory initialised.
)

REM ── Configure PostgreSQL ───────────────────────────────────
echo         Configuring PostgreSQL (port %PGPORT%, no password for postgres)...
set PGCONF=%PGDATA%\postgresql.conf
set PGHBA=%PGDATA%\pg_hba.conf

powershell -NoProfile -Command ^
  "(Get-Content '%PGCONF%') -replace '#port = 5432','port = %PGPORT%' | Set-Content '%PGCONF%'"
powershell -NoProfile -Command ^
  "(Get-Content '%PGCONF%') -replace \"#listen_addresses = 'localhost'\",\"listen_addresses = 'localhost'\" | Set-Content '%PGCONF%'"
REM Allow trust auth for local connections during bundle prep
powershell -NoProfile -Command ^
  "Set-Content '%PGHBA%' @'`nlocal   all             all                                     trust`nhost    all             all             127.0.0.1/32            trust`nhost    all             all             ::1/128                 trust`n'@"
echo         Configured.

REM ── Start PostgreSQL temporarily ──────────────────────────
echo.
echo [7/11] Starting temporary PostgreSQL for database setup...
"%PGSQL%\bin\pg_ctl.exe" -D "%PGDATA%" -l "%LOGS%\pg_setup.log" ^
    -o "-p %PGPORT%" start >nul 2>&1
timeout /t 5 /nobreak >nul

REM Wait until ready
:waitpg
"%PGSQL%\bin\pg_isready.exe" -h localhost -p %PGPORT% -U postgres >nul 2>&1
if errorlevel 1 (
    timeout /t 2 /nobreak >nul
    goto :waitpg
)
echo         PostgreSQL ready.

REM ── Create oxypc user and database ────────────────────────
echo.
echo [8/11] Creating database user, schema and tables...
"%PGSQL%\bin\psql.exe" -h localhost -p %PGPORT% -U postgres -c ^
    "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='oxypc') THEN CREATE USER oxypc WITH PASSWORD 'oxypc123'; END IF; END $$;" >nul 2>&1
"%PGSQL%\bin\psql.exe" -h localhost -p %PGPORT% -U postgres -c ^
    "SELECT 1 FROM pg_database WHERE datname='oxypc_db'" 2>nul | findstr "1 row" >nul
if errorlevel 1 (
    "%PGSQL%\bin\psql.exe" -h localhost -p %PGPORT% -U postgres -c ^
        "CREATE DATABASE oxypc_db OWNER oxypc;" >nul 2>&1
)
"%PGSQL%\bin\psql.exe" -h localhost -p %PGPORT% -U postgres -c ^
    "GRANT ALL PRIVILEGES ON DATABASE oxypc_db TO oxypc;" >nul 2>&1

REM Write a bundle-specific config.ini pointing to port 5433
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
) > "%BUNDLE%\config.ini"

REM Run setup_db (tables) using bundled Python, pointing to bundle config
set PYTHONPATH=%ROOT%
set OXYPC_CONFIG=%BUNDLE%\config.ini
"%PY%\python.exe" "%ROOT%setup_db.py" < "%ROOT%setup_uat_input.txt" ^
    >"%LOGS%\setup_db.log" 2>&1
"%PY%\python.exe" "%ROOT%upgrade_db.py" >"%LOGS%\upgrade_db.log" 2>&1

REM Seed UAT users
echo.
echo [9/11] Seeding UAT users into database...
"%PY%\python.exe" "%ROOT%seed_uat_users.py" >"%LOGS%\seed.log" 2>&1
echo         Users seeded.

REM ── Stop PostgreSQL ────────────────────────────────────────
echo.
echo [10/11] Stopping temporary PostgreSQL...
"%PGSQL%\bin\pg_ctl.exe" -D "%PGDATA%" stop -m fast >nul 2>&1
timeout /t 3 /nobreak >nul
echo         Stopped.

REM ── Download cloudflared ───────────────────────────────────
echo.
echo [11/11] Downloading Cloudflare Tunnel (cloudflared ^~45 MB)...
if exist "%BUNDLE%\cloudflared.exe" (
    echo         Already downloaded — skipping.
) else (
    powershell -NoProfile -Command ^
      "& { $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%CF_URL%' -OutFile '%BUNDLE%\cloudflared.exe' }"
    if errorlevel 1 ( echo  WARNING: cloudflared download failed. Internet tunnel will not work. )
    echo         Downloaded.
)

REM ── Cleanup tmp downloads ──────────────────────────────────
echo.
echo  Cleaning up temporary download cache...
rd /s /q "%BUNDLE%\tmp" >nul 2>&1
echo         Done.

echo.
echo  =====================================================================
echo    BUNDLE READY
echo  =====================================================================
echo    Contents in: %BUNDLE%\
echo      python\     ^<- Python 3.11 + all packages
echo      pgsql\      ^<- PostgreSQL 16 portable binaries
echo      pgdata\     ^<- Pre-initialised database with UAT users
echo      cloudflared.exe
echo.
echo    NEXT: Run build_all.bat to compile OxyPC_UAT_Setup.exe
echo  =====================================================================
echo.
pause
