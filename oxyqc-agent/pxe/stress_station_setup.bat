@echo off
REM PXE image #2 — Stress Test / Final QC line. Thin wrapper: forces
REM STATION_MODE=stress then runs the shared bootstrap next to this file.
set "OXYQC_FORCED_MODE=stress"
powershell -NoProfile -Command "(Get-Content '%~dp0setup_station.bat') -replace 'set \"STATION_MODE=.*\"','set \"STATION_MODE=stress\"' | Set-Content '%~dp0setup_station_run.bat'"
call "%~dp0setup_station_run.bat"
