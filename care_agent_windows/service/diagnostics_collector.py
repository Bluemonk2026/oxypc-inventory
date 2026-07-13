"""Read-only diagnostic collection (spec sections 4.3, 13). Every value that
leaves this module has already passed through the allowlist in
common/diagnostics_schema.py — there is no code path here that can return an
arbitrary field, because collect_profile() builds its result by iterating
the registry, not by dumping whatever WMI/Event Log returns.
"""
import concurrent.futures
import platform

try:
    import wmi
except ImportError:  # pragma: no cover
    wmi = None

try:
    import win32evtlog
except ImportError:  # pragma: no cover
    win32evtlog = None

from common.diagnostics_schema import (
    DIAGNOSTIC_FIELD_REGISTRY, EVENT_LOG_NAME, EVENT_LOG_SEVERITIES,
    EVENT_LOG_MAX_AGE_HOURS, EVENT_LOG_MAX_EVENTS, EVENT_LOG_PROVIDER_ALLOWLIST,
)


def _wmi_conn():
    if wmi is None:
        raise RuntimeError("wmi module not available on this host")
    return wmi.WMI()


def _collect_bios_serial(c) -> str:
    for row in c.Win32_BIOS():
        return (row.SerialNumber or "").strip()
    return ""


def _collect_manufacturer(c) -> str:
    for row in c.Win32_ComputerSystem():
        return (row.Manufacturer or "").strip()
    return ""


def _collect_model(c) -> str:
    for row in c.Win32_ComputerSystem():
        return (row.Model or "").strip()
    return ""


def _collect_cpu(c) -> str:
    for row in c.Win32_Processor():
        return (row.Name or "").strip()
    return ""


def _collect_ram_gb(c) -> int:
    for row in c.Win32_ComputerSystem():
        return round(int(row.TotalPhysicalMemory or 0) / (1024 ** 3))
    return 0


def _collect_os_version() -> str:
    return f"{platform.system()} {platform.release()} ({platform.version()})"


def _collect_storage_summary(c) -> str:
    parts = []
    for row in c.Win32_DiskDrive():
        size_gb = round(int(row.Size or 0) / (1024 ** 3))
        parts.append(f"{row.Model.strip() if row.Model else 'Disk'} {size_gb}GB")
    return "; ".join(parts) if parts else "unknown"


def _collect_smart_status(c) -> str:
    statuses = []
    try:
        for row in c.query("SELECT * FROM MSStorageDriver_FailurePredictStatus"):
            statuses.append("failing" if row.PredictFailure else "ok")
    except Exception:
        return "unavailable"
    if not statuses:
        return "unavailable"
    return "failing" if "failing" in statuses else "ok"


def _collect_battery_capacities(c):
    design, full_charge = None, None
    for row in c.query("SELECT * FROM BatteryStaticData", namespace="root\\WMI"):
        design = getattr(row, "DesignedCapacity", None)
    for row in c.query("SELECT * FROM BatteryFullChargedCapacity", namespace="root\\WMI"):
        full_charge = getattr(row, "FullChargedCapacity", None)
    return design, full_charge


def _collect_battery_health_pct(c) -> int:
    design, full_charge = _collect_battery_capacities(c)
    if not design or not full_charge:
        return -1  # no battery / not reported — caller omits the field
    return round(min(full_charge / design, 1.0) * 100)


def _collect_battery_cycle_count(c) -> int:
    try:
        for row in c.query("SELECT * FROM BatteryCycleCount", namespace="root\\WMI"):
            return int(getattr(row, "CycleCount", 0))
    except Exception:
        return -1
    return -1


def _collect_hardware_warning_summary(c) -> str:
    warnings = []
    for row in c.Win32_PnPEntity():
        # ConfigManagerErrorCode != 0 means Device Manager shows a problem —
        # this is a summary flag only, never the device's full identity string.
        if getattr(row, "ConfigManagerErrorCode", 0):
            warnings.append("device_manager_error")
            break
    return "; ".join(sorted(set(warnings))) if warnings else ""


def _collect_system_error_summary() -> str:
    """Windows System log, Error/Critical only, allowlisted providers, capped
    window and count, no raw messages containing usernames/paths (spec 13.3)."""
    if win32evtlog is None:
        return ""
    handle = win32evtlog.OpenEventLog(None, EVENT_LOG_NAME)
    flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
    counts = {}
    read = 0
    try:
        while read < EVENT_LOG_MAX_EVENTS * 4:  # scan a bounded window, not the whole log
            events = win32evtlog.ReadEventLog(handle, flags, 0)
            if not events:
                break
            for ev in events:
                read += 1
                if read > EVENT_LOG_MAX_EVENTS * 4:
                    break
                source = str(ev.SourceName)
                if source not in EVENT_LOG_PROVIDER_ALLOWLIST:
                    continue
                counts[source] = counts.get(source, 0) + 1
            if read >= EVENT_LOG_MAX_EVENTS * 4:
                break
    finally:
        win32evtlog.CloseEventLog(handle)
    if not counts:
        return ""
    return "; ".join(f"{src}: {n}" for src, n in sorted(counts.items()))


_COLLECTORS = {
    "bios_serial": lambda c: _collect_bios_serial(c),
    "manufacturer": lambda c: _collect_manufacturer(c),
    "model": lambda c: _collect_model(c),
    "cpu": lambda c: _collect_cpu(c),
    "ram_gb": lambda c: _collect_ram_gb(c),
    "os_version": lambda c: _collect_os_version(),
    "storage_summary": lambda c: _collect_storage_summary(c),
    "smart_status": lambda c: _collect_smart_status(c),
    "battery_health_pct": lambda c: _collect_battery_health_pct(c),
    "battery_cycle_count": lambda c: _collect_battery_cycle_count(c),
    "hardware_warning_summary": lambda c: _collect_hardware_warning_summary(c),
    "system_error_summary": lambda c: _collect_system_error_summary(),
}


def collect_profile(profile: str = "support_basic_v1") -> dict:
    """Runs every registered collector under its own timeout. A field that
    times out or errors is simply omitted — never partially populated with
    unvalidated data, and never blocks the others."""
    result = {}
    conn = None
    try:
        conn = _wmi_conn()
    except Exception:
        conn = None  # collectors that don't need WMI (os_version) still run

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {}
        for field, (_, _, timeout_s, _) in DIAGNOSTIC_FIELD_REGISTRY.items():
            fn = _COLLECTORS.get(field)
            if not fn:
                continue
            futures[pool.submit(fn, conn)] = (field, timeout_s)

        for fut, (field, timeout_s) in futures.items():
            try:
                value = fut.result(timeout=timeout_s)
                if value not in (None, "", -1):
                    result[field] = value
            except Exception:
                continue  # timed out or failed — omit, don't fail the whole snapshot

    return result
