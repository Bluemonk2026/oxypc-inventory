@echo off
REM ===========================================================================
REM  OxyQC Diagnose Agent launcher (run on each inspection STATION).
REM  Serves this station's hardware to the OxyPC web IQC page at
REM  http://127.0.0.1:8765/diagnose  (loopback only — nothing exposed on LAN).
REM ===========================================================================
cd /d "%~dp0"

REM Prefer a built exe if present, else run via Python.
if exist "OxyQC_Agent.exe" ( start "" "OxyQC_Agent.exe" & exit /b )

where pythonw >nul 2>&1 && ( start "OxyQC Agent" pythonw "oxyqc_agent.py" & echo Agent started (background). & exit /b )
where python  >nul 2>&1 && ( python "oxyqc_agent.py" & exit /b )

echo [X] Python not found and OxyQC_Agent.exe missing.
echo     Install Python, or build the exe (see README_AGENT.txt).
pause
