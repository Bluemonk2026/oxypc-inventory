# OxyPC ERP server supervisor — keeps uvicorn alive, restarts on exit.
# Launched by the "OxyPC_ERP" scheduled task (hidden) at logon. Logs to server.log.
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory"
$py = "C:\Python314\python.exe"
$args = @('-m','uvicorn','main:app','--host','0.0.0.0','--port','8000','--workers','1')

while ($true) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path "server.log" -Value "[$ts] [supervisor] starting uvicorn"
    try {
        Start-Process -FilePath $py -ArgumentList $args -NoNewWindow -Wait `
            -RedirectStandardOutput "server.out.log" -RedirectStandardError "server.err.log"
    } catch {
        Add-Content -Path "server.log" -Value "[$ts] [supervisor] launch error: $_"
    }
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path "server.log" -Value "[$ts] [supervisor] uvicorn exited — restarting in 3s"
    Start-Sleep -Seconds 3
}
