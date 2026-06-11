@echo off
title OxyPC — Stopping Server
color 0C

echo.
echo  Stopping OxyPC UAT Server...
echo.

REM Kill the FastAPI/uvicorn process
taskkill /f /im python.exe >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq OxyPC App" >nul 2>&1

REM Kill ngrok
taskkill /f /im ngrok.exe >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq OxyPC Tunnel" >nul 2>&1

echo  [OK] OxyPC app stopped.
echo  [OK] ngrok tunnel stopped.
echo.
echo  Server has been shut down. Internet link is now invalid.
echo.
pause
