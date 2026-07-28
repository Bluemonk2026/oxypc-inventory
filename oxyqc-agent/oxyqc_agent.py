#!/usr/bin/env python
"""
OxyQC Local Diagnose Agent
==========================
Runs on an INSPECTION STATION (the PC/Mac the technician uses). Exposes:

    GET  http://127.0.0.1:8765/diagnose   -> that station's hardware as JSON

The OxyPC web IQC page calls this from the browser. Because 127.0.0.1 in a
browser always means the machine the browser runs on, this reads the LOCAL
station's hardware — never the server's.

Stdlib only (no third-party deps). Supports Windows (WMI/CIM via PowerShell)
and macOS (system_profiler / ioreg / networksetup — all built-in, no admin
or sudo needed for any of the commands used here).

Run:    python oxyqc_agent.py        (or pythonw for no console, Windows only)
Build (Windows):  pyinstaller --onefile --noconsole --name Diagnose_Device_Agent oxyqc_agent.py
Build (macOS):    pyinstaller --onefile --name Diagnose_Device_Agent oxyqc_agent.py
                  (must be run ON a Mac — PyInstaller does not cross-compile)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import platform
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8765
# Bump this whenever detect()/probe logic changes materially. Lets a freshly
# downloaded exe recognise a stale already-running instance and replace it
# (see _shutdown_running_instance) instead of silently no-op'ing behind it.
AGENT_VERSION = "2026-07-28.1"
IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

# Per-user install target (no admin/sudo needed)
if IS_MAC:
    _APPDIR = os.path.expanduser("~/Library/Application Support/Diagnose_Device_Agent")
    _TARGET = os.path.join(_APPDIR, "Diagnose_Device_Agent")
    _LAUNCH_AGENT_DIR = os.path.expanduser("~/Library/LaunchAgents")
    _LAUNCH_AGENT_LABEL = "com.oxypc.diagnoseagent"
    _LAUNCH_AGENT_PATH = os.path.join(_LAUNCH_AGENT_DIR, f"{_LAUNCH_AGENT_LABEL}.plist")
else:
    _APPDIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Diagnose_Device_Agent")
    _TARGET = os.path.join(_APPDIR, "Diagnose_Device_Agent.exe")
    _RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    _AUTOSTART_NAME = "Diagnose_Device_Agent"


def _set_autostart(path):
    """Register per-user autostart. Best-effort, never fatal."""
    if IS_MAC:
        try:
            os.makedirs(_LAUNCH_AGENT_DIR, exist_ok=True)
            plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{_LAUNCH_AGENT_LABEL}</string>
    <key>ProgramArguments</key><array><string>{path}</string></array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><false/>
</dict>
</plist>
"""
            with open(_LAUNCH_AGENT_PATH, "w") as fh:
                fh.write(plist)
            subprocess.run(["launchctl", "load", "-w", _LAUNCH_AGENT_PATH],
                            capture_output=True, timeout=10)
        except Exception:
            pass
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, _AUTOSTART_NAME, 0, winreg.REG_SZ, f'"{path}"')
    except Exception:
        pass


def _shutdown_running_instance():
    """Ask any already-running instance (old or new) to exit, so this run —
    whether it's a fresh download replacing a stale install, or the
    just-installed copy about to bind the port — doesn't fight over the
    locked exe file or the port. Best-effort; safe no-op if nothing is
    listening. Polls briefly afterwards so the file lock has time to clear
    before the caller tries to overwrite it."""
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/quit", timeout=1.5)
    except Exception:
        return  # nothing was listening, or it didn't respond — nothing to wait for
    for _ in range(20):  # up to ~4s for the old process to fully exit and release the file
        time.sleep(0.2)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/ping", timeout=0.3)
        except Exception:
            return  # port is free again — old process has exited
    # gave up waiting; caller's copy/bind attempt will just fail and no-op as before


def _self_install():
    """When run as a frozen binary from somewhere other than the canonical
    per-user install dir, copy self there, register autostart, launch that
    copy, and signal the caller to exit. All per-user => no UAC / no sudo.
    Returns True if a relaunch was started (caller should exit)."""
    if not getattr(sys, "frozen", False):
        return False  # running as a .py script: don't self-install
    cur = os.path.abspath(sys.executable)
    try:
        os.makedirs(_APPDIR, exist_ok=True)
    except Exception:
        pass
    if os.path.normcase(cur) == os.path.normcase(_TARGET):
        _set_autostart(_TARGET)   # already the canonical copy
        return False
    _shutdown_running_instance()  # release the lock on _TARGET / the port if an old copy is running
    try:
        shutil.copy2(cur, _TARGET)   # note: drops Mark-of-the-Web -> no SmartScreen on the copy
        if IS_MAC:
            os.chmod(_TARGET, 0o755)
    except Exception:
        _set_autostart(cur)          # target busy/locked: just register where we are
        return False
    _set_autostart(_TARGET)
    try:
        if IS_WINDOWS:
            subprocess.Popen([_TARGET], creationflags=0x08000000)  # CREATE_NO_WINDOW
        else:
            subprocess.Popen([_TARGET], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              start_new_session=True)
        return True
    except Exception:
        return False

_PS_DIAGNOSE = r'''
$ErrorActionPreference='SilentlyContinue'
$cpu=Get-CimInstance Win32_Processor|Select-Object -First 1
$cs=Get-CimInstance Win32_ComputerSystem
$bios=Get-CimInstance Win32_BIOS|Select-Object -First 1
$os=Get-CimInstance Win32_OperatingSystem
$encl=Get-CimInstance Win32_SystemEnclosure|Select-Object -First 1
$batt=Get-CimInstance Win32_Battery|Select-Object -First 1
$gpu=Get-CimInstance Win32_VideoController|Where-Object {$_.Name -notmatch 'Basic|Remote|Meta|Mirror|DisplayLink|USB'}|Select-Object -First 1
$pd=@(Get-PhysicalDisk|Where-Object {$_.BusType -ne 'USB' -and $_.Size -gt 8GB}|ForEach-Object{[ordered]@{type="$($_.MediaType)";sizeGB=[math]::Round($_.Size/1GB);make="$($_.FriendlyName)".Trim();rpm=$_.SpindleSpeed}})
$ram=@(Get-CimInstance Win32_PhysicalMemory -EA SilentlyContinue|ForEach-Object{[ordered]@{capacityGB=[math]::Round($_.Capacity/1GB);speed=$_.Speed;make="$($_.Manufacturer)".Trim();memType=$_.SMBIOSMemoryType}})
$bh=$null
$full=(Get-CimInstance -Namespace root\wmi -ClassName BatteryFullChargedCapacity -EA SilentlyContinue|Select-Object -First 1).FullChargedCapacity
$des=(Get-CimInstance -Namespace root\wmi -ClassName BatteryStaticData -EA SilentlyContinue|Select-Object -First 1).DesignedCapacity
if($des -and $des -gt 0 -and $full -and $full -gt 0){$bh=[math]::Round(($full/$des)*100)}
if(-not $bh -and $batt){$fc=$batt.FullChargeCapacity;$dc=$batt.DesignCapacity;if($fc -gt 0 -and $dc -gt 0){$bh=[math]::Round($fc/$dc*100)}}
if(-not $bh -and $batt){try{$rf=[System.IO.Path]::Combine($env:TEMP,'bh_'+[guid]::NewGuid().ToString('N').Substring(0,8)+'.html');$null=powercfg /batteryreport /output $rf 2>&1;if(Test-Path $rf){$h=Get-Content $rf -Raw;Remove-Item $rf -Force -EA SilentlyContinue;$m1=$null;$m2=$null;if($h -match '(?si)DESIGN CAPACITY.{0,200}?([\d,]+)\s*mWh'){$m1=[int64]($matches[1]-replace',','')};if($h -match '(?si)FULL CHARGE CAPACITY.{0,200}?([\d,]+)\s*mWh'){$m2=[int64]($matches[1]-replace',','')};if($m1 -gt 0 -and $m2 -gt 0){$bh=[math]::Round($m2/$m1*100)}}}catch{}}
$batt_wh=$null
if($full -gt 0){$batt_wh=[math]::Round($full/1000.0, 1)}
$storage_health=$null
try{
  $bigDisks=@(Get-PhysicalDisk -EA SilentlyContinue|Where-Object{$_.BusType -ne 'USB' -and $_.Size -gt 8GB})
  if($bigDisks.Count -gt 0){
    # Prefer real SMART/NVMe wear-level data (Wear = % of rated life used) so
    # Storage Health % reflects actual drive wear, not just a healthy/unhealthy flag.
    # Get-StorageReliabilityCounter commonly requires elevation — on a standard
    # (non-admin) user session it throws "Access to a CIM resource was not
    # available", caught below, falling through to the status-based check.
    # Some drivers also misreport Wear=100 as an "unsupported" sentinel rather
    # than $null when the counter genuinely isn't tracked, which would read as
    # a fully-worn (0% health) drive — reject exactly 100 as unreliable too.
    $wears=@()
    foreach($d in $bigDisks){
      try{$rc=$d|Get-StorageReliabilityCounter -EA SilentlyContinue;if($rc -and $rc.Wear -ne $null -and $rc.Wear -ge 0 -and $rc.Wear -lt 100){$wears+=(100-[double]$rc.Wear)}}catch{}
    }
    if($wears.Count -gt 0){
      $storage_health=[math]::Round(($wears|Measure-Object -Average).Average)
    } else {
      # Fallback: fraction of disks reporting Healthy/OK status. Never collapse
      # to a bare 0 when the signal is inconclusive (e.g. HealthStatus reports
      # something other than the exact string 'Healthy' even though the disk
      # is fine per OperationalStatus) — leave blank rather than falsely
      # implying a dead drive.
      $disksHealth=@($bigDisks|Select-Object HealthStatus,OperationalStatus)
      $okCount=($disksHealth|Where-Object{$_.HealthStatus -eq 'Healthy' -or $_.OperationalStatus -eq 'OK'}).Count
      if($okCount -eq $disksHealth.Count){$storage_health=100}
      elseif($okCount -gt 0){$storage_health=[math]::Round(($okCount/$disksHealth.Count)*100)}
      # else: leave $storage_health as $null (inconclusive) instead of 0
    }
  }
}catch{}
if($storage_health -eq $null){
  # Last resort: Get-PhysicalDisk / the Storage Management module can be
  # missing entirely on some Windows editions/builds, throwing before
  # $bigDisks is even populated above. Win32_DiskDrive is the classic WMI
  # class (present since Windows XP) and needs no extra module.
  try{
    $legacyDisks=@(Get-CimInstance Win32_DiskDrive -EA SilentlyContinue|Where-Object{$_.InterfaceType -ne 'USB' -and $_.Size -gt 8GB*1})
    if($legacyDisks.Count -gt 0){
      $okCount2=($legacyDisks|Where-Object{$_.Status -eq 'OK'}).Count
      if($okCount2 -eq $legacyDisks.Count){$storage_health=100}
      elseif($okCount2 -gt 0){$storage_health=[math]::Round(($okCount2/$legacyDisks.Count)*100)}
    }
  }catch{}
}
$fan_working=$null;$fan_rpm=$null
try{$allFans=@(Get-CimInstance -Namespace root\wmi -ClassName Win32_Fan -EA SilentlyContinue);if($allFans.Count -gt 0){$fan_working='Yes';$spd=$allFans|Where-Object{$_.DesiredSpeed -gt 0};if($spd){$fan_rpm=[int]$spd[0].DesiredSpeed}}}catch{}
if(-not $fan_working){try{$fd=@(Get-CimInstance Win32_PnPEntity -EA SilentlyContinue|Where-Object{$_.DeviceID -match 'ACPI\\PNP0C0B'});if($fd.Count -gt 0){$ok=$fd|Where-Object{$_.ConfigManagerErrorCode -eq 0 -or $_.ConfigManagerErrorCode -eq $null};$fan_working=if($ok){'Yes'}else{'No'}}}catch{}}
$scr=$null
$mons=@(Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorBasicDisplayParams -EA SilentlyContinue)
foreach($mn in $mons){if($mn.MaxHorizontalImageSize -gt 0 -and $mn.MaxVerticalImageSize -gt 0){$dd=[math]::Round([math]::Sqrt(($mn.MaxHorizontalImageSize*$mn.MaxHorizontalImageSize)+($mn.MaxVerticalImageSize*$mn.MaxVerticalImageSize))/2.54,1);if($dd -gt 5 -and $dd -lt 40){if(-not $scr -or $dd -lt $scr){$scr=$dd}}}}
# device presence + working state: 'ok' | 'error' | 'absent'
function st($q){ if(-not $q -or $q.Count -eq 0){return 'absent'}; $bad=$q|Where-Object {$_.ConfigManagerErrorCode -ne $null -and $_.ConfigManagerErrorCode -ne 0}; if($bad){return 'error'}; return 'ok' }
$kbd=@(Get-CimInstance Win32_Keyboard)
$ptr=@(Get-CimInstance Win32_PointingDevice)
$snd=@(Get-CimInstance Win32_SoundDevice|Where-Object {$_.Name -notmatch 'Virtual|Remote|Steam'})
$cam=@(Get-CimInstance Win32_PnPEntity|Where-Object {$_.PNPClass -eq 'Camera' -or $_.Name -match 'web ?cam|integrated camera'})
$nics=@(Get-CimInstance Win32_NetworkAdapter|Where-Object {$_.PhysicalAdapter -eq $true})
$wifi=@($nics|Where-Object {$_.Name -match 'Wi-?Fi|Wireless|802\.11|Dual Band|AX2|Centrino'})
$eth=@($nics|Where-Object {($_.Name -match 'Ethernet|Gigabit|GbE|Realtek PCIe|Killer E|I2[12]9') -and $_.Name -notmatch 'Wi-?Fi|Wireless|Bluetooth|Virtual|VPN|TAP|Loopback|VMware|Hyper-V' -and $_.PNPDeviceID -notmatch '^USB'})
$dvd=@(Get-CimInstance Win32_CDROMDrive|Where-Object {$_.Name -notmatch 'Virtual'})
$usb=@(Get-CimInstance Win32_USBController)
$ucm=@(Get-CimInstance Win32_PnPEntity -EA SilentlyContinue|Where-Object {$_.Name -match 'UCSI|USB Connector Manager|USB Type-C|USB-C|USB4|Thunderbolt'})
$clk=[math]::Round($cpu.MaxClockSpeed/1000.0,2)
$onAC=$true; if($batt -and $batt.BatteryStatus -eq 1){$onAC=$false}
[ordered]@{
 manufacturer="$($cs.Manufacturer)";model="$($cs.Model)";sysfamily="$($cs.SystemFamily)";serial="$($bios.SerialNumber)";
 cpu="$(($cpu.Name).Trim())";cpu_make="$($cpu.Manufacturer)".Trim();clock=$clk;cores=$cpu.NumberOfCores;ram_gb=[math]::Round($cs.TotalPhysicalMemory/1GB);
 chassis=@($encl.ChassisTypes);has_battery=[bool]$batt;battery_pct=$batt.EstimatedChargeRemaining;battery_health=$bh;on_ac=$onAC;
 screen_in=$scr;gpu="$($gpu.Name)";os="$($os.Caption)";disks=$pd;ram_sticks=$ram;
 kbd=(st $kbd);touchpad=(st $ptr);sound=(st $snd);camera=(st $cam);wifi=(st $wifi);usbctrl=(st $usb);
 dvd_present=[bool]$dvd.Count;ethernet_count=$eth.Count;usbc_hint=$ucm.Count;has_gpu=[bool]$gpu;mons_count=$mons.Count;
 battery_wh=$batt_wh;storage_health=$storage_health;fan_working=$fan_working;fan_rpm=$fan_rpm
} | ConvertTo-Json -Depth 5 -Compress
'''

_STD_CAPACITIES = [32, 64, 120, 128, 240, 256, 320, 480, 500, 512, 640, 750, 1000, 1024, 2000, 2048, 4000, 4096]


def _snap_capacity(gb):
    try:
        gb = int(gb)
    except (TypeError, ValueError):
        return None
    return min(_STD_CAPACITIES, key=lambda s: abs(s - gb)) if gb > 0 else None


def _intel_gen(cpu):
    if not cpu:
        return None
    if "Core Ultra" in cpu:
        return "Core Ultra"
    m = re.search(r"i[3579][- ]?(\d{3,5})", cpu)
    if m:
        n = m.group(1)
        # SKU-number → generation:
        #   5 digits (e.g. 10750)        -> first 2  -> 10th
        #   4 digits starting with 1     -> first 2  -> 10th..14th (1135G7, 1235U, 1335U)
        #   4 digits starting with 2-9   -> first 1  -> 2nd..9th   (8250U, 7200U)
        if len(n) >= 5:
            g = n[:2]
        elif len(n) == 4:
            g = n[:2] if n[0] == "1" else n[:1]
        else:
            return None   # 3-digit (1st-gen era) — too ambiguous, leave blank
        try:
            gi = int(g)
        except ValueError:
            return None
        if 4 <= gi <= 20:                      # only gens the form lists (4th+)
            return f"{gi}th Gen"
    return None


def _generation(cpu):
    g = _intel_gen(cpu)
    if g:
        return g
    if cpu:
        m = re.search(r"Ryzen\s+([3579])", cpu)
        if m and m.group(1) in ("3", "5", "7"):
            return f"AMD Ryzen {m.group(1)}"
        m2 = re.search(r"Apple\s+(M\d+)\s*(Pro|Max|Ultra)?", cpu)
        if m2:
            return f"Apple {m2.group(1)}{(' ' + m2.group(2)) if m2.group(2) else ''}"
    return None


def _cpu_make(cpu, manufacturer=None):
    """Derive Intel / AMD / Apple from the CPU manufacturer string (Windows
    Win32_Processor.Manufacturer) or by parsing the CPU/chip name (macOS)."""
    src = f"{manufacturer or ''} {cpu or ''}".lower()
    if "intel" in src or "genuineintel" in src:
        return "Intel"
    if "amd" in src or "authenticamd" in src or "ryzen" in src:
        return "AMD"
    if "apple" in src or re.match(r"^\s*m\d", (cpu or "").strip(), re.I):
        return "Apple"
    return None


def _clean_cpu(name, clock):
    """Return 'Intel Core i9-12900H @ 2.50 GHz' style — processor + speed only."""
    if not name:
        return None
    s = name
    for junk in ("(R)", "(TM)", "(r)", "(tm)"):
        s = s.replace(junk, "")
    s = re.sub(r"\bCPU\b", "", s)
    s = re.sub(r"\b\d+(st|nd|rd|th)\s+Gen\s+", "", s, flags=re.I)  # drop "12th Gen "
    s = re.sub(r"@.*$", "", s)                                     # drop any existing @ speed
    s = re.sub(r"\s+", " ", s).strip()
    try:
        if clock and float(clock) > 0:
            return f"{s} @ {float(clock):.2f} GHz"
    except (TypeError, ValueError):
        pass
    return s


_SCREEN_MAP = {11.6: '11.6"', 12.5: '12.5"', 13.3: '13.3"', 14.0: '14.0"',
               15.6: '15.6"', 17.3: '17.3"', 18.5: '18.5"', 21.5: '21.5"', 24.0: '24"'}


def _snap_screen(d):
    try:
        d = float(d)
    except (TypeError, ValueError):
        return None
    best = min(_SCREEN_MAP, key=lambda s: abs(s - d))
    if abs(best - d) > 2.0:   # far from any standard panel (likely an external monitor)
        return None
    return _SCREEN_MAP[best]


def _yn3(state):
    """Map device state to the form's Yes / No options (faulty or absent → No)."""
    return {"ok": "Yes", "error": "No", "absent": "No"}.get(state)


# SMBIOS memory-type codes (DMTF SMBIOS spec, Type 17 "Memory Type" field) —
# Win32_PhysicalMemory.SMBIOSMemoryType returns these numeric codes.
_SMBIOS_RAM_TYPE = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5",
                    28: "LPDDR", 29: "LPDDR2", 30: "LPDDR3", 31: "LPDDR4"}


def _ram_type_label(mem_type):
    """Map a SMBIOSMemoryType numeric code (Windows) to a DDR label; on macOS
    dimm_type already arrives as a string (e.g. "DDR4") — pass through as-is."""
    if mem_type is None or mem_type == "":
        return ""
    if isinstance(mem_type, str) and not mem_type.isdigit():
        return mem_type.upper().replace(" ", "")
    try:
        return _SMBIOS_RAM_TYPE.get(int(mem_type), "")
    except (TypeError, ValueError):
        return ""


def format_ram_summary(sticks):
    """sticks: list of dicts with keys capacityGB, memType, speed, make.
    Produces e.g. "16GB_DDR4_2300MHz_Samsung, 8GB_DDR4_2133MHz_Crucial" —
    a stick with no usable size is skipped; missing type/speed/make are
    simply omitted from that stick's segment rather than showing blank
    placeholders."""
    parts = []
    for s in sticks or []:
        gb = s.get("capacityGB")
        if not gb:
            continue
        segs = [f"{int(gb)}GB"]
        t = _ram_type_label(s.get("memType"))
        if t:
            segs.append(t)
        speed = str(s.get("speed") or "").strip()
        if speed and speed not in ("0",):
            segs.append(speed)
        make = str(s.get("make") or "").strip()
        if make:
            segs.append(make)
        parts.append("_".join(segs))
    return ", ".join(parts)


def format_hdd_summary(drives):
    """drives: list of dicts with keys sizeGB, type ('SSD'/'HDD'), rpm, make.
    Produces e.g. "520GB_SSD_5400RPM_Samsung, 1TB_SSD_7200RPM_Seagate".
    Size is expressed in GB unless >=1000GB, then shown as whole TB (matches
    the spec's own "1TB_SSD_..." example)."""
    parts = []
    for d in drives or []:
        gb = d.get("sizeGB")
        if not gb:
            continue
        gb = int(gb)
        size_label = f"{round(gb / 1000)}TB" if gb >= 1000 else f"{gb}GB"
        segs = [size_label]
        dtype = str(d.get("type") or "").strip().upper()
        if dtype:
            segs.append(dtype)
        rpm = d.get("rpm")
        if rpm:
            segs.append(str(int(rpm)))
        make = str(d.get("make") or "").strip()
        if make:
            segs.append(make)
        parts.append("_".join(segs))
    return ", ".join(parts)


def _probe_windows():
    """Run the PowerShell/CIM probe. Returns (info_dict, err)."""
    ps = shutil.which("powershell") or "powershell"
    kw = {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    try:
        r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", _PS_DIAGNOSE],
                           capture_output=True, text=True, timeout=45, **kw)
    except Exception as e:
        return None, f"hardware probe failed: {e}"
    raw = (r.stdout or "").strip()
    if not raw:
        return None, (r.stderr or "no output from hardware probe").strip()[:200]
    try:
        return json.loads(raw), None
    except Exception:
        return None, "could not parse hardware probe output"


def _sp(datatype):
    """Run `system_profiler -json <datatype>` and return the parsed top-level list
    for that datatype, or [] on any failure. Never raises."""
    try:
        r = subprocess.run(["system_profiler", "-json", datatype],
                            capture_output=True, text=True, timeout=20)
        data = json.loads(r.stdout or "{}")
        return data.get(datatype) or []
    except Exception:
        return []


def _ioreg_battery():
    """Read AppleSmartBattery properties via ioreg. Returns a dict of best-effort
    numeric fields; missing keys just aren't present. Never raises."""
    out = {}
    try:
        r = subprocess.run(["ioreg", "-rn", "AppleSmartBattery"], capture_output=True, text=True, timeout=10)
        text = r.stdout or ""
        if not text.strip():
            return out
        out["present"] = True
        for key in ("DesignCapacity", "MaxCapacity", "AppleRawMaxCapacity",
                    "CurrentCapacity", "AppleRawCurrentCapacity", "Voltage", "CycleCount"):
            m = re.search(rf'"{key}"\s*=\s*(\d+)', text)
            if m:
                out[key] = int(m.group(1))
        out["is_charging"] = bool(re.search(r'"IsCharging"\s*=\s*Yes', text))
        out["external_connected"] = bool(re.search(r'"ExternalConnected"\s*=\s*Yes', text))
    except Exception:
        pass
    return out


# Best-effort USB-C/Thunderbolt port counts by Mac model family. Apple doesn't
# expose an exact physical port count via any read-only API, so — same as the
# Windows probe's USB estimate — this is a starting point the technician
# verifies, not a guarantee.
_MAC_PORT_ESTIMATES = [
    (r"MacBook Air", 2),
    (r"MacBook Pro.*1[46]", 3),
    (r"MacBook Pro", 2),
    (r"Mac Studio", 4),
    (r"Mac mini", 2),
    (r"Mac Pro", 2),
    (r"iMac", 2),
]


def _mac_usb_c_estimate(model_name):
    for pattern, count in _MAC_PORT_ESTIMATES:
        if re.search(pattern, model_name or "", re.I):
            return count
    return 0


def _mac_physical_disk_ids():
    """Return internal physical disk identifiers (e.g. ['disk0']) by parsing
    `diskutil list`, skipping external/virtual disks. No sudo required."""
    ids = []
    try:
        r = subprocess.run(["diskutil", "list"], capture_output=True, text=True, timeout=10)
        for block in re.split(r"\n(?=/dev/)", r.stdout or ""):
            m = re.match(r"/dev/(disk\d+)\s*\(([^)]*)\)", block)
            if m and "internal" in m.group(2) and "physical" in m.group(2):
                ids.append(m.group(1))
    except Exception:
        pass
    return ids


def _mac_physical_disks():
    """Return one entry per internal PHYSICAL disk (via `diskutil info -plist`
    on each id from _mac_physical_disk_ids()) instead of per APFS volume.

    SPStorageDataType (system_profiler) lists APFS *volumes*, not physical
    disks — a single container shows up as both "Macintosh HD" and
    "Macintosh HD - Data" (plus Preboot/VM/Update on some setups), and EVERY
    one of those volumes reports size_in_bytes for the FULL container, not
    its own share. Summing that list double- (or triple-) counts the real
    physical disk capacity. `diskutil info` on the physical /dev/diskN node
    gives the true, single TotalSize plus a direct SolidState flag."""
    disks = []
    for disk_id in _mac_physical_disk_ids():
        try:
            r = subprocess.run(["diskutil", "info", "-plist", disk_id],
                                capture_output=True, timeout=10)
            import plistlib
            data = plistlib.loads(r.stdout)
        except Exception:
            continue
        size_bytes = data.get("TotalSize") or data.get("Size")
        if not size_bytes:
            continue
        gb = round(int(size_bytes) / (1024 ** 3))
        if gb <= 30:
            continue
        is_ssd = data.get("SolidState")
        disk_type = "SSD" if is_ssd else "HDD"
        disks.append({
            "type": disk_type, "sizeGB": gb,
            "make": data.get("MediaName") or "",
            "rpm": 0 if disk_type == "SSD" else None,
        })
    return disks


def _mac_storage_health():
    """Best-effort per-disk wear percentage for internal storage.

    Apple's own internal NVMe controller doesn't expose SMART wear data through
    any built-in, no-sudo API — so this only produces a real percentage when
    `smartctl` (smartmontools, e.g. `brew install smartmontools`) is present on
    the technician's station. Without it, returns None rather than a fabricated
    number; the technician's own eyes (drive age / diskutil health) still apply.
    """
    smartctl = shutil.which("smartctl")
    if not smartctl:
        return None
    healths = []
    for disk_id in _mac_physical_disk_ids():
        try:
            # smartctl usually needs root to open the raw device on macOS — under
            # a normal (non-sudo) technician session this typically fails and
            # either raises here or returns incomplete JSON with the fields
            # below simply absent, which the .get() chains below already treat
            # as "no data" rather than a fabricated value.
            r = subprocess.run([smartctl, "-a", "-j", f"/dev/{disk_id}"],
                                capture_output=True, text=True, timeout=15)
            data = json.loads(r.stdout or "{}")
        except Exception:
            continue
        # NVMe: percentage_used is "% of rated endurance consumed" -> health = 100 - used.
        # Reject out-of-range readings (e.g. 255, a common raw "field not
        # populated" sentinel in some firmware) rather than letting them clamp
        # to a false 0% — same class of bug fixed on the Windows side.
        used = (data.get("nvme_smart_health_information_log") or {}).get("percentage_used")
        if isinstance(used, (int, float)) and 0 <= used <= 100:
            healths.append(100 - used)
            continue
        # SATA SSD: attribute 202 (SSD Life Left) or 177 (Wear Leveling Count) is
        # already a remaining-life percentage. A raw value of exactly 0 is far
        # more often an unsupported/placeholder field than a genuinely dead
        # drive, so treat it as inconclusive rather than reporting 0% health.
        for attr in (data.get("ata_smart_attributes") or {}).get("table", []):
            value = attr.get("value")
            if attr.get("id") in (202, 177) and isinstance(value, (int, float)) and 0 < value <= 100:
                healths.append(value)
                break
    if not healths:
        return None
    return round(sum(healths) / len(healths))


def _probe_mac():
    """Gather the same info-dict schema as _probe_windows(), using macOS
    command-line tools (system_profiler, ioreg, networksetup) — every command
    here is a read-only query available to any logged-in user, no sudo."""
    hw_list = _sp("SPHardwareDataType")
    hw = hw_list[0] if hw_list else {}

    model_name = hw.get("machine_name") or hw.get("model_name") or hw.get("machine_model") or ""
    model_id = hw.get("machine_model") or model_name
    serial = hw.get("serial_number", "")
    chip = hw.get("chip_type") or hw.get("cpu_type") or ""
    # On Apple Silicon, system_profiler's "machine_name" is only ever the
    # generic line ("MacBook Pro"), never the full marketing name with
    # size/year/chip the way Windows' Win32_ComputerSystem.Model returns an
    # exact vendor model string — Apple simply doesn't expose that mapping
    # via any local, no-sudo API. Rather than guess a marketing name from a
    # hardcoded identifier table (risk of showing a WRONG specific model),
    # append the machine identifier so the field is still exact + unique
    # per hardware revision, just not a "size-inch" style pretty name.
    # Keep model_name (used below for the "MacBook"/screen-size/USB-C
    # regex heuristics) unmodified — only build a separate display string
    # so an identifier like "Mac14,9" (contains "14") can't accidentally
    # match a "1[46]-inch" style regex meant for real screen sizes.
    model_display = model_name
    if model_id and model_id != model_name and model_id not in model_name:
        model_display = f"{model_name} ({model_id})".strip()
    cores = None
    cores_raw = hw.get("number_processors") or hw.get("total_number_of_cores") or hw.get("number_of_cores")
    m = re.search(r"(\d+)", str(cores_raw or ""))
    if m:
        cores = int(m.group(1))
    ram_gb = None
    m = re.search(r"(\d+)", str(hw.get("physical_memory") or ""))
    if m:
        ram_gb = int(m.group(1))

    # Battery
    batt = _ioreg_battery()
    has_battery = bool(batt.get("present"))
    battery_pct = None
    battery_health = None
    battery_wh = None
    on_ac = True
    if has_battery:
        design_cap = batt.get("DesignCapacity")
        max_cap = batt.get("MaxCapacity") or batt.get("AppleRawMaxCapacity")
        cur_cap = batt.get("CurrentCapacity") or batt.get("AppleRawCurrentCapacity")
        if design_cap and max_cap:
            battery_health = round(max_cap / design_cap * 100)
        if max_cap and cur_cap:
            battery_pct = round(cur_cap / max_cap * 100)
        voltage_mv = batt.get("Voltage")
        if max_cap and voltage_mv:
            battery_wh = round(max_cap * voltage_mv / 1_000_000, 1)  # mAh * mV -> Wh
        on_ac = bool(batt.get("external_connected"))

    # Storage — capacity + rough SSD/HDD classification. Use physical disks
    # (diskutil), not APFS volumes (system_profiler SPStorageDataType), so a
    # single internal drive isn't double-counted as "Macintosh HD" +
    # "Macintosh HD - Data" (see _mac_physical_disks docstring).
    disks = _mac_physical_disks()
    if not disks:
        # Fallback for the rare case diskutil/plistlib fails — best-effort
        # from system_profiler, same de-dup risk as before but better than
        # reporting no storage at all.
        for item in _sp("SPStorageDataType"):
            try:
                size_bytes = item.get("size_in_bytes")
                drive = item.get("physical_drive") or {}
                if not size_bytes:
                    size_bytes = drive.get("size_in_bytes")
                if not size_bytes:
                    continue
                gb = round(int(size_bytes) / (1024 ** 3))
                if gb <= 30:
                    continue
                medium = str(drive.get("medium_type") or "").lower()
                disk_type = "HDD" if "rotational" in medium else "SSD"
                rpm = 0 if disk_type == "SSD" else None
                disks.append({
                    "type": disk_type, "sizeGB": gb,
                    "make": drive.get("device_name") or item.get("_name") or "",
                    "rpm": rpm,
                })
            except Exception:
                continue

    # RAM — per-DIMM detail (Intel Macs only; Apple Silicon reports unified
    # memory with no discrete DIMMs, so this list is empty there and detect()
    # falls back to a single ram_gb-only entry with no type/speed/make).
    ram_sticks = []
    for item in _sp("SPMemoryDataType"):
        try:
            for dimm in (item.get("_items") or [item]):
                size_str = str(dimm.get("dimm_size") or "").strip()
                if not size_str or size_str.lower() in ("empty", "none"):
                    continue
                m = re.search(r"(\d+)\s*GB", size_str, re.I)
                if not m:
                    continue
                ram_sticks.append({
                    "capacityGB": int(m.group(1)),
                    "speed": re.sub(r"\s*MHz", "", str(dimm.get("dimm_speed") or ""), flags=re.I).strip(),
                    "make": dimm.get("dimm_manufacturer") or "",
                    "memType": dimm.get("dimm_type") or "",
                })
        except Exception:
            continue

    # Display / GPU
    disp_list = _sp("SPDisplaysDataType")
    gpu_name = None
    mons_count = 0
    for d in disp_list:
        if not gpu_name:
            gpu_name = d.get("sppci_model") or d.get("_name")
        ndrvs = d.get("spdisplays_ndrvs") or []
        mons_count += len(ndrvs) if ndrvs else 1
    screen_in = None
    m = re.search(r'(\d{2}(?:\.\d)?)[\s\-]*(?:inch|")', model_name, re.I)
    if m:
        try:
            screen_in = float(m.group(1))
        except ValueError:
            pass

    # Peripherals — presence only (macOS gives no per-device error/fault state
    # the way Windows Device Manager does, so 'ok' here means "detected", the
    # same caveat the Windows probe already carries for several fields).
    audio_list = _sp("SPAudioDataType")
    camera_list = _sp("SPCameraDataType")
    usb_list = _sp("SPUSBDataType")

    is_laptop = bool(has_battery) or "MacBook" in model_name or "MacBook" in model_id

    # Ethernet / Wi-Fi presence via networksetup hardware ports (built-in, no sudo)
    wifi_present = False
    ethernet_count = 0
    try:
        r = subprocess.run(["networksetup", "-listallhardwareports"],
                            capture_output=True, text=True, timeout=10)
        ports_out = r.stdout or ""
        blocks = re.split(r"\n\n+", ports_out.strip())
        for b in blocks:
            name_m = re.search(r"Hardware Port:\s*(.+)", b)
            if not name_m:
                continue
            pname = name_m.group(1)
            if re.search(r"Wi-?Fi|AirPort", pname, re.I):
                wifi_present = True
            elif re.search(r"Ethernet|Thunderbolt Ethernet|USB.*LAN", pname, re.I):
                ethernet_count += 1
    except Exception:
        pass
    if not wifi_present:
        # Virtually every Mac has built-in Wi-Fi; fall back to system_profiler.
        wifi_present = bool(_sp("SPAirPortDataType"))

    dvd_present = False  # no Mac model since ~2016 ships an internal optical drive

    storage_health = _mac_storage_health()

    info = {
        "manufacturer": "Apple",
        "model": model_display or model_name or model_id,
        "serial": serial,
        "cpu": chip,
        "clock": None,
        "cores": cores,
        "ram_gb": ram_gb,
        "chassis": [],
        "has_battery": has_battery,
        "battery_pct": battery_pct,
        "battery_health": battery_health,
        "on_ac": on_ac,
        "screen_in": screen_in,
        "gpu": gpu_name,
        "os": f"macOS {platform.mac_ver()[0]}".strip(),
        "disks": disks,
        "ram_sticks": ram_sticks,
        "kbd": "ok",                                  # built-in keyboard always present
        "touchpad": "ok" if is_laptop else "absent",   # built-in trackpad on laptops only
        "sound": "ok" if audio_list else "absent",
        "camera": "ok" if camera_list else "absent",
        "wifi": "ok" if wifi_present else "absent",
        "usbctrl": "ok" if usb_list else "absent",
        "dvd_present": dvd_present,
        "ethernet_count": ethernet_count,
        "usbc_hint": _mac_usb_c_estimate(model_name or model_id),
        "has_gpu": bool(gpu_name),
        "mons_count": mons_count,
        "battery_wh": battery_wh,
        "storage_health": storage_health,
        "fan_working": None,      # not reliably readable without elevated tools (powermetrics)
        "fan_rpm": None,
    }
    return info, None


def detect():
    system = platform.system()
    if system == "Windows":
        info, err = _probe_windows()
    elif system == "Darwin":
        info, err = _probe_mac()
    else:
        return None, f"OxyQC Agent supports Windows and macOS only (detected: {system})."
    if info is None:
        return None, err

    chassis = info.get("chassis") or []
    if isinstance(chassis, int):
        chassis = [chassis]
    laptop_codes = {8, 9, 10, 11, 12, 14, 18, 21, 30, 31, 32}
    is_laptop = bool(info.get("has_battery")) or any(
        str(c).isdigit() and int(c) in laptop_codes for c in chassis)
    sub = "Laptop" if is_laptop else "Desktop"

    disks = info.get("disks") or []
    if isinstance(disks, dict):
        disks = [disks]
    ssd = [d for d in disks if str(d.get("type", "")).upper().startswith("SSD")]
    hdd = [d for d in disks if str(d.get("type", "")).upper().startswith("HDD")]

    f = {}
    # ── Identity / specs ─────────────────────────────────────────────────────
    if info.get("manufacturer"):
        f["brand"] = str(info["manufacturer"]).split()[0].title()   # e.g. "Dell" / "Apple"
    if info.get("model"):
        model_raw = str(info["model"]).strip()
        # Dell BIOSes sometimes report the SKU (short code like "0A30") in
        # Win32_ComputerSystem.Model — fall back to SystemFamily ("Latitude
        # 5420") when the model looks like a SKU, not a marketing name.
        fam = str(info.get("sysfamily") or "").strip()
        if fam and "dell" in str(info.get("manufacturer") or "").lower() \
                and re.fullmatch(r"[0-9A-Fa-f]{3,6}", model_raw):
            model_raw = fam
        f["model"] = model_raw
    serial = str(info.get("serial") or "").strip()
    if serial and serial not in ("To Be Filled By O.E.M.", "Default string", "System Serial Number", "None"):
        f["serial_no"] = serial
    cpu_clean = _clean_cpu(info.get("cpu"), info.get("clock"))
    if cpu_clean:
        f["cpu"] = cpu_clean            # processor + speed only
    make = _cpu_make(info.get("cpu"), info.get("cpu_make"))
    if make:
        f["cpu_make"] = make
    gen = _generation(info.get("cpu"))
    if gen:
        f["generation"] = gen
    if info.get("ram_gb"):
        try:
            f["ram_gb"] = int(info["ram_gb"])
        except (TypeError, ValueError):
            pass
    ram_sticks = info.get("ram_sticks") or []
    ram_summary = format_ram_summary(ram_sticks)
    if not ram_summary and info.get("ram_gb"):
        # No per-DIMM breakdown available (e.g. Apple Silicon unified memory,
        # or a Windows station where Win32_PhysicalMemory returned nothing) —
        # fall back to just the total size rather than leaving the field blank.
        ram_summary = f"{int(info['ram_gb'])}GB"
    # Total RAM Count = # DIMMs (Apple Silicon unified → 1); plain summed size like "16GB" (or "1TB" if >= 1000GB)
    ram_dimms = [s for s in ram_sticks if s.get("capacityGB")]
    ram_plain = None
    if ram_sticks:
        # Count every populated slot — a sub-1GB module rounds to
        # capacityGB=0 in the probe and previously vanished from the count.
        f["total_ram_count"] = str(len(ram_sticks))
    if ram_dimms:
        _rg = sum(int(s["capacityGB"]) for s in ram_dimms)
        ram_plain = f"{round(_rg / 1000)}TB" if _rg >= 1000 else f"{_rg}GB"
    elif info.get("ram_gb"):
        if not ram_sticks:
            f["total_ram_count"] = "1"
        _rg = int(info["ram_gb"])
        ram_plain = f"{round(_rg / 1000)}TB" if _rg >= 1000 else f"{_rg}GB"
    # Swapped per spec: "Total RAM Size" holds the combined string,
    # "RAM" (ram_summary) holds the plain summed size.
    if ram_summary:
        f["total_ram_size"] = ram_summary
    if ram_plain:
        f["ram_summary"] = ram_plain
    f["sub_category"] = sub
    f["device_type"] = sub
    prim = (ssd or hdd or disks)
    if prim:
        psz = _snap_capacity(prim[0].get("sizeGB"))
        if psz:
            f["storage_gb"] = psz
        f["storage_type"] = "SSD" if ssd else ("HDD" if hdd else "SSD")
    if ssd and hdd:
        hsz = _snap_capacity(hdd[0].get("sizeGB"))
        if hsz:
            f["hdd_capacity_gb"] = hsz
    hdd_summary = format_hdd_summary(disks)
    # Total Hard Drive Count = # physical disks; plain summed size like "512GB"
    hdd_disks = [d for d in disks if d.get("sizeGB")]
    hdd_plain = None
    if hdd_disks:
        f["total_hdd_count"] = str(len(hdd_disks))
        _tot_gb = sum(int(d["sizeGB"]) for d in hdd_disks)
        hdd_plain = f"{round(_tot_gb / 1000)}TB" if _tot_gb >= 1000 else f"{_tot_gb}GB"
    # Swapped per spec: "Total Hard Drive Size" holds the combined string,
    # "Hard Drive" (hdd_summary) holds the plain summed size.
    if hdd_summary:
        f["total_hdd_size"] = hdd_summary
    if hdd_plain:
        f["hdd_summary"] = hdd_plain
    scr = _snap_screen(info.get("screen_in"))
    if scr:
        f["screen_size"] = scr
    bh = info.get("battery_health")
    if isinstance(bh, (int, float)) and bh > 0:
        # cap at 100 — a new/healthy pack can report full-charge > design (>100%)
        f["battery_health_pct"] = min(int(round(bh)), 100)
    batt_wh = info.get("battery_wh")
    if isinstance(batt_wh, (int, float)) and batt_wh > 0:
        f["battery_wh"] = round(float(batt_wh), 1)

    # ── Screen / display ──────────────────────────────────────────────────────
    # Screen Functional = a display is connected & active (genuinely detectable).
    mc = info.get("mons_count")
    if isinstance(mc, int):
        f["screen_functional"] = "Yes" if mc > 0 else "No"
    # Optical defects (dead pixel / line / patch / discoloration / colour spread /
    # flicker) cannot be read by software — no camera. Default to "No" (no defect)
    # as a baseline; the technician must still visually verify the panel.
    for _sf in ("screen_dot", "screen_line", "screen_patch", "screen_discoloration",
                "screen_colour_spread", "screen_flickering"):
        f[_sf] = "No"

    # Charging port — works if the system is currently running on AC through it.
    if info.get("on_ac"):
        f["charging_port"] = "Yes"

    # ── Functional status ─────────────────────────────────────────────────────
    f["battery_present"] = "Yes" if info.get("has_battery") else "No"
    f["power_on"] = "Yes"           # the agent is running, so it powered on
    f["status"] = "Power On"
    kb = info.get("kbd")
    if kb:
        f["keyboard_working"] = _yn3(kb)        # external kb on desktop also shows here
    if is_laptop:
        tp = info.get("touchpad")
        if tp:
            f["touchpad_working"] = _yn3(tp)
        # touchpad cosmetic fields (Yes / No)
        f["touchpad_click_working"] = "Yes" if tp == "ok" else "No"
        f["touchpad_missing"] = "No" if tp in ("ok", "error") else "Yes"
        # Logicboard exists if a pointing device was detected (ok or error)
        f["touchpad_logicboard"] = "Yes" if tp in ("ok", "error") else "No"
    else:
        f["touchpad_working"] = "No"            # desktops have no touchpad
        f["touchpad_click_working"] = "No"
        f["touchpad_missing"] = "Yes"
        f["touchpad_logicboard"] = "No"
    snd = info.get("sound")
    if snd == "ok":
        f["speaker_status"] = "Both speakers working"
    elif snd == "error":
        f["speaker_status"] = "Both speakers faulty"
    else:
        f["speaker_status"] = "Not Checked"     # no sound device → can't auto-check
    wf = info.get("wifi")
    if wf == "ok":
        f["wifi_status"] = "Working"
    elif wf == "error":
        f["wifi_status"] = "Faulty"
    cam = info.get("camera")
    if cam == "ok":
        f["webcam_status"] = "Ok"
    elif cam == "error":
        f["webcam_status"] = "Faulty"
    uc = info.get("usbctrl")
    if uc == "ok":
        f["port_usb_working"] = "Yes"
    elif uc == "error":
        f["port_usb_working"] = "No"
    f["dvd_drive"] = "Yes" if info.get("dvd_present") else "No"
    # HDD connector + casing. Rule: casing follows the connector.
    f["hdd_connector"] = "Yes" if disks else "No"
    f["hdd_casing"] = "Yes" if disks else "No"
    # Battery cable follows internal-battery presence.
    f["battery_cable"] = f["battery_present"]
    # HDMI: derive from a real display adapter being present (no WMI port probe exists).
    f["port_hdmi"] = "Yes" if (info.get("has_gpu") or info.get("gpu")) else "No"
    # Audio jack: follow the sound-device state (ok→Yes, faulty→Not Working, none→No).
    aj = _yn3(info.get("sound"))
    if aj:
        f["port_audio_jack"] = aj
    ec = info.get("ethernet_count")
    if isinstance(ec, int):
        f["ethernet_ports"] = ec
    # USB port counts:
    #   USB-C → best-effort from Windows UCSI/Type-C hints, or macOS model-based estimate
    #   USB-A → form-factor estimate; technician verifies (modern Macs have none)
    uch = info.get("usbc_hint")
    f["usb_c_ports"] = min(int(uch), 4) if isinstance(uch, int) and uch >= 0 else 0
    f["usbc_hint"] = int(uch) if isinstance(uch, int) else 0  # pass raw hint to JS
    f["usb_a_ports"] = 0 if IS_MAC else (2 if is_laptop else 4)
    # Storage health
    sh = info.get("storage_health")
    if isinstance(sh, (int, float)) and sh >= 0:
        f["storage_health_pct"] = int(sh)
    # Fan
    fw = info.get("fan_working")
    if fw:
        f["fan_working"] = fw
    fr = info.get("fan_rpm")
    if isinstance(fr, (int, float)) and fr > 0:
        f["fan_rpm"] = int(fr)

    diag = [f"Auto-diagnosed on {info.get('os', 'this station')}."]
    if info.get("cpu"):
        clock_txt = f" @ {info.get('clock')}GHz" if info.get("clock") else ""
        diag.append(f"CPU: {info['cpu']}{clock_txt} ({info.get('cores', '?')}C).")
    if info.get("ram_gb"):
        diag.append(f"RAM: {info['ram_gb']} GB.")
    if disks:
        diag.append("Storage: " + ", ".join(
            (f"{d.get('sizeGB', '?')}GB {d.get('type', '')}").strip() for d in disks) + ".")
    if info.get("gpu"):
        diag.append(f"GPU: {info['gpu']}.")
    if info.get("has_battery"):
        b = f"Battery: {info.get('battery_pct', '?')}% charge"
        if f.get("battery_health_pct") is not None:
            b += f", design health ~{f['battery_health_pct']}%"
        diag.append(b + ".")
    diag.append(f"Ethernet ports: {info.get('ethernet_count', 0)}.")
    diag.append(f"USB ports (estimate — verify): {f.get('usb_a_ports', '?')}xA, {f.get('usb_c_ports', '?')}xC.")
    f["_summary"] = " ".join(diag)
    f["notes"] = f["_summary"]
    return f, None


def run_stress_suite():
    """Standalone ON-DEVICE stress suite (PXE station mode).

    Unlike the ERP server's stress_runner (which exercises the SERVER's
    hardware), this runs on the laptop under test itself. Result shape matches
    stress_runner.TestResult.to_dict() — {status, summary, data, elapsed} per
    test key — so the ERP can persist and PDF-render it unchanged.
    """
    import tempfile
    import hashlib
    started = time.time()
    results = {}

    def rec(key, status, summary, elapsed=0.0, data=None):
        results[key] = {"status": status, "summary": summary,
                        "data": data or {}, "elapsed": round(elapsed, 1)}

    # One hardware probe up front — presence/health checks reuse it.
    t0 = time.time()
    system = platform.system()
    if system == "Windows":
        info, _perr = _probe_windows()
    elif system == "Darwin":
        info, _perr = _probe_mac()
    else:
        info, _perr = None, "unsupported platform"
    probe_elapsed = time.time() - t0
    info = info or {}

    # CPU — multi-thread integer burn, 5s
    t0 = time.time()
    try:
        stop_at = t0 + 5.0
        outs = []

        def _burn():
            n = 0
            while time.time() < stop_at:
                n += 1
                _ = (n * 2654435761) % 4294967296
            outs.append(n)

        threads = [threading.Thread(target=_burn)
                   for _ in range(max(2, (os.cpu_count() or 2)))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        total = sum(outs)
        rec("cpu", "PASS" if total > 0 else "FAIL",
            f"{len(threads)} threads, {total:,} ops in 5s", time.time() - t0)
    except Exception as e:
        rec("cpu", "FAIL", f"CPU test error: {e}", time.time() - t0)

    # RAM — allocate 256MB, pattern write/verify
    t0 = time.time()
    try:
        block = bytearray(256 * 1024 * 1024)
        step = 4096
        for i in range(0, len(block), step):
            block[i] = i % 251
        bad = sum(1 for i in range(0, len(block), step) if block[i] != i % 251)
        del block
        rec("ram", "PASS" if bad == 0 else "FAIL",
            "256MB write/verify OK" if bad == 0 else f"{bad} page verify errors",
            time.time() - t0)
    except MemoryError:
        rec("ram", "FAIL", "Could not allocate 256MB", time.time() - t0)
    except Exception as e:
        rec("ram", "WARN", f"RAM test error: {e}", time.time() - t0)

    # Storage — 64MB write/read/verify + SMART health from the probe
    t0 = time.time()
    try:
        payload = os.urandom(1024 * 1024)
        digest = hashlib.sha256(payload).hexdigest()
        mb = 64
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            path = fh.name
            for _ in range(mb):
                fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        w_secs = max(time.time() - t0, 0.01)
        t1 = time.time()
        ok = True
        with open(path, "rb") as fh:
            for _ in range(mb):
                if hashlib.sha256(fh.read(1024 * 1024)).hexdigest() != digest:
                    ok = False
                    break
        r_secs = max(time.time() - t1, 0.01)
        try:
            os.remove(path)
        except Exception:
            pass
        health = info.get("storage_health")
        hs = f", SMART {int(health)}%" if isinstance(health, (int, float)) else ""
        status = "PASS" if ok else "FAIL"
        if ok and isinstance(health, (int, float)) and health < 70:
            status = "WARN"
        rec("storage", status,
            f"{mb}MB write {mb / w_secs:.0f}MB/s, read {mb / r_secs:.0f}MB/s{hs}",
            time.time() - t0)
    except Exception as e:
        rec("storage", "FAIL", f"Disk I/O error: {e}", time.time() - t0)

    # Presence checks from the probe ('ok' | 'error' | 'absent')
    for key, state, okmsg in (
        ("usb",     info.get("usbctrl"), "USB controller OK"),
        ("camera",  info.get("camera"),  "Camera detected and OK"),
        ("speaker", info.get("sound"),   "Sound device OK"),
        ("wifi",    info.get("wifi"),    "WiFi adapter OK"),
    ):
        if state == "ok":
            rec(key, "PASS", okmsg)
        elif state == "error":
            rec(key, "FAIL", "Device reports an error state")
        else:
            rec(key, "WARN", "Not detected")

    # Battery
    bh = info.get("battery_health")
    if not info.get("has_battery"):
        rec("battery", "WARN", "No internal battery detected")
    elif isinstance(bh, (int, float)) and bh > 0:
        bhc = min(int(bh), 100)
        rec("battery", "PASS" if bhc >= 60 else "WARN", f"Battery health {bhc}%")
    else:
        rec("battery", "WARN", "Battery present, health unreadable")

    # Bluetooth
    t0 = time.time()
    try:
        if system == "Windows":
            ps = shutil.which("powershell") or "powershell"
            r = subprocess.run(
                [ps, "-NoProfile", "-Command",
                 "@(Get-CimInstance Win32_PnPEntity|Where-Object{$_.Name -match 'bluetooth'}).Count"],
                capture_output=True, text=True, timeout=20,
                creationflags=0x08000000)
            n = int((r.stdout or "0").strip() or 0)
            rec("bluetooth", "PASS" if n > 0 else "WARN",
                f"{n} Bluetooth device(s)" if n else "No Bluetooth adapter",
                time.time() - t0)
        else:
            rec("bluetooth", "WARN", "Not checked on this platform", time.time() - t0)
    except Exception as e:
        rec("bluetooth", "WARN", f"Bluetooth check error: {e}", time.time() - t0)

    # Display & GPU
    mc = info.get("mons_count")
    gpu = str(info.get("gpu") or "")
    if isinstance(mc, int) and mc > 0:
        rec("display", "PASS", f"{mc} display(s), GPU: {gpu[:40] or 'n/a'}")
    else:
        rec("display", "WARN", "No active display reported")

    # Thermal — fan state + the CPU burn completing without shutdown is the proxy
    fw = info.get("fan_working")
    if fw == "Yes":
        rec("thermal", "PASS", "Fan working; CPU burn completed without thermal shutdown")
    elif fw == "No":
        rec("thermal", "WARN", "Fan reports not working")
    else:
        rec("thermal", "WARN", "Fan state unknown; CPU burn completed without shutdown")

    finished = time.time()
    statuses = [r["status"] for r in results.values()]
    overall = ("FAIL" if "FAIL" in statuses
               else "PASS_WITH_WARNINGS" if "WARN" in statuses else "PASS")
    brand = str(info.get("manufacturer") or "").split()[0].title() if info.get("manufacturer") else ""
    return {
        "agent": "OxyQC", "version": AGENT_VERSION, "on_device": True,
        "brand": brand,
        "model": str(info.get("model") or ""),
        "serial": str(info.get("serial") or ""),
        "results": results,
        "overall_status": overall,
        "duration": round(finished - started, 1),
        "started_at": started, "finished_at": finished,
    }


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Accept, Content-Type")
        # Chrome Private Network Access (loopback) preflight
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/ping":   # lightweight liveness check (no hardware probe) for the page to poll
            body = json.dumps({"ok": True, "agent": "OxyQC", "platform": platform.system(),
                                "version": AGENT_VERSION}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/quit":   # used by a freshly-launched copy to evict a stale running instance
            body = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path == "/stress":
            # Standalone on-device stress suite — runs synchronously (~30-60s);
            # the Stress Test page fetches this then saves results to the ERP.
            try:
                payload = run_stress_suite()
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
            except Exception as e:
                body = json.dumps({"error": f"stress suite failed: {e}"}).encode("utf-8")
                self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return
        if path not in ("/diagnose", "/"):
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        fields, err = detect()
        summary = ""
        if fields:
            summary = fields.pop("_summary", "")
        payload = {"ok": err is None, "error": err, "data": (fields or {}), "summary": summary}
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # quiet


def main():
    # First run from Downloads etc. → install to the per-user app dir + autostart,
    # then the relaunched canonical copy serves. (No UAC on Windows, no sudo on Mac.)
    if _self_install():
        return
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        return  # port already in use → an instance is already running, exit quietly
    print(f"Diagnose_Device_Agent running on http://127.0.0.1:{PORT}/diagnose  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
