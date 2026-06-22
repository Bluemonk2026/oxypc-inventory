@echo off
cd /d "C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory"
"C:\Python314\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 >> server.log 2>&1
