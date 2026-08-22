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

    Panel fields read "No" / "Yes" / "Minor" / "Major" on the current IQC form,
    and "Major Broken" / "Major Dent" / "Minor Scratch" on rows captured before
    the scales were unified — so anything that is not "No" (and not blank) is
    damage, whichever wording it was entered under. Deliberately NOT using
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


# The fixed part list, in the order the shop floor reads it: MAIN PARTS then
# ADDITIONAL PARTS, matching the "Spare Part Names" master dropdown.
#
# Each entry: (label, category, name_keyword, required_fn, section)
#  - category / name_keyword match SparePart rows for stock status. They are
#    deliberately NOT renamed alongside the label: "Bezel" still matches stock
#    spelled "Bazel", because those are the keys the Part Master rows carry.
#  - required_fn(iqc, device) -> bool. A part with no IQC field behind it gets
#    `lambda i, d: False` - Required stays No and it is requested by hand.
MAIN, ADDITIONAL = "MAIN PARTS", "ADDITIONAL PARTS"


def _battery_required(i, d):
    """Shared by Internal and External Battery.

    IQC records one battery per device - there is no separate external-battery
    field - so both rows read the same signal. They stay two rows because they
    are two different parts to pick and price from Stores.
    """
    return (_is(i.battery_present, "No") or _is_sentinel(i.battery_present)
            or (d is not None and d.battery_health_pct is not None
                and d.battery_health_pct < 40))


PARTS_MATRIX = [
    # -- MAIN PARTS ----------------------------------------------------------
    ("RAM",               "RAM",        "ram",      lambda i, d: d is not None and d.ram_gb is None, MAIN),
    ("Hard Drive",        "SSD",        "ssd",      lambda i, d: d is not None and (d.storage_gb is None or not d.storage_type), MAIN),
    ("Bezel",             "Bazel",      "bazel",    lambda i, d: _damaged(
        i.panel_c_broken, i.panel_c_missing, i.panel_c_dent), MAIN),
    ("Panel",             "Body",       "display panel", lambda i, d: _damaged(
        i.panel_a_broken, i.panel_a_missing, i.panel_a_dent), MAIN),
    ("Screen",            "Screen",     "screen",   lambda i, d: _is(i.status, "No Display")
                          or _damaged(i.screen_broken) or _is(i.screen_line, "Yes")
                          or _is(i.screen_dot, "Yes") or _is(i.screen_flickering, "Yes")
                          or _is(i.screen_missing, "Yes") or _is(i.screen_functional, "No")
                          or _is_unknown(i.screen_functional), MAIN),
    ("Hinge",             "Other",      "hinge",    lambda i, d: _is(i.screen_hinge_broken, "Yes") or _is_unknown(i.screen_hinge_broken), MAIN),
    ("Bottom Base",       "Body",       "bottom base", lambda i, d: _damaged(
        i.panel_b_broken, i.panel_b_missing, i.panel_b_rubber_cut), MAIN),
    ("Keyboard",          "Keyboard",   "keyboard", lambda i, d: _is(i.keyboard_working, "No") or _is_unknown(i.keyboard_working)
                          or _is(i.keyboard_key_missing, "Yes"), MAIN),
    ("Internal Battery",  "Battery",    "battery",  _battery_required, MAIN),
    ("External Battery",  "Battery",    "external battery", _battery_required, MAIN),
    ("Camera",            "Other",      "webcam",   lambda i, d: _faulty(i.webcam_status) or _is_sentinel(i.webcam_status), MAIN),
    ("DC Jack",           "Charging Port", "charging", lambda i, d: _is(i.charging_port, "No") or _faulty(i.charging_port), MAIN),
    # Ethernet is captured as a port count, not a pass/fail, so it never
    # auto-flags - a count of zero is a spec, not a fault.
    ("LAN Port",          "Ethernet Port", "ethernet", lambda i, d: False, MAIN),
    ("USB Port",          "USB Port",   "usb",      lambda i, d: _is(i.port_usb_working, "No") or _faulty(i.port_usb_working), MAIN),
    ("HDMI Port",         "HDMI Port",  "hdmi",     lambda i, d: _is(i.port_hdmi, "No") or _faulty(i.port_hdmi), MAIN),
    ("Audio Jack",        "Audio Jack", "audio",    lambda i, d: _is(i.port_audio_jack, "No") or _faulty(i.port_audio_jack), MAIN),
    ("Speaker",           "Other",      "speaker",  lambda i, d: _faulty(i.speaker_status) or _is_sentinel(i.speaker_status), MAIN),
    ("Fan Working",       "Fan",        "fan",      lambda i, d: _is(i.fan_working, "No") or _faulty(i.fan_working), MAIN),
    ("Motherboard",       "Motherboard", "motherboard", lambda i, d: _is(i.status, "No Display") or _is(i.power_on, "No"), MAIN),
    ("Logic Card",        "Other",      "touchpad", lambda i, d: _is(i.touchpad_working, "No") or _is_unknown(i.touchpad_working)
                          or _is(i.touchpad_missing, "Yes"), MAIN),
    ("Wi-Fi Card",        "Other",      "wifi",     lambda i, d: _faulty(i.wifi_status) or _is_sentinel(i.wifi_status), MAIN),
    ("DVD Drive",         "DVD Drive",  "dvd",      lambda i, d: _is(i.dvd_drive, "No") or _faulty(i.dvd_drive), MAIN),
    # -- ADDITIONAL PARTS ----------------------------------------------------
    # Covers and cables are not inspected at IQC, so none of them can derive a
    # Required flag. They exist here so an engineer can request one against the
    # tag instead of typing free text, which is what produced the unmatchable
    # "HDD Connector/Caddy" and "M.2 SSD" rows in request history.
    ("RAM Cover",         "Body",       "ram cover",        lambda i, d: False, ADDITIONAL),
    ("DVD Drive Cover",   "Body",       "dvd drive cover",  lambda i, d: False, ADDITIONAL),
    ("Hinge Cover",       "Body",       "hinge cover",      lambda i, d: False, ADDITIONAL),
    ("Hard Drive Cover",  "Body",       "hard drive cover", lambda i, d: False, ADDITIONAL),
    ("HDD Connector",     "HDD",        "hdd",      lambda i, d: _is(i.hdd_connector, "No") or _is_sentinel(i.hdd_connector)
                          or (d is not None and d.hdd_capacity_gb is None), ADDITIONAL),
    ("Touchpad Cover",    "Body",       "palm rest", lambda i, d: _damaged(
        i.panel_d_broken, i.panel_d_missing, i.panel_d_dent), ADDITIONAL),
    ("Touchpad Cable",    "Other",      "touchpad cable",   lambda i, d: False, ADDITIONAL),
    ("Camera Cable",      "Other",      "camera cable",     lambda i, d: False, ADDITIONAL),
    ("Battery Cable",     "Other",      "battery cable",    lambda i, d: False, ADDITIONAL),
]

# The list must stay in the order above - it is the order the floor strips a
# machine, fixed by the business rather than derived - and every MAIN row must
# precede every ADDITIONAL one or the Device Detail headings interleave. A
# stray edit that breaks either becomes an import-time failure rather than a
# silently reordered table.
_MATRIX_LABELS = [r[0] for r in PARTS_MATRIX]
assert len(_MATRIX_LABELS) == len(set(_MATRIX_LABELS)), (
    "PARTS_MATRIX has a duplicate label")
_sections = [r[4] for r in PARTS_MATRIX]
assert _sections == sorted(_sections, key=lambda x: 0 if x == MAIN else 1), (
    "PARTS_MATRIX sections interleave - every MAIN row must precede ADDITIONAL")
assert _MATRIX_LABELS[:8] == ["RAM", "Hard Drive", "Bezel", "Panel", "Screen",
                              "Hinge", "Bottom Base", "Keyboard"], (
    "PARTS_MATRIX head order changed: %s" % _MATRIX_LABELS[:8])


# Older labels that PartRequest.part_name rows may still carry in the database.
# The label is the join key for "does this part already have a request?", so a
# rename without this map would orphan every historical / in-flight request.
# New label -> tuple of previously used labels.
LEGACY_LABELS = {
    # The 2026-08 consolidation onto the shop-floor part names. Every rename
    # needs an entry here: without one the Requested / Verify pill silently
    # disappears from every in-flight request raised under the old name.
    "Panel":          ("Display Panel",),
    "Screen":         ("Display", "Screen / Display"),
    "Camera":         ("Web Cam", "Webcam"),
    "DC Jack":        ("Charging Port",),
    "LAN Port":       ("Ethernet Ports", "Ethernet Port"),
    "USB Port":       ("USB Ports", "USB ports"),
    "Logic Card":     ("Touchpad",),
    "Wi-Fi Card":     ("Wi-Fi",),
    "Touchpad Cover": ("Palm rest",),
    # Shipped as "Bazel Frame" for one day before being renamed.
    "Bezel":          ("Bazel Frame",),
}


# Optical-drive parts only make sense on a desktop chassis; on the laptop
# queue they are two rows that can never be needed.
DESKTOP_ONLY = {"DVD Drive", "DVD Drive Cover"}


def _is_desktop(device):
    """True / False / None for "is this a desktop", where None means unknown.

    Matched on a substring, case-insensitively, because production carries both
    "Desktop" (1,132 tags) and "DESKTOP" (28) - an equality check would leak the
    DVD rows back onto the shouted ones.

    An unrecorded type counts as "not a desktop" by decision: the floor would
    rather the 8,684 typeless tags read as laptops than carry two optical rows
    that are wrong on nearly all of them. A DVD drive on such a tag is still
    requestable through the New Request modal, which is not restricted here.
    """
    if device is None:
        return None          # no device at all -> not a tag view; show everything
    value = (getattr(device, "device_type", None) or "").strip().lower()
    if not value:
        return False         # recorded as nothing -> treated as not a desktop
    return "desktop" in value


def rules_by_label():
    """{label -> required_fn}, keyed by BOTH the current label and every name
    it used to carry.

    Part Estimation asks for its rules by name ("Wi-Fi", "Web Cam", "Touchpad")
    and those names are its own column headers, stored against historical
    estimates — so they cannot simply be renamed alongside the parts list. The
    aliases keep those lookups resolving to the same classifier instead of
    raising KeyError at import.
    """
    rules = {label: fn for label, _c, _k, fn, _s in PARTS_MATRIX}
    for current, olds in LEGACY_LABELS.items():
        fn = rules.get(current)
        if fn is None:
            continue
        for old in olds:
            rules.setdefault(old, fn)
    return rules


class _NullIQC:
    """Stand-in when a device has no IQC inspection yet — any attribute reads as None,
    so device-driven rules (RAM / Storage / HDD = 'Not Available') still evaluate."""
    def __getattr__(self, _name):
        return None


def extra_master_labels():
    """Spare Part Names configured in Master Data that PARTS_MATRIX does not know.

    Reads the warm in-memory master cache, so this stays synchronous and costs
    no query — and it refreshes the moment an admin adds a value, because
    /admin/master calls refresh_master_cache() on every edit.

    A name added to the dropdown has no IQC field behind it by definition, so
    it can only ever appear under ADDITIONAL PARTS with Required = No. Matching
    is case-insensitive: "ram cover" typed into the dropdown must not produce a
    second row alongside the matrix's "RAM Cover".
    """
    from utils.master_data import master_options

    known = {lbl.strip().lower() for lbl in _MATRIX_LABELS}
    seen, extras = set(known), []
    for value in master_options("part_category"):
        key = (value or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        extras.append(value.strip())
    return extras


def compute_required(iqc, device, include_master_extras=False):
    """Return [{label, category, keyword, required, section}] for the parts list.

    The DVD Drive / DVD Drive Cover rows are omitted for a tag whose
    device_type says it is not a desktop, so the list length is device
    dependent - do not assume it equals len(PARTS_MATRIX).

    `include_master_extras` appends any Spare Part Name configured in Master
    Data that the matrix does not carry. Only Device Detail passes it: the
    repair queues and cosmetic pages use this to COUNT required parts, and an
    extra can never be required, so including it there would only add rows that
    always answer No.
    """
    i = iqc if iqc is not None else _NullIQC()
    desktop = _is_desktop(device)
    rows = []
    for label, category, keyword, fn, section in PARTS_MATRIX:
        # Drop the optical-drive rows only when the tag is KNOWN to be
        # something other than a desktop. See _is_desktop on why unknown shows.
        if label in DESKTOP_ONLY and desktop is False:
            continue
        try:
            required = bool(fn(i, device))
        except Exception:
            required = False
        rows.append({"label": label, "category": category, "keyword": keyword,
                     "required": required, "section": section})
    if include_master_extras:
        for label in extra_master_labels():
            rows.append({"label": label, "category": "Other",
                         "keyword": label.strip().lower(),
                         "required": False, "section": ADDITIONAL})
    return rows
