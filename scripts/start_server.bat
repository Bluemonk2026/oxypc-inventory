@echo off
REM scripts\start_server.bat
REM Wrapper invoked by NSSM. Activates venv and starts uvicorn.
REM NSSM will restart this if it exits.

cd /d C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
call venv\Scripts\activate.bat
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
