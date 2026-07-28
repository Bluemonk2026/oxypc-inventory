@echo off
REM ============================================================================
REM  OxyPC PXE Station Bootstrap — installs the OxyQC agent and opens the ERP
REM  page for this station type automatically after Windows boots.
REM
REM  HOW TO USE (see README_PXE.txt for full PXE wiring instructions):
REM    1. Set SERVER_URL and STATION_MODE below for the image you are building.
REM    2. Bake this file into the PXE Windows image and call it from
REM       SetupComplete.cmd, a FirstLogonCommand, or the all-users Startup
REM       folder (README_PXE.txt shows all three options).
REM    3. On every boot it (re)downloads the latest agent from the ERP server,
REM       starts it, and opens the right ERP page in the browser.
REM
REM  STATION_MODE values:
REM    iqc     -> opens the IQC Entry page          (PXE image #1, IQC line)
REM    stress  -> opens Stress Test with autorun    (PXE image #2, Stress/Final QC line)
REM    finalqc -> opens the Final QC page           (also PXE image #2 if preferred)
REM ============================================================================

REM ==== CONFIG — EDIT THESE TWO LINES PER PXE IMAGE ===========================
set "SERVER_URL=http://10.199.206.109"
set "STATION_MODE=iqc"
REM ============================================================================

set "INSTALL_DIR=%ProgramData%\OxyQC"
set "AGENT_EXE=%INSTALL_DIR%\Diagnose_Device_Agent.exe"
set "STARTUP_DIR=%ProgramData%\Microsoft\Windows\Start Menu\Programs\StartUp"

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

REM ---- 1. Fetch the latest agent from the ERP (curl ships with Windows 10+).
REM      Keeps the previous copy if the server is unreachable (offline boot).
curl -fsSL --connect-timeout 15 "%SERVER_URL%/iqc/agent-exe" -o "%AGENT_EXE%.new"
if exist "%AGENT_EXE%.new" (
  move /y "%AGENT_EXE%.new" "%AGENT_EXE%" >nul
) else (
  echo [OxyQC] WARNING: could not download agent from %SERVER_URL% — using existing copy if present.
)

REM ---- 2. Resolve the ERP page for this station type.
if /i "%STATION_MODE%"=="stress"  set "STATION_PAGE=/qc?autorun=1"
if /i "%STATION_MODE%"=="finalqc" set "STATION_PAGE=/cosmetic/final-qc"
if /i "%STATION_MODE%"=="iqc"     set "STATION_PAGE=/iqc/new"
if not defined STATION_PAGE       set "STATION_PAGE=/iqc/new"

REM ---- 3. Write the boot launcher into the all-users Startup folder so every
REM         subsequent boot starts the agent and opens the ERP automatically.
(
  echo @echo off
  echo start "" "%AGENT_EXE%"
  echo timeout /t 6 /nobreak ^>nul
  echo start "" "%SERVER_URL%%STATION_PAGE%"
) > "%STARTUP_DIR%\oxyqc_station.bat"

REM ---- 4. First run right now (PXE first boot — Startup folder only fires on
REM         the NEXT logon).
start "" "%AGENT_EXE%"
timeout /t 6 /nobreak >nul
start "" "%SERVER_URL%%STATION_PAGE%"

echo [OxyQC] Station configured: MODE=%STATION_MODE%  SERVER=%SERVER_URL%
exit /b 0
