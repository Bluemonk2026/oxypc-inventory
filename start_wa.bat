@echo off
REM Launches the OxyPC WhatsApp bridge (whatsapp-web.js, multi-session) on port 3001.
REM Run this alongside start_oxypc.bat. Logs to wa-service\wa-service.log
cd /d "C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory\wa-service"
node index.js >> wa-service.log 2>&1
