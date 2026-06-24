@echo off
REM Removes the OxyQC Diagnose Agent autostart + stops it. No admin needed.
setlocal
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v OxyQCAgent /f >nul 2>&1
taskkill /f /im OxyQC_Agent.exe >nul 2>&1
echo OxyQC Diagnose Agent autostart removed and process stopped.
echo (Files in "%LOCALAPPDATA%\OxyQC" are left in place; delete that folder to fully remove.)
pause
endlocal
