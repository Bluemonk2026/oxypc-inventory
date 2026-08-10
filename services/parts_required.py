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


# Same idea as _is_sentinel, but "No" counts as a real answer rather than a
# non-answer. Used by the body / display group at the foot of the table: on
# those fields "No" is the technician saying there is no defect, so treating it
# as unknown made the part Required on essentially every tag — Hinge came back
# needed on all 2,185 tags of a lot purely because screen_hinge_broken said
# "No". Genuinely missing data still flags.
def _is_unknown(val):
    if val is None:
        return True
    return str(val).strip().lower() in (_SENTINELS - {"no"})


def _damaged(*vals):
    """True if any cosmetic panel field reports actual damage.

    Panel fields read "No" / "Yes" / "Major Broken" / "Major Dent", so anything
    that is not "No" (and not blank) is damage. Deliberately NOT using
    _is_sentinel here: a blank cosmetic field means the inspector did not
    record that panel, which is not evidence the part needs replacing. The
    hardware rows above treat blanks as Required=Yes because an unverified
    component is a risk; a body panel nobody looked at is not.
    """
    for v in vals:
        if v is None:
            continue
        s = str(v).strip().lower()
        if not s or s in ("no", "-", "n/a", "none"):
            continue
        # The broken/dent columns sometimes carry a scratch or colour-fade
        # value (panel_c_broken holds "Minor Scratch" on 104 production rows).
        # Those go to Paint for refinishing, not to Stores for a new panel, so
        # they must not flag the part Required wherever they were entered.
        if "scratch" in s or "fade" in s:
            continue
        return True
    return False


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
    ("Adapter",           "Charger",    "charger",  lambda i, d: False),
    ("Speaker",           "Other",      "speaker",  lambda i, d: _faulty(i.speaker_status) or _is_sentinel(i.speaker_status)),
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
    # ── Body / display assembly, kept together at the foot of the table ──────
    # These eight are the parts an engineer strips the chassis to reach, so
    # they sit last and in the order the machine comes apart: lid, bezel,
    # screen, hinges, then the base half. The sequence is fixed by the
    # business, not derived — do not re-sort this block.
    #
    # The four cosmetic panels are Required when that panel is recorded
    # broken, missing or dented. A scratch or a faded colour is refinished at
    # the Paint stage, not replaced, so those fields are not consulted.
    ("Display Panel",     "Body",   "display panel", lambda i, d: _damaged(
        i.panel_a_broken, i.panel_a_missing, i.panel_a_dent)),
    # Label is "Bezel"; the category and keyword stay "Bazel" because that is
    # how the spare-part rows are spelled in master data and they are the
    # stock-matching keys. Rename those in Master Data if you want them to
    # agree — the display label does not depend on it.
    ("Bezel",             "Bazel",  "bazel",         lambda i, d: _damaged(
        i.panel_c_broken, i.panel_c_missing, i.panel_c_dent)),
    ("Display",           "Screen",     "screen",   lambda i, d: _is(i.status, "No Display")
                          or _is(i.screen_broken, "Yes") or _is(i.screen_line, "Yes")
                          or _is(i.screen_dot, "Yes") or _is(i.screen_flickering, "Yes")
                          or _is(i.screen_missing, "Yes") or _is(i.screen_functional, "No")
                          or _is_unknown(i.screen_functional)),
    ("Hinge",             "Other",      "hinge",    lambda i, d: _is(i.screen_hinge_broken, "Yes") or _is_unknown(i.screen_hinge_broken)),
    ("Touchpad",          "Other",      "touchpad", lambda i, d: _is(i.touchpad_working, "No") or _is_unknown(i.touchpad_working)
                          or _is(i.touchpad_missing, "Yes")),
    ("Bottom Base",       "Body",   "bottom base",   lambda i, d: _damaged(
        i.panel_b_broken, i.panel_b_missing, i.panel_b_rubber_cut)),
    ("Keyboard",          "Keyboard",   "keyboard", lambda i, d: _is(i.keyboard_working, "No") or _is_unknown(i.keyboard_working)
                          or _is(i.keyboard_key_missing, "Yes")),
    ("Palm rest",         "Body",   "palm rest",     lambda i, d: _damaged(
        i.panel_d_broken, i.panel_d_missing, i.panel_d_dent)),
]

# The eight rows above must stay last and in this order. compute_required
# preserves PARTS_MATRIX order, so a stray edit that moves one of them would
# silently reorder the Device Detail table; the assertion below turns that
# into an import-time failure instead.
_BODY_TAIL = ["Display Panel", "Bezel", "Display", "Hinge",
              "Touchpad", "Bottom Base", "Keyboard", "Palm rest"]
assert [row[0] for row in PARTS_MATRIX[-len(_BODY_TAIL):]] == _BODY_TAIL, (
    "PARTS_MATRIX tail order changed — Parts Consumption expects "
    f"{_BODY_TAIL}, found {[row[0] for row in PARTS_MATRIX[-len(_BODY_TAIL):]]}"
)


# Older labels that PartRequest.part_name rows may still carry in the database.
# The label is the join key for "does this part already have a request?", so a
# rename without this map would orphan every historical / in-flight request.
# New label -> tuple of previously used labels.
LEGACY_LABELS = {
    "Display": ("Screen / Display",),
    "Adapter": ("Adapter / Charger",),
    # Shipped as "Bazel Frame" for one day before being renamed.
    "Bezel": ("Bazel Frame",),
}


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
