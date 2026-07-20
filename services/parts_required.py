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


# Values entered on the IQC Entry form that mean "we don't actually know /
# this wasn't usably captured" — any of these on a relevant field means the
# part's status is effectively unresolved, so Parts Consumption must show
# Required = Yes rather than silently defaulting to No.
_SENTINELS = {"-", "n/a", "n / a", "no", "not available", "not checked", "unknown", ""}


def _is_sentinel(val):
    if val is None:
        return True
    return str(val).strip().lower() in _SENTINELS


# Labels are the IQC Entry form's hardware field names (templates/iqc/form.html)
# so a Parts Consumption row reads with the same name the technician saw at IQC.
PARTS_MATRIX = [
    # RAM required when RAM = "Not Available" (blank → stored as None)
    ("RAM",               "RAM",        "ram",      lambda i, d: d is not None and d.ram_gb is None),
    # Hard Drive required when SSD Capacity OR Storage Type = "Not Available"
    ("Hard Drive",        "SSD",        "ssd",      lambda i, d: d is not None and (d.storage_gb is None or not d.storage_type)),
    # HDD Connector required when HDD connector faulty/unclear OR HDD Capacity = "Not Available"
    ("HDD Connector",     "HDD",        "hdd",      lambda i, d: _is(i.hdd_connector, "No") or _is_sentinel(i.hdd_connector)
                          or (d is not None and d.hdd_capacity_gb is None)),
    ("Internal Battery",  "Battery",    "battery",  lambda i, d: _is(i.battery_present, "No") or _is_sentinel(i.battery_present)
                          or (d is not None and d.battery_health_pct is not None and d.battery_health_pct < 40)),
    ("Keyboard",          "Keyboard",   "keyboard", lambda i, d: _is(i.keyboard_working, "No") or _is_sentinel(i.keyboard_working)
                          or _is(i.keyboard_key_missing, "Yes")),
    ("Screen / Display",  "Screen",     "screen",   lambda i, d: _is(i.status, "No Display")
                          or _is(i.screen_broken, "Yes") or _is(i.screen_line, "Yes")
                          or _is(i.screen_dot, "Yes") or _is(i.screen_flickering, "Yes")
                          or _is(i.screen_missing, "Yes") or _is(i.screen_functional, "No")
                          or _is_sentinel(i.screen_functional)),
    ("Hinge",             "Other",      "hinge",    lambda i, d: _is(i.screen_hinge_broken, "Yes") or _is_sentinel(i.screen_hinge_broken)),
    ("Adapter / Charger", "Charger",    "charger",  lambda i, d: False),
    ("Speaker",           "Other",      "speaker",  lambda i, d: _faulty(i.speaker_status) or _is_sentinel(i.speaker_status)),
    ("Touchpad",          "Other",      "touchpad", lambda i, d: _is(i.touchpad_working, "No") or _is_sentinel(i.touchpad_working)
                          or _is(i.touchpad_missing, "Yes")),
    ("Wi-Fi",             "Other",      "wifi",     lambda i, d: _faulty(i.wifi_status) or _is_sentinel(i.wifi_status)),
    ("Web Cam",           "Other",      "webcam",   lambda i, d: _faulty(i.webcam_status) or _is_sentinel(i.webcam_status)),
    # ── Remaining IQC hardware fields (item 3d) — one Parts Consumption row per
    #    component captured on the IQC Entry form. Required when the field
    #    reports a fault / "No"; count-only fields (Ethernet ports) never
    #    auto-flag (mirrors the Adapter/Charger row). ────────────────────────
    ("HDMI Port",         "HDMI Port",  "hdmi",     lambda i, d: _is(i.port_hdmi, "No") or _faulty(i.port_hdmi)),
    ("USB Ports",         "USB Port",   "usb",      lambda i, d: _is(i.port_usb_working, "No") or _faulty(i.port_usb_working)),
    ("Audio Jack",        "Audio Jack", "audio",    lambda i, d: _is(i.port_audio_jack, "No") or _faulty(i.port_audio_jack)),
    ("Ethernet Ports",    "Ethernet Port", "ethernet", lambda i, d: False),
    ("Charging Port",     "Charging Port", "charging", lambda i, d: _is(i.charging_port, "No") or _faulty(i.charging_port)),
    ("DVD Drive",         "DVD Drive",  "dvd",      lambda i, d: _is(i.dvd_drive, "No") or _faulty(i.dvd_drive)),
    ("Fan Working",       "Fan",        "fan",      lambda i, d: _is(i.fan_working, "No") or _faulty(i.fan_working)),
    ("Motherboard",       "Motherboard", "motherboard", lambda i, d: _is(i.status, "No Display") or _is(i.power_on, "No")),
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
