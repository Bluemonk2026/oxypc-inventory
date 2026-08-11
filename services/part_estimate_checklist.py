"""Per-model checklist matrix behind Part Estimation -> "Create Estimate".

Unlike Part Estimate (three broad groups, one line per serviceable part),
Create Estimate prices the exact field-by-field checklist the business
specified: nine groups (Critical, Hardware, Display Panel, Bezel Frame,
Screen/Display, Hinge, Touchpad, Bottom Base, Keyboard), one row per field,
one column per distinct Model in the lot.

Every field counts its DEFECT/MISSING side — the count is "how many of this
model need this part/repair", which is what the price column is pricing.
Fields whose IQC value carries a severity ("No / Minor X / Major X", or a
bare "Yes" with no severity qualifier) are counted per-severity (Minor,
Major) so the modal's Minor/Major checkbox filter can re-sum client-side
without another round trip; a bare "Yes" buckets as Minor (the lightest
defect a technician can record without grading it further).

Grade is not a device filter here, same as Part Estimate: selecting more
than one grade in the modal produces one identical-content file per grade,
purely for record-keeping, not a different device population.
"""
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.device import Device
from models.iqc_inspection import IQCInspection
from services.parts_required import PARTS_MATRIX
from services.part_estimate_matrix import (
    _DEVICE_COLS as _MATRIX_DEVICE_COLS,
    _IQC_COLS as _MATRIX_IQC_COLS,
    model_key,
)

_RULES = {label: fn for label, _c, _k, fn in PARTS_MATRIX}


def _rule(label):
    """Reuse an existing Required=Yes classifier (defect = True)."""
    fn = _RULES[label]
    return lambda i, d: "Yes" if fn(i, d) else "No"


def _blank(val):
    if val is None:
        return True
    return str(val).strip().lower() in (
        "", "-", "n/a", "n / a", "none", "unknown", "not available", "not checked")


def _yesno(field, defect_value="yes", blank_is_defect=False):
    """Plain Yes/No field: defect when the value matches defect_value."""
    def fn(i, _d):
        val = getattr(i, field, None)
        if _blank(val):
            return "Yes" if blank_is_defect else "No"
        return "Yes" if str(val).strip().lower() == defect_value else "No"
    return fn


def _working(field):
    """"Yes / Not Working / No" style field: defect unless it literally says Yes."""
    def fn(i, _d):
        val = getattr(i, field, None)
        if _blank(val):
            return "Yes"
        return "No" if str(val).strip().lower() == "yes" else "Yes"
    return fn


def _port_count(field):
    def fn(i, _d):
        val = getattr(i, field, None)
        return "Yes" if (val is None or int(val) == 0) else "No"
    return fn


def _sev(field):
    """No / Minor / Major, worst-of-one field. A bare 'Yes' (no severity
    qualifier in the stored string) buckets as Minor."""
    def fn(i, _d):
        val = getattr(i, field, None)
        if _blank(val):
            return "No"
        s = str(val).strip().lower()
        if s in ("no",):
            return "No"
        if "major" in s:
            return "Major"
        return "Minor"
    return fn


def _touch_screen(i, _d):
    val = getattr(i, "touch_screen", None)
    if _blank(val):
        return "No"
    return "Faulty" if "faulty" in str(val).strip().lower() else "No"


# Every group belongs to exactly one of the three filter scopes the modal
# shows above the table: Critical Part Added, Hardware Damage, Cosmetic
# Damage Scope — same three-way split the older Part Estimate matrix uses
# (Critical/Internal/Cosmetic), just with Hardware standing in for Internal.
GROUP_SCOPE = {
    "critical": "critical", "hardware": "hardware",
    "display_panel": "cosmetic", "bezel_frame": "cosmetic", "screen_display": "cosmetic",
    "hinge": "cosmetic", "touchpad": "cosmetic", "bottom_base": "cosmetic", "keyboard": "cosmetic",
}

# (group key, heading, [(field name, domain, classifier)])
# domain: "yesno" (sums Yes/No per its scope's Yes/No filter), "sev" (sums
# Minor/Major per the cosmetic scope's Minor/Major filter), "faulty" (sums
# Faulty/No per its scope's Yes/No filter, Faulty standing in for Yes).
CHECKLIST_GROUPS = [
    ("critical", "Critical", [
        ("CPU",        "yesno", lambda i, d: "Yes" if d is not None and _blank(d.cpu) else "No"),
        ("RAM",        "yesno", _rule("RAM")),
        ("Hard Drive", "yesno", _rule("Hard Drive")),
    ]),
    ("hardware", "Hardware", [
        ("HDMI Working",          "yesno", _working("port_hdmi")),
        ("USB Working",           "yesno", _working("port_usb_working")),
        ("Audio jack Working",    "yesno", _working("port_audio_jack")),
        ("Ethernet Working",      "yesno", _port_count("ethernet_ports")),
        ("Speaker Working",       "yesno", _rule("Speaker")),
        ("Wi-Fi working",         "yesno", _rule("Wi-Fi")),
        ("Web Cam working",       "yesno", _rule("Web Cam")),
        ("HDD Connector exist",   "yesno", _rule("HDD Connector")),
        ("DVD Drive exist",       "yesno", _rule("DVD Drive")),
        ("Battery Cable exist",   "yesno", _yesno("battery_cable", defect_value="no", blank_is_defect=True)),
        ("Internal Battery exist","yesno", _rule("Internal Battery")),
    ]),
    ("display_panel", "Display Panel", [
        ("Scratch",      "sev",   _sev("panel_a_scratch")),
        ("Broken/Crack", "sev",   _sev("panel_a_broken")),
        ("Missing",      "yesno", _yesno("panel_a_missing")),
        ("Dent",         "sev",   _sev("panel_a_dent")),
        ("Colour Fade",  "yesno", _yesno("panel_a_colour_fade")),
    ]),
    ("bezel_frame", "Bezel Frame", [
        ("Scratch",      "sev",   _sev("panel_c_scratch")),
        ("Broken/Crack", "sev",   _sev("panel_c_broken")),
        ("Missing",      "yesno", _yesno("panel_c_missing")),
        ("Dent",         "sev",   _sev("panel_c_dent")),
        ("Colour Fade",  "yesno", _yesno("panel_c_colour_fade")),
    ]),
    ("screen_display", "Screen/Display", [
        ("Dot",                   "yesno",  _yesno("screen_dot")),
        ("Line",                  "yesno",  _yesno("screen_line")),
        ("Colour Discoloration",  "sev",    _sev("screen_discoloration")),
        ("Colour Spread",         "yesno",  _yesno("screen_colour_spread")),
        ("Patch",                 "sev",    _sev("screen_patch")),
        ("Flickering",            "yesno",  _yesno("screen_flickering")),
        ("Scratch",               "sev",    _sev("screen_scratch")),
        ("Missing",               "yesno",  _yesno("screen_missing")),
        ("Broken",                "sev",    _sev("screen_broken")),
        ("Keyboard Mark",         "yesno",  _yesno("screen_keyboard_mark")),
        ("Touch Screen",          "faulty", _touch_screen),
    ]),
    ("hinge", "Hinge", [
        ("Hinge",              "yesno", _yesno("hinge_condition")),
        ("Loose",              "yesno", _yesno("screen_loose")),
        ("Hinge Broken",       "yesno", _yesno("screen_hinge_broken")),
        ("Hinge Cover Broken", "sev",   _sev("hinge_cover")),
    ]),
    ("touchpad", "Touchpad", [
        ("Missing",            "yesno", _yesno("touchpad_missing")),
        ("Scratch",            "sev",   _sev("touchpad_scratch")),
        ("Colour Fade",        "yesno", _yesno("touchpad_colour_fade")),
        ("Logicboard Missing", "yesno", _yesno("touchpad_logicboard")),
    ]),
    ("bottom_base", "Bottom Base", [
        ("Scratch",      "sev",   _sev("panel_b_scratch")),
        ("Broken/Crack", "sev",   _sev("panel_b_broken")),
        ("Missing",      "yesno", _yesno("panel_b_missing")),
        ("Colour Fade",  "yesno", _yesno("panel_b_colour_fade")),
        ("Rubber Cut",   "yesno", _yesno("panel_b_rubber_cut")),
    ]),
    ("keyboard", "Keyboard", [
        ("Key Missing", "yesno", _yesno("keyboard_key_missing")),
        ("Hard Press",  "yesno", _yesno("keyboard_hard_press")),
        ("Colour Fade", "yesno", _yesno("keyboard_colour_fade")),
    ]),
]

_STATUS_DOMAINS = {"yesno": ("Yes", "No"), "sev": ("No", "Minor", "Major"), "faulty": ("No", "Faulty")}

_DEVICE_COLS = tuple(dict.fromkeys(_MATRIX_DEVICE_COLS))
_IQC_COLS = tuple(dict.fromkeys(_MATRIX_IQC_COLS + (
    "screen_dot", "screen_line", "screen_colour_spread", "screen_missing",
    "screen_keyboard_mark", "touch_screen", "screen_loose", "screen_hinge_broken",
    "panel_a_broken", "panel_a_missing", "panel_a_dent", "panel_a_colour_fade",
    "panel_c_scratch", "panel_c_broken", "panel_c_missing", "panel_c_dent", "panel_c_colour_fade",
    "panel_b_broken", "panel_b_missing", "panel_b_colour_fade", "panel_b_rubber_cut",
    "keyboard_key_missing", "keyboard_hard_press", "keyboard_colour_fade",
    "touchpad_missing", "touchpad_colour_fade", "touchpad_logicboard",
    "hinge_condition", "port_hdmi", "port_usb_working", "port_audio_jack",
    "battery_cable",
)))


def group_meta() -> list[dict]:
    return [{"key": key, "heading": heading,
             "fields": [{"name": name, "domain": domain} for name, domain, _fn in fields]}
            for key, heading, fields in CHECKLIST_GROUPS]


class _NullIQC:
    def __getattr__(self, _name):
        return None


def _select_cols():
    cols = [Device.model, Device.brand, Device.device_type, Device.sub_category]
    cols += [getattr(Device, c) for c in _DEVICE_COLS]
    cols += [getattr(IQCInspection, c) for c in _IQC_COLS]
    return cols


async def lot_checklist_matrix(db: AsyncSession, lot_id) -> list[dict]:
    """[{key, model, make, device_type, qty,
         counts: {group: {field: {status: n}}}}] — one row per distinct
    Model in the lot, every field's raw status breakdown so the modal can
    re-sum Minor/Major client-side with no extra round trip."""
    rows = (await db.execute(
        select(*_select_cols())
        .outerjoin(IQCInspection, IQCInspection.device_id == Device.id)
        .where(Device.lot_id == lot_id,
               Device.is_active == True, Device.is_trashed == False)  # noqa: E712
    )).all()

    n_head, n_dev = 4, len(_DEVICE_COLS)
    merged: dict = {}

    for row in rows:
        model, make, dtype, sub = row[0], row[1], row[2], row[3]
        dtype = dtype or sub
        device = SimpleNamespace(**dict(zip(_DEVICE_COLS, row[n_head:n_head + n_dev])))
        iqc_vals = row[n_head + n_dev:]
        iqc = _NullIQC() if all(v is None for v in iqc_vals) else \
            SimpleNamespace(**dict(zip(_IQC_COLS, iqc_vals)))

        key = model_key(model, make, dtype)
        entry = merged.get(key)
        if entry is None:
            entry = merged[key] = {
                "key": key, "qty": 0, "spellings": {},
                "counts": {g: {name: {s: 0 for s in _STATUS_DOMAINS[domain]} for name, domain, _fn in fields}
                           for g, _h, fields in CHECKLIST_GROUPS},
            }
        entry["qty"] += 1
        spell = ((model or "").strip(), (make or "").strip(), (dtype or "").strip())
        entry["spellings"][spell] = entry["spellings"].get(spell, 0) + 1

        for g, _h, fields in CHECKLIST_GROUPS:
            bucket = entry["counts"][g]
            for name, _domain, fn in fields:
                try:
                    status = fn(iqc, device)
                except Exception:
                    status = "No"
                if status in bucket[name]:
                    bucket[name][status] += 1

    out = []
    for entry in merged.values():
        model, make, dtype = max(entry["spellings"].items(), key=lambda kv: kv[1])[0]
        out.append({
            "key": entry["key"], "model": model or "—", "make": make or "—",
            "device_type": dtype or "—", "qty": entry["qty"], "counts": entry["counts"],
        })
    out.sort(key=lambda r: (-r["qty"], r["model"]))
    return out


def quantities_for(matrix: list[dict], filters: dict) -> dict:
    """Server-side re-derivation of every count the modal displayed.
    {model_key: {group: {field: count}}}. `filters` is
    {"critical": {"yes": bool, "no": bool},
     "hardware": {"yes": bool, "no": bool},
     "cosmetic": {"yes": bool, "no": bool, "minor": bool, "major": bool}}.
    A "sev" field sums whichever of Minor/Major its scope has checked;
    "yesno"/"faulty" fields sum whichever of Yes/No (Faulty standing in for
    Yes) their scope has checked."""
    out: dict = {}
    for row in matrix:
        per_group = {}
        for g, _h, fields in CHECKLIST_GROUPS:
            f = filters.get(GROUP_SCOPE[g]) or {}
            per_field = {}
            for name, domain, _fn in fields:
                counts = row["counts"][g][name]
                if domain == "sev":
                    n = (counts.get("Minor", 0) if f.get("minor") else 0) + \
                        (counts.get("Major", 0) if f.get("major") else 0)
                else:
                    pos_key = "Faulty" if domain == "faulty" else "Yes"
                    n = (counts.get(pos_key, 0) if f.get("yes") else 0) + \
                        (counts.get("No", 0) if f.get("no") else 0)
                per_field[name] = n
            per_group[g] = per_field
        out[row["key"]] = per_group
    return out
