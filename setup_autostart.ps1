# Run this ELEVATED (Run as Administrator) once to install OxyPC ERP as an
# auto-starting, self-healing background task. Safe to re-run.
$ps1 = "C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory\run_server.ps1"

# Free port 8000 (stop any session-bound uvicorn so the task can take over)
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
            -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -NoProfile -File `"$ps1`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
            -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "OxyPC_ERP" -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force
Start-ScheduledTask -TaskName "OxyPC_ERP"

Write-Host "OxyPC_ERP installed and started. It will auto-start at logon and restart itself if it ever exits." -ForegroundColor Green
Start-Sleep -Seconds 6
try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/auth/login" -TimeoutSec 6
    Write-Host ("Server check: HTTP " + $r.StatusCode) -ForegroundColor Green
} catch { Write-Host "Server not responding yet; give it a few seconds." -ForegroundColor Yellow }
Write-Host "Press Enter to close..."; [void](Read-Host)
