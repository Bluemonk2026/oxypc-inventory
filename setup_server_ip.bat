@echo off
REM ═══════════════════════════════════════════════════════
REM  OxyPC Inventory Server — One-Time IP & Firewall Setup
REM  Run this ONCE as Administrator on the server machine
REM  Right-click → Run as administrator
REM ═══════════════════════════════════════════════════════

echo.
echo  OxyPC Inventory Server — Network Setup
echo  =======================================
echo.

REM ── Step 1: Open Windows Firewall for port 8000 ──────────────────────────
echo [1/3] Opening firewall port 8000...
netsh advfirewall firewall delete rule name="OxyPC Inventory API" >nul 2>&1
netsh advfirewall firewall add rule ^
    name="OxyPC Inventory API" ^
    dir=in ^
    action=allow ^
    protocol=TCP ^
    localport=8000 ^
    profile=any
echo   Done.

REM ── Step 2: Set static IP 192.168.1.100 on LAN adapter ───────────────────
echo.
echo [2/3] Setting static IP 192.168.1.100 on Wi-Fi / Ethernet...
echo   (Finding LAN adapter...)

REM Find the adapter with 192.168.1.x
FOR /F "tokens=2 delims=:" %%A IN ('ipconfig ^| findstr /C:"192.168.1."') DO (
    SET CURRENT_IP=%%A
)

REM Use PowerShell to find and set the adapter
powershell -ExecutionPolicy Bypass -Command ^
    "$a = Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -like '192.168.1.*' -and $_.IPAddress -ne '192.168.1.100'} | Select-Object -First 1; " ^
    "if ($a) { " ^
        "$iface = $a.InterfaceAlias; " ^
        "Write-Host '  Adapter:' $iface '| Current IP:' $a.IPAddress; " ^
        "Remove-NetIPAddress -InterfaceAlias $iface -IPAddress $a.IPAddress -Confirm:$false -ErrorAction SilentlyContinue; " ^
        "Remove-NetRoute -InterfaceAlias $iface -DestinationPrefix '0.0.0.0/0' -Confirm:$false -ErrorAction SilentlyContinue; " ^
        "New-NetIPAddress -InterfaceAlias $iface -IPAddress '192.168.1.100' -PrefixLength 24 -DefaultGateway '192.168.1.1' | Out-Null; " ^
        "Set-DnsClientServerAddress -InterfaceAlias $iface -ServerAddresses ('8.8.8.8','8.8.4.4'); " ^
        "Write-Host '  Static IP 192.168.1.100 set on' $iface " ^
    "} else { " ^
        "Write-Host '  No 192.168.1.x adapter found — set IP manually in Network Settings' " ^
    "}"
echo   Done.

REM ── Step 3: Set server to auto-start on Windows login ────────────────────
echo.
echo [3/3] Registering OxyPC server as startup task...

SET "SERVER_DIR=%~dp0"
SET "START_CMD=%SERVER_DIR%start_server.bat"

schtasks /delete /tn "OxyPC Inventory Server" /f >nul 2>&1
schtasks /create ^
    /tn "OxyPC Inventory Server" ^
    /tr "\"%START_CMD%\"" ^
    /sc onlogon ^
    /rl highest ^
    /f >nul 2>&1
echo   Registered: starts automatically on login.

echo.
echo ═══════════════════════════════════════════════════════
echo   Setup complete!
echo.
echo   Server IP:   192.168.1.100
echo   Server Port: 8000
echo   URL:         http://192.168.1.100:8000
echo.
echo   Next steps:
echo     1. Restart this machine (for IP change to take effect)
echo     2. Run start_server.bat to start the server
echo     3. From any inspection laptop, open OxyQC.exe
echo        and set server URL to: http://192.168.1.100:8000
echo ═══════════════════════════════════════════════════════
echo.
pause
