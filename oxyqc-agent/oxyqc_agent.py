#!/usr/bin/env python
"""
OxyQC Local Diagnose Agent
==========================
Runs on an INSPECTION STATION (the PC the technician uses). Exposes:

    GET  http://127.0.0.1:8765/diagnose   -> that station's hardware as JSON

The OxyPC web IQC page calls this from the browser. Because 127.0.0.1 in a
browser always means the machine the browser runs on, this reads the LOCAL
station's hardware — never the server's.

Stdlib only (no third-party deps). Windows only (uses WMI/CIM via PowerShell).
Run:    python oxyqc_agent.py        (or pythonw for no console)
Build:  pyinstaller --onefile --noconsole --name OxyQC_Agent oxyqc_agent.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import platform
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8765

# Per-user install target (no admin needed)
_APPDIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Diagnose_Device_Agent")
_TARGET = os.path.join(_APPDIR, "Diagnose_Device_Agent.exe")
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_NAME = "Diagnose_Device_Agent"


def _set_autostart(path):
    """Register HKCU autostart (per-user, no UAC). Best-effort."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, _AUTOSTART_NAME, 0, winreg.REG_SZ, f'"{path}"')
    except Exception:
        pass


def _self_install():
    """When run as a frozen exe from somewhere other than %LOCALAPPDATA%\\OxyQC,
    copy self there, register per-user autostart, launch that copy, and signal the
    caller to exit. All per-user => never triggers UAC. Returns True if a relaunch
    was started (caller should exit)."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return False  # running as a .py script: don't self-install
    cur = os.path.abspath(sys.executable)
    try:
        os.makedirs(_APPDIR, exist_ok=True)
    except Exception:
        pass
    if os.path.normcase(cur) == os.path.normcase(_TARGET):
        _set_autostart(_TARGET)   # already the canonical copy
        return False
    try:
        shutil.copy2(cur, _TARGET)   # note: drops Mark-of-the-Web -> no SmartScreen on the copy
    except Exception:
        _set_autostart(cur)          # target busy/locked: just register where we are
        return False
    _set_autostart(_TARGET)
    try:
        subprocess.Popen([_TARGET], creationflags=0x08000000)  # CREATE_NO_WINDOW
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
$pd=@(Get-PhysicalDisk|Where-Object {$_.Size -gt 30GB}|ForEach-Object{[ordered]@{type="$($_.MediaType)";sizeGB=[math]::Round($_.Size/1GB)}})
$bh=$null
$full=(Get-CimInstance -Namespace root\wmi -ClassName BatteryFullChargedCapacity -EA SilentlyContinue|Select-Object -First 1).FullChargedCapacity
$des=(Get-CimInstance -Namespace root\wmi -ClassName BatteryStaticData -EA SilentlyContinue|Select-Object -First 1).DesignedCapacity
if($des -and $des -gt 0 -and $full -and $full -gt 0){$bh=[math]::Round(($full/$des)*100)}
if(-not $bh -and $batt){$fc=$batt.FullChargeCapacity;$dc=$batt.DesignCapacity;if($fc -gt 0 -and $dc -gt 0){$bh=[math]::Round($fc/$dc*100)}}
if(-not $bh -and $batt){try{$rf=[System.IO.Path]::Combine($env:TEMP,'bh_'+[guid]::NewGuid().ToString('N').Substring(0,8)+'.html');$null=powercfg /batteryreport /output $rf 2>&1;if(Test-Path $rf){$h=Get-Content $rf -Raw;Remove-Item $rf -Force -EA SilentlyContinue;$m1=$null;$m2=$null;if($h -match '(?si)DESIGN CAPACITY.{0,200}?([\d,]+)\s*mWh'){$m1=[int64]($matches[1]-replace',','')};if($h -match '(?si)FULL CHARGE CAPACITY.{0,200}?([\d,]+)\s*mWh'){$m2=[int64]($matches[1]-replace',','')};if($m1 -gt 0 -and $m2 -gt 0){$bh=[math]::Round($m2/$m1*100)}}}catch{}}
$batt_wh=$null
if($full -gt 0){$batt_wh=[math]::Round($full/1000.0, 1)}
$storage_health=$null
try{$disksHealth=@(Get-PhysicalDisk|Where-Object{$_.Size -gt 30GB}|Select-Object HealthStatus,MediaType,OperationalStatus);if($disksHealth.Count -gt 0){$h2=$disksHealth|Where-Object{$_.HealthStatus -eq 'Healthy'};$storage_health=[math]::Round(($h2.Count/$disksHealth.Count)*100)}}catch{}
$fan_working=$null;$fan_rpm=$null
try{$fans=@(Get-CimInstance -Namespace root\wmi -ClassName Win32_Fan -EA SilentlyContinue|Where-Object{$_.DesiredSpeed -gt 0 -or $_.ActiveCooling -eq $true});if($fans.Count -gt 0){$fan_working='Yes';$fan_rpm=$fans[0].DesiredSpeed}}catch{}
if(-not $fan_working){$fan_working='No'}
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
$eth=@($nics|Where-Object {($_.Name -match 'Ethernet|Gigabit|GbE|Realtek PCIe|Killer E|I2[12]9') -and $_.Name -notmatch 'Wi-?Fi|Wireless|Bluetooth|Virtual|VPN|TAP|Loopback|VMware|Hyper-V'})
$dvd=@(Get-CimInstance Win32_CDROMDrive|Where-Object {$_.Name -notmatch 'Virtual'})
$usb=@(Get-CimInstance Win32_USBController)
$ucm=@(Get-CimInstance Win32_PnPEntity -EA SilentlyContinue|Where-Object {$_.Name -match 'UCSI|USB Connector Manager|USB Type-C|USB-C|USB4|Thunderbolt'})
$clk=[math]::Round($cpu.MaxClockSpeed/1000.0,2)
$onAC=$true; if($batt -and $batt.BatteryStatus -eq 1){$onAC=$false}
[ordered]@{
 manufacturer="$($cs.Manufacturer)";model="$($cs.Model)";serial="$($bios.SerialNumber)";
 cpu="$(($cpu.Name).Trim())";clock=$clk;cores=$cpu.NumberOfCores;ram_gb=[math]::Round($cs.TotalPhysicalMemory/1GB);
 chassis=@($encl.ChassisTypes);has_battery=[bool]$batt;battery_pct=$batt.EstimatedChargeRemaining;battery_health=$bh;on_ac=$onAC;
 screen_in=$scr;gpu="$($gpu.Name)";os="$($os.Caption)";disks=$pd;
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


def detect():
    if platform.system() != "Windows":
        return None, "OxyQC Agent runs on Windows only."
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
        info = json.loads(raw)
    except Exception:
        return None, "could not parse hardware probe output"

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
        f["brand"] = str(info["manufacturer"]).split()[0].title()   # e.g. "Dell"
    if info.get("model"):
        f["model"] = info["model"]
    serial = str(info.get("serial") or "").strip()
    if serial and serial not in ("To Be Filled By O.E.M.", "Default string", "System Serial Number", "None"):
        f["serial_no"] = serial
    cpu_clean = _clean_cpu(info.get("cpu"), info.get("clock"))
    if cpu_clean:
        f["cpu"] = cpu_clean            # processor + speed only
    gen = _generation(info.get("cpu"))
    if gen:
        f["generation"] = gen
    if info.get("ram_gb"):
        try:
            f["ram_gb"] = int(info["ram_gb"])
        except (TypeError, ValueError):
            pass
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
    else:
        f["touchpad_working"] = "No"            # desktops have no touchpad
        f["touchpad_click_working"] = "No"
        f["touchpad_missing"] = "Yes"
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
    # USB port counts (Windows exposes no exact physical A/C count):
    #   USB-C → best-effort from UCSI/Type-C/Thunderbolt connector devices
    #   USB-A → form-factor estimate (laptop 2 / desktop 4); technician verifies
    uch = info.get("usbc_hint")
    f["usb_c_ports"] = min(int(uch), 4) if isinstance(uch, int) and uch >= 0 else 0
    f["usbc_hint"] = int(uch) if isinstance(uch, int) else 0  # pass raw hint to JS
    f["usb_a_ports"] = 2 if is_laptop else 4
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
        diag.append(f"CPU: {info['cpu']} @ {info.get('clock', '?')}GHz ({info.get('cores', '?')}C).")
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
        if path == "/ping":   # lightweight liveness check (no WMI) for the page to poll
            body = json.dumps({"ok": True, "agent": "OxyQC"}).encode("utf-8")
            self.send_response(200)
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
    # First run from Downloads etc. → install to %LOCALAPPDATA% + autostart, then
    # the relaunched canonical copy serves. (No UAC — all per-user.)
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
