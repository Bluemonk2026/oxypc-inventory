@echo off
REM PXE image #1 — IQC line. Thin wrapper: forces STATION_MODE=iqc then runs
REM the shared bootstrap next to this file.
set "OXYQC_FORCED_MODE=iqc"
powershell -NoProfile -Command "(Get-Content '%~dp0setup_station.bat') -replace 'set \"STATION_MODE=.*\"','set \"STATION_MODE=iqc\"' | Set-Content '%~dp0setup_station_run.bat'"
call "%~dp0setup_station_run.bat"
