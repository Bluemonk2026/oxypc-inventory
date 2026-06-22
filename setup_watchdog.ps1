# Run ELEVATED (Run as Administrator) ONCE to install the OxyPC watchdog.
# It registers a scheduled task that, every 30 minutes (and at each logon),
# pings the server and restarts it ONLY if it is down. Safe to re-run.

$wd = "C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory\watchdog_server.ps1"

# Remove the old supervisor-loop task if it exists (superseded by the watchdog)
Unregister-ScheduledTask -TaskName "OxyPC_ERP" -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -NoProfile -File `"$wd`""

# Triggers: at every logon, AND every 30 minutes indefinitely
$tLogon  = New-ScheduledTaskTrigger -AtLogOn
$tRepeat = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 30)

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "OxyPC_ERP_Watchdog" -Action $action `
    -Trigger $tLogon, $tRepeat -Settings $settings -Principal $principal -Force | Out-Null

Start-ScheduledTask -TaskName "OxyPC_ERP_Watchdog"

Write-Host "OxyPC_ERP_Watchdog installed:" -ForegroundColor Green
Write-Host "  - pings http://127.0.0.1:8000 every 30 minutes (and at logon)" -ForegroundColor Green
Write-Host "  - restarts the server only when it is down; does nothing when it is up" -ForegroundColor Green
Start-Sleep -Seconds 8
try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/auth/login" -TimeoutSec 6
    Write-Host ("Server check: HTTP " + $r.StatusCode) -ForegroundColor Green
} catch { Write-Host "Server not responding yet; the watchdog will start it within 30 min." -ForegroundColor Yellow }
Write-Host "Press Enter to close..."; [void](Read-Host)
