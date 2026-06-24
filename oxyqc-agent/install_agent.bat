@echo off
REM ===========================================================================
REM  OxyQC Diagnose Agent — PER-USER install. NO admin / NO UAC required.
REM  Copies the agent to %LOCALAPPDATA%, auto-starts it at every logon (HKCU),
REM  and launches it now on http://127.0.0.1:8765 (loopback only).
REM ===========================================================================
setlocal EnableExtensions
set "SRC=%~dp0"
set "DEST=%LOCALAPPDATA%\OxyQC"
if not exist "%DEST%" mkdir "%DEST%" >nul 2>&1

if exist "%SRC%OxyQC_Agent.exe" (
    copy /y "%SRC%OxyQC_Agent.exe" "%DEST%\OxyQC_Agent.exe" >nul
    reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v OxyQCAgent /t REG_SZ /d "\"%DEST%\OxyQC_Agent.exe\"" /f >nul
    start "" "%DEST%\OxyQC_Agent.exe"
) else if exist "%SRC%oxyqc_agent.py" (
    copy /y "%SRC%oxyqc_agent.py" "%DEST%\oxyqc_agent.py" >nul
    reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v OxyQCAgent /t REG_SZ /d "pythonw \"%DEST%\oxyqc_agent.py\"" /f >nul
    start "" pythonw "%DEST%\oxyqc_agent.py"
) else (
    echo [X] OxyQC_Agent.exe or oxyqc_agent.py not found next to this script.
    pause & exit /b 1
)

echo.
echo  OK - OxyQC Diagnose Agent installed for the current user (no admin needed).
echo       - Location : %DEST%
echo       - Autostart: HKCU Run "OxyQCAgent"  (starts at every logon)
echo       - Running  : http://127.0.0.1:8765/diagnose
echo.
echo  Open IQC Entry and click "Diagnose this Device".
echo.
pause
endlocal
