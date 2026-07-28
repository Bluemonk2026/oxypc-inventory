OxyPC PXE Station Deployment — README
=====================================

Goal: laptops booted from a PXE-deployed Windows image automatically get the
OxyQC agent installed and the correct ERP page opened, with zero technician
setup. Two separate PXE images are used:

  PXE image #1  (IQC line)              -> STATION_MODE=iqc
  PXE image #2  (Stress Test / Final QC) -> STATION_MODE=stress

What happens on each boot
-------------------------
1. setup_station.bat downloads the latest agent from
      <SERVER_URL>/iqc/agent-exe        (no login needed — public LAN route)
   so agent updates ship automatically with every ERP deploy; no image rebuild.
2. The agent starts on 127.0.0.1:8765 (serves /diagnose and /stress).
3. The default browser opens at the station page:
      iqc     -> <SERVER_URL>/iqc/new           (IQC entry; agent auto-fills)
      stress  -> <SERVER_URL>/qc?autorun=1      (Stress Test; selecting a
                 device auto-runs the ON-DEVICE suite via the local agent and
                 saves results + PDF to the ERP automatically)
      finalqc -> <SERVER_URL>/cosmetic/final-qc
4. A launcher is written to the all-users Startup folder so steps 2-3 repeat
   on every subsequent boot.

The technician's only actions: log in to the ERP in the opened browser (first
boot only — the session cookie persists), and scan the device's tag number.

Configuring the two PXE images
------------------------------
Copy this whole pxe\ folder into each Windows image (e.g. C:\OxyQC-Setup\),
then edit the CONFIG block at the top of setup_station.bat in each image:

  Image #1:  set "SERVER_URL=http://10.199.206.109"
             set "STATION_MODE=iqc"

  Image #2:  set "SERVER_URL=http://10.199.206.109"
             set "STATION_MODE=stress"

(Or use iqc_station_setup.bat / stress_station_setup.bat, which force the
mode without editing the shared script.)

Wire it into the image — pick ONE of these three methods:

METHOD A — SetupComplete.cmd (recommended for sysprepped images)
  Create  C:\Windows\Setup\Scripts\SetupComplete.cmd  containing:
      call C:\OxyQC-Setup\setup_station.bat
  Windows runs this once automatically at the end of OOBE/first boot.
  The script then self-persists via the Startup folder for later boots.

METHOD B — unattend.xml FirstLogonCommands
  In your PXE/MDT/WDS answer file, add under <FirstLogonCommands>:
      <SynchronousCommand wcm:action="add">
        <Order>1</Order>
        <CommandLine>cmd /c C:\OxyQC-Setup\setup_station.bat</CommandLine>
        <Description>OxyQC station bootstrap</Description>
      </SynchronousCommand>

METHOD C — Startup folder (simplest; no sysprep needed)
  Place a shortcut to setup_station.bat in:
      C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp\
  It then runs at every logon (the script is idempotent — safe to re-run).

Auto-login note
---------------
For a true zero-touch kiosk boot, configure Windows auto-logon in the image
(netplwiz, or Autologon from Sysinternals) with a low-privilege local user.
The ERP login inside the browser is separate and persists via cookie
(session lifetime is controlled by OXYPC_TOKEN_EXPIRE_MINUTES on the server).

On-device Stress Test / Final QC flow (image #2)
------------------------------------------------
The Stress Test page detects the local agent and shows an "On Device" button;
with ?autorun=1 (which the launcher uses) the technician just clicks Start on
the scanned device's row — the suite (CPU burn, RAM verify, disk I/O+SMART,
battery health, WiFi, Bluetooth, camera, speakers, USB, display, thermal)
runs on the laptop itself, results save to the ERP under the scanned tag, and
the PDF report opens automatically. Final QC pass/fail is then recorded on
the Final QC page as usual.

Troubleshooting
---------------
- Agent not detected on the page: check http://127.0.0.1:8765/ping in the
  browser on the station; Windows Firewall prompts must be allowed (loopback
  is normally exempt).
- Download fails at boot: the script keeps the last good agent copy and the
  station still works offline; fix connectivity to <SERVER_URL> and reboot.
- Wrong page opens: re-check STATION_MODE in setup_station.bat inside that
  PXE image.
