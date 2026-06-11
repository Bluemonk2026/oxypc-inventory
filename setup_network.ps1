# ═══════════════════════════════════════════════════════
#  OxyPC Inventory — Network & Firewall Setup
#  Run ONCE as Administrator on the server machine:
#
#    Right-click PowerShell → Run as Administrator
#    cd "C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory"
#    powershell -ExecutionPolicy Bypass -File setup_network.ps1
# ═══════════════════════════════════════════════════════

param(
    [string]$TargetIP   = "192.168.1.100",
    [string]$Gateway    = "192.168.1.1",
    [int]   $Port       = 8000,
    [string]$PrefixLen  = "24"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  OxyPC Inventory — Network Setup" -ForegroundColor Cyan
Write-Host "  ================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Firewall ───────────────────────────────────────────────────────────────
Write-Host "[1/3] Opening Windows Firewall port $Port..." -ForegroundColor Yellow

$existing = Get-NetFirewallRule -DisplayName "OxyPC Inventory API" -ErrorAction SilentlyContinue
if ($existing) {
    Remove-NetFirewallRule -DisplayName "OxyPC Inventory API" -ErrorAction SilentlyContinue
}
New-NetFirewallRule `
    -DisplayName "OxyPC Inventory API" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort $Port `
    -Action Allow `
    -Profile Any | Out-Null

Write-Host "  ✓ Port $Port open (inbound TCP, all profiles)" -ForegroundColor Green

# ── 2. Static IP ──────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[2/3] Assigning static IP $TargetIP to LAN adapter..." -ForegroundColor Yellow

# Find the Wi-Fi or Ethernet adapter that has a 192.168.1.x address
$current = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -like "192.168.1.*" -and $_.IPAddress -ne $TargetIP } |
    Select-Object -First 1

if (-not $current) {
    # Check if target IP is already set
    $already = Get-NetIPAddress -IPAddress $TargetIP -ErrorAction SilentlyContinue
    if ($already) {
        Write-Host "  ✓ $TargetIP already assigned on $($already.InterfaceAlias)" -ForegroundColor Green
    } else {
        Write-Host "  ⚠ No 192.168.1.x adapter found." -ForegroundColor Red
        Write-Host "    Please set IP manually:" -ForegroundColor Red
        Write-Host "    Control Panel → Network → Adapter → IPv4 Properties" -ForegroundColor Red
        Write-Host "    IP: $TargetIP   Mask: 255.255.255.0   Gateway: $Gateway" -ForegroundColor Red
    }
} else {
    $iface = $current.InterfaceAlias
    $oldIP  = $current.IPAddress
    Write-Host "  Adapter : $iface" -ForegroundColor Gray
    Write-Host "  Old IP  : $oldIP  →  New IP: $TargetIP" -ForegroundColor Gray

    # Remove old IP + default route
    Remove-NetIPAddress -InterfaceAlias $iface -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue
    Remove-NetRoute -InterfaceAlias $iface -DestinationPrefix "0.0.0.0/0" -Confirm:$false -ErrorAction SilentlyContinue

    # Assign new static IP
    New-NetIPAddress `
        -InterfaceAlias $iface `
        -IPAddress $TargetIP `
        -PrefixLength ([int]$PrefixLen) `
        -DefaultGateway $Gateway | Out-Null

    # Set DNS
    Set-DnsClientServerAddress -InterfaceAlias $iface -ServerAddresses ("8.8.8.8", "8.8.4.4")

    Write-Host "  ✓ Static IP $TargetIP set on $iface" -ForegroundColor Green
    Write-Host "  ✓ DNS: 8.8.8.8, 8.8.4.4" -ForegroundColor Green
}

# ── 3. Auto-start task ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[3/3] Registering OxyPC as Windows startup task..." -ForegroundColor Yellow

$serverDir  = $PSScriptRoot
$pythonExe  = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) { $pythonExe = "python" }
$mainScript = Join-Path $serverDir "main.py"
$action     = New-ScheduledTaskAction -Execute $pythonExe -Argument $mainScript -WorkingDirectory $serverDir
$trigger    = New-ScheduledTaskTrigger -AtLogOn
$settings   = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal  = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest

Unregister-ScheduledTask -TaskName "OxyPC Inventory Server" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask `
    -TaskName "OxyPC Inventory Server" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal | Out-Null

Write-Host "  ✓ Auto-starts on login as: OxyPC Inventory Server" -ForegroundColor Green

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "   Setup Complete!" -ForegroundColor Green
Write-Host ""
Write-Host "   Server URL  : http://$TargetIP`:$Port" -ForegroundColor White
Write-Host "   API Key     : oxyqc-default-key-change-me" -ForegroundColor White
Write-Host "   Dashboard   : http://$TargetIP`:$Port/dashboard" -ForegroundColor White
Write-Host ""
Write-Host "   OxyQC.exe settings → Server URL:" -ForegroundColor Gray
Write-Host "     http://$TargetIP`:$Port" -ForegroundColor Yellow
Write-Host "  ══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "  ⚠  A restart may be needed for the IP change to take effect." -ForegroundColor Yellow
Write-Host ""

Read-Host "  Press Enter to exit"
