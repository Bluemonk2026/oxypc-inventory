@echo off
setlocal EnableDelayedExpansion
title OxyPC Inventory — UAT Setup
color 0A

echo.
echo  =====================================================
echo    OxyPC Inventory  ^|  UAT Server Setup
echo  =====================================================
echo.

REM ─────────────────────────────────────────────
REM  STEP 0 : Check Python
REM ─────────────────────────────────────────────
echo [1/8] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  ERROR: Python not found.
    echo  Please install Python 3.11+ from https://python.org
    echo  Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo         Python %PYVER% found.

REM ─────────────────────────────────────────────
REM  STEP 1 : Create / activate virtual environment
REM ─────────────────────────────────────────────
echo.
echo [2/8] Setting up virtual environment...
if not exist "venv\" (
    python -m venv venv
    echo         Virtual environment created.
) else (
    echo         Virtual environment already exists.
)

call venv\Scripts\activate.bat
echo         Activated venv.

REM ─────────────────────────────────────────────
REM  STEP 2 : Install dependencies
REM ─────────────────────────────────────────────
echo.
echo [3/8] Installing Python dependencies (this may take a moment)...
pip install -q -r requirements.txt
if errorlevel 1 (
    echo  ERROR: pip install failed. Check requirements.txt.
    pause
    exit /b 1
)
echo         Dependencies installed.

REM ─────────────────────────────────────────────
REM  STEP 3 : Check PostgreSQL connectivity
REM ─────────────────────────────────────────────
echo.
echo [4/8] Checking PostgreSQL...
psql --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  WARNING: psql not found in PATH.
    echo  Make sure PostgreSQL is installed and its bin folder is in PATH.
    echo  Default path: C:\Program Files\PostgreSQL\16\bin
    echo.
    echo  Attempting to continue anyway — if DB already exists this is fine.
) else (
    for /f "tokens=3" %%v in ('psql --version 2^>^&1') do set PGVER=%%v
    echo         PostgreSQL %PGVER% found.
)

REM Create DB user and database (safe — uses IF NOT EXISTS logic)
echo.
echo [5/8] Creating database user and schema...
echo         Running: CREATE USER oxypc ...
psql -U postgres -c "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='oxypc') THEN CREATE USER oxypc WITH PASSWORD 'oxypc123'; END IF; END $$;" >nul 2>&1
psql -U postgres -c "SELECT 1 FROM pg_database WHERE datname='oxypc_db'" | findstr /C:"1 row" >nul 2>&1
if errorlevel 1 (
    psql -U postgres -c "CREATE DATABASE oxypc_db OWNER oxypc;" >nul 2>&1
    echo         Database oxypc_db created.
) else (
    echo         Database oxypc_db already exists.
)
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE oxypc_db TO oxypc;" >nul 2>&1
echo         Permissions granted.

REM ─────────────────────────────────────────────
REM  STEP 4 : Write config.ini if not present
REM ─────────────────────────────────────────────
echo.
echo [6/8] Checking config.ini...
if not exist "config.ini" (
    python -c "from config import write_default_config; write_default_config()"
    echo         config.ini created.
) else (
    echo         config.ini already exists.
)

REM ─────────────────────────────────────────────
REM  STEP 5 : Run database migrations / table creation
REM ─────────────────────────────────────────────
echo.
echo [7/8] Running database setup and migrations...
python setup_db.py < setup_uat_input.txt
if errorlevel 1 (
    echo.
    echo  WARNING: setup_db.py returned an error.
    echo  If tables already exist this is normal — continuing.
)
python upgrade_db.py
echo         Migrations complete.

REM ─────────────────────────────────────────────
REM  STEP 6 : Seed UAT users
REM ─────────────────────────────────────────────
echo.
echo [8/8] Seeding UAT user accounts...
python seed_uat_users.py
echo.

REM ─────────────────────────────────────────────
REM  DONE
REM ─────────────────────────────────────────────
echo  =====================================================
echo    SETUP COMPLETE
echo  =====================================================
echo.
echo    To start the server + internet tunnel, run:
echo       start_server.bat
echo.
echo    Default Admin:   admin / oxypc@admin123
echo    UAT Users:       see UAT_Credentials_Sheet.txt
echo  =====================================================
echo.
pause
