"""
OxyPC Server-Side Stress Runner
================================
Runs hardware stress tests on the station machine (the FastAPI host).
All tests are thread-safe; results stored in a StressSession object.

Tests: cpu, ram, storage, usb, battery, wifi, thermal,
       camera (SKIP if no cv2), speaker (SKIP), display (WMI or SKIP)
"""
from __future__ import annotations

import json
import math
import os
import platform
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Optional

# ── Optional heavy imports (SKIP test if unavailable) ────────────────────────
try:
    import wmi as _wmi
    _WMI = _wmi.WMI()
except Exception:
    _WMI = None

try:
    import cv2 as _cv2
except Exception:
    _cv2 = None

# ── Durations (seconds per test) ─────────────────────────────────────────────
DURATIONS: dict[str, dict[str, int]] = {
    "quick":     {"cpu": 20,  "ram": 15,  "storage": 15, "usb": 5,  "camera": 5,  "speaker": 3,  "battery": 5,  "wifi": 10, "display": 5,  "thermal": 10},
    "standard":  {"cpu": 60,  "ram": 45,  "storage": 30, "usb": 5,  "camera": 8,  "speaker": 5,  "battery": 8,  "wifi": 20, "display": 8,  "thermal": 20},
    "intensive": {"cpu": 180, "ram": 120, "storage": 90, "usb": 5,  "camera": 10, "speaker": 5,  "battery": 10, "wifi": 30, "display": 10, "thermal": 60},
}

TEST_NAMES = {
    "cpu":     "CPU Stress",
    "ram":     "RAM Stress",
    "storage": "Storage I/O",
    "usb":     "USB Ports",
    "camera":  "Camera",
    "speaker": "Speaker",
    "battery": "Battery",
    "wifi":    "WiFi / Network",
    "display": "Display & GPU",
    "thermal": "Thermal",
}

ALL_KEYS = list(TEST_NAMES.keys())


# ── Result dataclass ──────────────────────────────────────────────────────────
@dataclass
class TestResult:
    status:  str = "PENDING"   # PENDING / RUNNING / PASS / FAIL / WARN / SKIP
    summary: str = ""
    data:    dict = field(default_factory=dict)
    elapsed: float = 0.0

    def to_dict(self) -> dict:
        return {"status": self.status, "summary": self.summary,
                "data": self.data, "elapsed": round(self.elapsed, 1)}


# ── Individual test runners ───────────────────────────────────────────────────

def _run_cpu(duration: int, progress: Callable) -> TestResult:
    """Prime-sieve based CPU burn for `duration` seconds."""
    start = time.monotonic()
    primes_found = 0

    def _sieve(n: int) -> int:
        sieve = bytearray([1]) * (n + 1)
        sieve[0] = sieve[1] = 0
        for i in range(2, int(n**0.5) + 1):
            if sieve[i]:
                sieve[i*i::i] = bytearray(len(sieve[i*i::i]))
        return sum(sieve)

    try:
        while time.monotonic() - start < duration:
            primes_found = _sieve(500_000)
            elapsed = time.monotonic() - start
            progress(min(99, int(elapsed / duration * 100)), f"Computing… {elapsed:.0f}s")

        elapsed = time.monotonic() - start
        return TestResult("PASS", f"Completed {elapsed:.0f}s — primes<500k: {primes_found:,}", elapsed=elapsed)
    except Exception as e:
        return TestResult("FAIL", f"Exception: {e}", elapsed=time.monotonic()-start)


def _run_ram(duration: int, progress: Callable) -> TestResult:
    start = time.monotonic()
    try:
        chunk_mb = 64
        chunk = bytearray(chunk_mb * 1024 * 1024)
        for i in range(len(chunk)):
            chunk[i] = i & 0xFF  # write pattern
        elapsed = time.monotonic() - start
        progress(50, f"Writing {chunk_mb} MB…")
        for i in range(len(chunk)):
            if chunk[i] != (i & 0xFF):
                return TestResult("FAIL", "RAM data integrity error", elapsed=time.monotonic()-start)
        del chunk
        elapsed = time.monotonic() - start
        progress(100, f"Verified {chunk_mb} MB OK")
        return TestResult("PASS", f"64 MB alloc+verify OK ({elapsed:.1f}s)", elapsed=elapsed)
    except MemoryError:
        return TestResult("FAIL", "MemoryError — insufficient RAM", elapsed=time.monotonic()-start)
    except Exception as e:
        return TestResult("FAIL", str(e), elapsed=time.monotonic()-start)


def _run_storage(duration: int, progress: Callable) -> TestResult:
    start = time.monotonic()
    tmp = Path(tempfile.gettempdir()) / "oxypc_stress_io.tmp"
    mb = 128
    block = bytes(1024 * 1024)  # 1 MB
    try:
        progress(10, f"Writing {mb} MB…")
        t0 = time.monotonic()
        with open(tmp, "wb") as f:
            for _ in range(mb):
                f.write(block)
            f.flush()
        write_s = time.monotonic() - t0

        progress(60, "Reading back…")
        t0 = time.monotonic()
        with open(tmp, "rb") as f:
            while f.read(1024 * 1024):
                pass
        read_s = time.monotonic() - t0

        wr = mb / write_s
        rd = mb / read_s
        elapsed = time.monotonic() - start
        status = "PASS" if wr >= 10 and rd >= 10 else "WARN"
        return TestResult(status, f"W {wr:.0f} MB/s  R {rd:.0f} MB/s",
                          data={"write_mbps": round(wr, 1), "read_mbps": round(rd, 1)},
                          elapsed=elapsed)
    except Exception as e:
        return TestResult("FAIL", str(e), elapsed=time.monotonic()-start)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _run_usb(duration: int, progress: Callable) -> TestResult:
    start = time.monotonic()
    try:
        if _WMI:
            disks = _WMI.Win32_DiskDrive()
            usb_disks = [d for d in disks if "USB" in (d.InterfaceType or "")]
            hubs = _WMI.Win32_USBHub()
            count = len(hubs)
            progress(100, f"{count} hub(s), {len(usb_disks)} USB storage")
            status = "PASS" if count >= 1 else "WARN"
            return TestResult(status, f"{count} USB hub(s) detected, {len(usb_disks)} storage device(s)",
                              data={"hubs": count, "storage": len(usb_disks)},
                              elapsed=time.monotonic()-start)
        else:
            # Linux fallback
            out = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
            lines = [l for l in out.stdout.splitlines() if l.strip()]
            count = len(lines)
            return TestResult("PASS" if count else "WARN", f"{count} USB device(s)",
                              data={"devices": count}, elapsed=time.monotonic()-start)
    except Exception as e:
        return TestResult("WARN", f"USB detection error: {e}", elapsed=time.monotonic()-start)


def _run_camera(duration: int, progress: Callable) -> TestResult:
    start = time.monotonic()
    if _cv2 is None:
        return TestResult("SKIP", "cv2 not installed", elapsed=time.monotonic()-start)
    try:
        cap = _cv2.VideoCapture(0)
        if not cap.isOpened():
            return TestResult("WARN", "No camera detected (index 0)", elapsed=time.monotonic()-start)
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None:
            h, w = frame.shape[:2]
            return TestResult("PASS", f"Camera OK {w}×{h}",
                              data={"width": w, "height": h}, elapsed=time.monotonic()-start)
        return TestResult("FAIL", "Camera opened but no frame", elapsed=time.monotonic()-start)
    except Exception as e:
        return TestResult("FAIL", str(e), elapsed=time.monotonic()-start)


def _run_speaker(_duration: int, progress: Callable) -> TestResult:
    return TestResult("SKIP", "Speaker test requires audio hardware on device",
                      elapsed=0.0)


def _run_battery(_duration: int, progress: Callable) -> TestResult:
    start = time.monotonic()
    try:
        if _WMI:
            bat = _WMI.Win32_Battery()
            if not bat:
                # Check BatteryFullChargedCapacity in root\WMI
                import wmi as _wmi2
                wmi2 = _wmi2.WMI(namespace="root\\wmi")
                try:
                    batt = wmi2.BatteryFullChargedCapacity()
                    if batt:
                        fc = batt[0].FullChargedCapacity
                        return TestResult("PASS", f"Battery detected — full charge: {fc} mWh",
                                         data={"full_charged_mwh": fc}, elapsed=time.monotonic()-start)
                except Exception:
                    pass
                return TestResult("WARN", "No battery detected (desktop or AC-only)",
                                  elapsed=time.monotonic()-start)
            b = bat[0]
            status_code = b.BatteryStatus
            charge = b.EstimatedChargeRemaining
            desc_map = {1:"Discharging",2:"AC",3:"Fully Charged",4:"Low",5:"Critical",
                        6:"Charging",7:"Charging+High",8:"Charging+Low",9:"Charging+Critical",10:"Undefined",11:"Partially Charged"}
            desc = desc_map.get(status_code, f"Code {status_code}")
            return TestResult("PASS", f"Battery {charge}% — {desc}",
                              data={"charge_pct": charge, "status": desc},
                              elapsed=time.monotonic()-start)
        else:
            # Linux
            for bat_path in Path("/sys/class/power_supply").glob("BAT*"):
                cap = (bat_path / "capacity").read_text().strip()
                return TestResult("PASS", f"Battery {cap}%",
                                  data={"charge_pct": int(cap)}, elapsed=time.monotonic()-start)
            return TestResult("WARN", "No battery found", elapsed=time.monotonic()-start)
    except Exception as e:
        return TestResult("WARN", f"Battery check error: {e}", elapsed=time.monotonic()-start)


def _run_wifi(duration: int, progress: Callable) -> TestResult:
    start = time.monotonic()
    try:
        host = "8.8.8.8"
        count = 4 if platform.system() == "Windows" else 4
        flag = "-n" if platform.system() == "Windows" else "-c"
        progress(30, f"Pinging {host}…")
        res = subprocess.run(
            ["ping", flag, str(count), host],
            capture_output=True, text=True, timeout=20
        )
        output = res.stdout + res.stderr
        # Parse packet loss
        lost = 0
        for line in output.splitlines():
            if "Lost" in line or "loss" in line:
                for token in line.split():
                    try:
                        pct = float(token.strip("%,"))
                        lost = int(pct)
                        break
                    except ValueError:
                        pass
        elapsed = time.monotonic() - start
        status = "PASS" if lost == 0 else ("WARN" if lost <= 25 else "FAIL")
        return TestResult(status, f"Ping {host} — {100-lost}% success ({count} packets)",
                          data={"host": host, "loss_pct": lost}, elapsed=elapsed)
    except subprocess.TimeoutExpired:
        return TestResult("FAIL", "Network unreachable (timeout)", elapsed=time.monotonic()-start)
    except Exception as e:
        return TestResult("FAIL", str(e), elapsed=time.monotonic()-start)


def _run_display(_duration: int, progress: Callable) -> TestResult:
    start = time.monotonic()
    try:
        if _WMI:
            gpus = _WMI.Win32_VideoController()
            if not gpus:
                return TestResult("WARN", "No GPU detected via WMI", elapsed=time.monotonic()-start)
            g = gpus[0]
            name = g.Name or "Unknown GPU"
            ram_mb = int((g.AdapterRAM or 0) / 1024 / 1024)
            res_w = g.CurrentHorizontalResolution or 0
            res_h = g.CurrentVerticalResolution or 0
            desc = f"{name} — {ram_mb}MB — {res_w}×{res_h}"
            return TestResult("PASS", desc,
                              data={"gpu": name, "vram_mb": ram_mb, "res": f"{res_w}x{res_h}"},
                              elapsed=time.monotonic()-start)
        return TestResult("SKIP", "WMI not available for GPU detection", elapsed=time.monotonic()-start)
    except Exception as e:
        return TestResult("WARN", str(e), elapsed=time.monotonic()-start)


def _run_thermal(_duration: int, progress: Callable) -> TestResult:
    start = time.monotonic()
    try:
        if _WMI:
            import wmi as _wmi2
            wmi2 = _wmi2.WMI(namespace="root\\wmi")
            temps = wmi2.MSAcpi_ThermalZoneTemperature()
            if temps:
                readings = []
                for t in temps:
                    kelvin = t.CurrentTemperature / 10
                    celsius = kelvin - 273.15
                    readings.append(round(celsius, 1))
                max_t = max(readings)
                status = "PASS" if max_t < 80 else ("WARN" if max_t < 95 else "FAIL")
                return TestResult(status, f"Thermal zones: {readings}°C (max {max_t}°C)",
                                  data={"temps_c": readings, "max_c": max_t},
                                  elapsed=time.monotonic()-start)
            return TestResult("WARN", "No thermal zones reported", elapsed=time.monotonic()-start)
        else:
            # Linux
            path = Path("/sys/class/thermal/thermal_zone0/temp")
            if path.exists():
                temp_c = int(path.read_text()) / 1000
                status = "PASS" if temp_c < 80 else "WARN"
                return TestResult(status, f"{temp_c:.1f}°C",
                                  data={"max_c": temp_c}, elapsed=time.monotonic()-start)
            return TestResult("SKIP", "No thermal sensor", elapsed=time.monotonic()-start)
    except Exception as e:
        return TestResult("WARN", f"Thermal read error: {e}", elapsed=time.monotonic()-start)


_RUNNERS = {
    "cpu":     _run_cpu,
    "ram":     _run_ram,
    "storage": _run_storage,
    "usb":     _run_usb,
    "camera":  _run_camera,
    "speaker": _run_speaker,
    "battery": _run_battery,
    "wifi":    _run_wifi,
    "display": _run_display,
    "thermal": _run_thermal,
}


# ── Session object ────────────────────────────────────────────────────────────

class StressSession:
    """Holds state for one device's stress test run."""

    def __init__(self, barcode: str, duration: str, run_by: str,
                 brand: str = "", model: str = ""):
        self.barcode   = barcode
        self.duration  = duration if duration in DURATIONS else "standard"
        self.run_by    = run_by
        self.brand     = brand
        self.model     = model
        self.running   = False
        self._stop_evt = threading.Event()
        self._lock     = threading.Lock()
        self.results: dict[str, TestResult] = {k: TestResult() for k in ALL_KEYS}
        self.started_at: float = 0.0
        self.finished_at: float = 0.0

    def start(self):
        self.running   = True
        self._stop_evt.clear()
        self.started_at = time.time()
        self.results   = {k: TestResult() for k in ALL_KEYS}
        t = threading.Thread(target=self._run_all, daemon=True, name=f"stress-{self.barcode}")
        t.start()

    def stop(self):
        self._stop_evt.set()

    def _run_all(self):
        durations = DURATIONS[self.duration]
        for key in ALL_KEYS:
            if self._stop_evt.is_set():
                with self._lock:
                    self.results[key] = TestResult("SKIP", "Stopped by user")
                continue

            with self._lock:
                self.results[key] = TestResult("RUNNING", "Running…")

            def _prog(pct: int, msg: str, _key=key):
                with self._lock:
                    self.results[_key].summary = msg

            dur = durations.get(key, 10)
            runner = _RUNNERS.get(key)
            t0 = time.monotonic()
            if runner:
                try:
                    result = runner(dur, _prog)
                except Exception as e:
                    result = TestResult("FAIL", f"Uncaught: {e}", elapsed=time.monotonic()-t0)
            else:
                result = TestResult("SKIP", "No runner defined")

            with self._lock:
                self.results[key] = result

        self.running = False
        self.finished_at = time.time()

    def overall_status(self) -> str:
        statuses = [r.status for r in self.results.values()]
        if "RUNNING" in statuses or "PENDING" in statuses:
            return "IN_PROGRESS"
        if "FAIL" in statuses:
            return "FAIL"
        if "WARN" in statuses:
            return "PASS_WITH_WARNINGS"
        if all(s in ("PASS", "SKIP") for s in statuses):
            return "PASS"
        return "UNKNOWN"

    def to_status_dict(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "overall_status": self.overall_status(),
                "results": {k: r.to_dict() for k, r in self.results.items()},
            }

    def to_full_dict(self) -> dict:
        with self._lock:
            return {
                "barcode":   self.barcode,
                "brand":     self.brand,
                "model":     self.model,
                "run_by":    self.run_by,
                "duration":  self.duration,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "overall_status": self.overall_status(),
                "results": {k: r.to_dict() for k, r in self.results.items()},
            }


# ── Global session registry ───────────────────────────────────────────────────
_sessions: dict[str, StressSession] = {}
_sessions_lock = threading.Lock()


def get_session(barcode: str) -> Optional[StressSession]:
    with _sessions_lock:
        return _sessions.get(barcode)


def start_session(barcode: str, duration: str, run_by: str,
                  brand: str = "", model: str = "") -> StressSession:
    session = StressSession(barcode, duration, run_by, brand, model)
    with _sessions_lock:
        _sessions[barcode] = session
    session.start()
    return session


def stop_session(barcode: str):
    session = get_session(barcode)
    if session:
        session.stop()
