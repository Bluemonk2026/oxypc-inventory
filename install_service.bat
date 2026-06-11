@echo off
REM OxyPC Windows Service Installer using NSSM
REM Run as Administrator
REM Download NSSM from https://nssm.cc/download first, place nssm.exe in PATH

SET APP_DIR=C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
SET PYTHON=C:\Python313\python.exe
SET SERVICE_NAME=OxyPC_ERP

echo Installing OxyPC ERP as Windows Service...

nssm install %SERVICE_NAME% %PYTHON% "%APP_DIR%\main.py"
nssm set %SERVICE_NAME% AppDirectory %APP_DIR%
nssm set %SERVICE_NAME% AppStdout "%APP_DIR%\logs\service_stdout.log"
nssm set %SERVICE_NAME% AppStderr "%APP_DIR%\logs\service_stderr.log"
nssm set %SERVICE_NAME% AppRotateFiles 1
nssm set %SERVICE_NAME% AppRotateBytes 10485760
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START
nssm set %SERVICE_NAME% ObjectName LocalSystem

mkdir "%APP_DIR%\logs" 2>nul

echo Starting service...
nssm start %SERVICE_NAME%

echo.
echo Service installed. OxyPC will now auto-start on every Windows boot.
echo To check status: nssm status OxyPC_ERP
echo To stop:         nssm stop OxyPC_ERP
echo To uninstall:    nssm remove OxyPC_ERP confirm
pause
