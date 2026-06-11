# scripts\install_service.ps1
# Run as Administrator.
# Downloads NSSM 2.24, installs OxyPCInventory as a Windows Service.

$NssmDir     = "C:\nssm"
$NssmExe     = "$NssmDir\nssm-2.24\win64\nssm.exe"
$ServiceName = "OxyPCInventory"
$AppDir      = "C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory"
$BatchFile   = "$AppDir\scripts\start_server.bat"
$LogDir      = "$AppDir\logs"

# ── 1. Download + extract NSSM ────────────────────────────────────────────
if (-not (Test-Path $NssmExe)) {
    Write-Host "Downloading NSSM 2.24..."
    New-Item -ItemType Directory -Force $NssmDir | Out-Null
    $ZipPath = "$NssmDir\nssm-2.24.zip"
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $ZipPath
    Expand-Archive -Path $ZipPath -DestinationPath $NssmDir -Force
    Write-Host "NSSM extracted to $NssmDir"
} else {
    Write-Host "NSSM already present at $NssmExe"
}

# ── 2. Ensure log directory exists ────────────────────────────────────────
New-Item -ItemType Directory -Force $LogDir | Out-Null

# ── 3. Remove old service if it exists ───────────────────────────────────
$existing = sc.exe query $ServiceName 2>&1
if ($existing -notlike "*does not exist*") {
    Write-Host "Removing existing service $ServiceName..."
    & $NssmExe stop  $ServiceName 2>&1 | Out-Null
    & $NssmExe remove $ServiceName confirm 2>&1 | Out-Null
}

# ── 4. Install service ────────────────────────────────────────────────────
Write-Host "Installing $ServiceName service..."
& $NssmExe install $ServiceName $BatchFile

# ── 5. Configure service settings ─────────────────────────────────────────
& $NssmExe set $ServiceName AppDirectory   $AppDir
& $NssmExe set $ServiceName Start          SERVICE_AUTO_START
& $NssmExe set $ServiceName AppStdout      "$LogDir\service.log"
& $NssmExe set $ServiceName AppStderr      "$LogDir\service_error.log"
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateBytes 10485760   # 10 MB
& $NssmExe set $ServiceName AppRestartDelay 5000       # 5 sec before auto-restart

# ── 6. Start the service ──────────────────────────────────────────────────
Write-Host "Starting $ServiceName..."
& $NssmExe start $ServiceName

Start-Sleep -Seconds 5
$status = (sc.exe query $ServiceName | Select-String "STATE").ToString().Trim()
Write-Host "Service status: $status"

if ($status -like "*RUNNING*") {
    Write-Host "`n✅ OxyPCInventory service is RUNNING."
    Write-Host "   URL: http://localhost:8000"
    Write-Host "   Logs: $LogDir\service.log"
    Write-Host "   Manage: services.msc -> OxyPCInventory"
} else {
    Write-Host "`n❌ Service did not start. Check $LogDir\service_error.log"
}
