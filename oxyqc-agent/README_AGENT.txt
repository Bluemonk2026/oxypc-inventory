OxyQC Diagnose Agent — per-station hardware auto-fill
=====================================================

WHAT IT IS
----------
A tiny localhost service that lets the "Diagnose this Device" button on the
OxyPC web IQC Entry page read the hardware of the STATION the technician is
using — not the server. It listens only on 127.0.0.1:8765 (loopback), so it is
never exposed on the LAN and needs no inbound firewall rule.

WHY IT'S NEEDED
---------------
A browser cannot read the hardware of the PC it runs on. So each inspection
station runs this agent; the web page calls http://127.0.0.1:8765/diagnose,
which (in the browser) always points to that same station.

INSTALL & RUN — one step, NO admin / NO UAC
-------------------------------------------
OxyQC_Agent.exe is a SINGLE self-installing exe. On each station, just run it
once (or download it from the IQC page's "Diagnose" message):

    Double-click OxyQC_Agent.exe

On first run it (all per-user, no UAC):
  - copies itself to %LOCALAPPDATA%\OxyQC\OxyQC_Agent.exe
  - registers per-user autostart (HKCU Run "OxyQCAgent") -> starts at every logon
  - starts serving on http://127.0.0.1:8765
From then on it runs automatically; the technician never has to start it again.

Notes:
  - The exe is unsigned, so the FIRST launch of the DOWNLOADED file may show a
    one-time SmartScreen prompt ("More info" -> "Run anyway"). This is NOT UAC.
    The self-installed copy in %LOCALAPPDATA% has no Mark-of-the-Web, so the
    daily autostart launches with no prompt at all.
  - Windows only (uses WMI/CIM via PowerShell).

USING IT
--------
1. Run OxyQC_Agent.exe once on the station (autostart handles every logon after).
2. Open the OxyPC web app -> IQC Entry on that same station.
3. Click "Diagnose this Device" -> the form auto-fills from THIS station:
   Brand, Model, Serial, CPU, Generation, RAM, Storage (SSD/HDD) + capacity,
   Laptop/Desktop, screen size (single-display only), battery design health,
   and a diagnosis summary in Notes.

REMOVE
------
Run uninstall_agent.bat (removes autostart + stops it; no admin needed), or:
  - delete the HKCU Run value "OxyQCAgent", end OxyQC_Agent.exe in Task Manager,
    and delete the folder %LOCALAPPDATA%\OxyQC.

REBUILD THE EXE (developers)
----------------------------
  pip install pyinstaller
  pyinstaller --onefile --noconsole --name OxyQC_Agent oxyqc_agent.py
  -> dist\OxyQC_Agent.exe

LIMITS
------
- Screen size is read only when exactly one display is connected (captures the
  laptop's own panel, not an external monitor).
- If the OxyPC web app is ever served over HTTPS, browsers block an HTTPS page
  from calling http://127.0.0.1 (mixed content). Keep the app on http on the LAN.
