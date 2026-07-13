"""Diagnostic field registry (spec section 13). Deliberately duplicated from
services/care_service.DIAGNOSTIC_ALLOWED_FIELDS rather than imported — the
Windows agent ships as a standalone package with its own Python runtime and
must not depend on the FastAPI app's import path. Keep the two lists in sync
by hand whenever either changes; a mismatch just means the server rejects a
field the agent sent (fails safe, not open).
"""

# field_name -> (source, privilege, timeout_seconds, customer_visible)
DIAGNOSTIC_FIELD_REGISTRY = {
    "bios_serial":              ("wmi_cim", "standard", 2, False),   # masked before display
    "manufacturer":             ("wmi_cim", "standard", 2, True),
    "model":                     ("wmi_cim", "standard", 2, True),
    "cpu":                       ("wmi_cim", "standard", 3, True),
    "ram_gb":                    ("wmi_cim", "standard", 3, True),
    "os_version":                ("windows_api", "standard", 2, True),
    "storage_summary":           ("storage_api", "standard", 5, True),
    "smart_status":              ("storage_api", "elevated", 8, True),
    "battery_health_pct":        ("derived", "standard", 1, True),
    "battery_cycle_count":       ("wmi_cim", "standard", 5, True),
    "hardware_warning_summary":  ("device_manager", "elevated", 8, False),  # summary only
    "system_error_summary":      ("event_log_allowlist", "elevated", 10, False),  # summary only
}

DIAGNOSTIC_ALLOWED_FIELDS = frozenset(DIAGNOSTIC_FIELD_REGISTRY.keys())
MAX_DIAGNOSTIC_STRING_LEN = 2000

# Windows Event Log collection is restricted per spec 13.3 — System log only,
# Error/Critical severity, capped window and count, no other logs at all.
EVENT_LOG_NAME = "System"
EVENT_LOG_SEVERITIES = ("Error", "Critical")
EVENT_LOG_MAX_AGE_HOURS = 72
EVENT_LOG_MAX_EVENTS = 25
EVENT_LOG_PROVIDER_ALLOWLIST = frozenset({
    "Disk", "Ntfs", "volmgr", "storahci", "Kernel-Power", "EventLog",
})

# Explicitly prohibited — never collected, never sent, regardless of profile.
PROHIBITED_CATEGORIES = frozenset({
    "file_names", "file_contents", "browser_history", "cookies", "credentials",
    "clipboard", "screenshots", "webcam", "microphone", "keystrokes",
    "email_content", "messaging_content", "app_usage_history",
    "raw_registry_export", "raw_event_log_export", "process_command_lines",
})
