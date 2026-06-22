"""
Fixed spare-parts list for the device 'Parts Consumption' section, with the
'Required (Yes/No)' flag derived from the device's IQC inspection fields.

Each entry: (label, category, name_keyword, required_fn)
 - category / name_keyword are used to match SparePart rows for stock status.
 - required_fn(iqc, device) -> bool, where iqc is an IQCInspection (or None).
"""


def _is(val, target):
    return bool(val) and str(val).strip().lower() == str(target).strip().lower()


def _faulty(val):
    return bool(val) and "faulty" in str(val).lower()


PARTS_MATRIX = [
    # RAM required when RAM = "Not Available" (blank → stored as None)
    ("RAM",               "RAM",        "ram",      lambda i, d: d is not None and d.ram_gb is None),
    # SSD / Storage required when SSD Capacity OR Storage Type = "Not Available"
    ("SSD / Storage",     "SSD",        "ssd",      lambda i, d: d is not None and (d.storage_gb is None or not d.storage_type)),
    # HDD Connector/Caddy required when HDD connector faulty OR HDD Capacity = "Not Available"
    ("HDD Connector/Caddy", "HDD",      "hdd",      lambda i, d: _is(i.hdd_connector, "No") or (d is not None and d.hdd_capacity_gb is None)),
    ("Battery",           "Battery",    "battery",  lambda i, d: _is(i.battery_present, "No")
                          or (d is not None and d.battery_health_pct is not None and d.battery_health_pct < 40)),
    ("Keyboard",          "Keyboard",   "keyboard", lambda i, d: _is(i.keyboard_working, "No")
                          or _is(i.keyboard_key_missing, "Yes")),
    ("Screen / Display",  "Screen",     "screen",   lambda i, d: _is(i.status, "No Display")
                          or _is(i.screen_broken, "Yes") or _is(i.screen_line, "Yes")
                          or _is(i.screen_dot, "Yes") or _is(i.screen_flickering, "Yes")
                          or _is(i.screen_missing, "Yes") or _is(i.screen_functional, "No")),
    ("Hinge",             "Other",      "hinge",    lambda i, d: _is(i.screen_hinge_broken, "Yes")),
    ("Adapter / Charger", "Charger",    "charger",  lambda i, d: False),
    ("Speaker",           "Other",      "speaker",  lambda i, d: _faulty(i.speaker_status)),
    ("Touchpad",          "Other",      "touchpad", lambda i, d: _is(i.touchpad_working, "No")
                          or _is(i.touchpad_missing, "Yes")),
    ("WiFi Card",         "Other",      "wifi",     lambda i, d: _faulty(i.wifi_status)),
    ("Webcam",            "Other",      "webcam",   lambda i, d: _faulty(i.webcam_status)),
]


class _NullIQC:
    """Stand-in when a device has no IQC inspection yet — any attribute reads as None,
    so device-driven rules (RAM / Storage / HDD = 'Not Available') still evaluate."""
    def __getattr__(self, _name):
        return None


def compute_required(iqc, device):
    """Return list of {label, category, keyword, required} for the fixed parts list."""
    i = iqc if iqc is not None else _NullIQC()
    rows = []
    for label, category, keyword, fn in PARTS_MATRIX:
        try:
            required = bool(fn(i, device))
        except Exception:
            required = False
        rows.append({"label": label, "category": category, "keyword": keyword, "required": required})
    return rows
