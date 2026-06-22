# OxyPC ERP watchdog — pings the server; if DOWN, restarts it; if UP, does nothing.
# Run on a 30-minute schedule (and at logon) by the "OxyPC_ERP_Watchdog" task.
$ErrorActionPreference = "SilentlyContinue"
$app = "C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory"
$py  = "C:\Python314\python.exe"

$up = $false
try {
    if ((Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/auth/login" -TimeoutSec 8).StatusCode -eq 200) { $up = $true }
} catch { $up = $false }

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
if ($up) {
    Add-Content -Path "$app\watchdog.log" -Value "[$stamp] OK - server responding, no action"
} else {
    Add-Content -Path "$app\watchdog.log" -Value "[$stamp] DOWN - restarting server"
    # clear any half-dead listener squatting the port
    Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    # launch the static .bat launcher fully detached + hidden (logs to server.log)
    Start-Process -FilePath "$app\start_oxypc.bat" -WorkingDirectory $app -WindowStyle Hidden
}
