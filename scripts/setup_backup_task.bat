@echo off
REM OxyPC — Install daily backup as a Windows Scheduled Task
REM Run this once as Administrator to register the task.
REM
REM Usage:
REM   scripts\setup_backup_task.bat
REM
REM The task runs daily at 02:00 using the Python interpreter on PATH.

SET TASK_NAME=OxyPC_DailyBackup
SET PYTHON_EXE=python
SET SCRIPT_DIR=%~dp0
SET SCRIPT_PATH=%SCRIPT_DIR%backup_db.py

echo Installing scheduled task: %TASK_NAME%
echo Script: %SCRIPT_PATH%
echo Schedule: Daily at 02:00

schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "\"%PYTHON_EXE%\" \"%SCRIPT_PATH%\"" ^
    /sc DAILY ^
    /st 02:00 ^
    /ru SYSTEM ^
    /rl HIGHEST ^
    /f

IF %ERRORLEVEL% EQU 0 (
    echo.
    echo Task installed successfully.
    echo To verify: schtasks /query /tn "%TASK_NAME%"
    echo To run now: schtasks /run /tn "%TASK_NAME%"
    echo To remove:  schtasks /delete /tn "%TASK_NAME%" /f
) ELSE (
    echo.
    echo ERROR: Task installation failed. Run this script as Administrator.
)
