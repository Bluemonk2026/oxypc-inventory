@echo off
:: OxyPC Inventory Server — auto-restart loop
:: Logs to server_service.log in the project folder

cd /d "C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory"

:LOOP
echo [%DATE% %TIME%] Starting OxyPC server... >> server_service.log
python -m uvicorn main:app --host 127.0.0.1 --port 8000 >> server_service.log 2>&1
echo [%DATE% %TIME%] Server stopped (exit %ERRORLEVEL%), restarting in 5s... >> server_service.log
timeout /t 5 /nobreak > nul
goto LOOP
