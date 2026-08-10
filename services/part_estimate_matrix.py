"""Per-model part matrix behind Part Estimation -> "Part Estimate".

The Generate Estimate modal costs a lot as a single bill. Part Estimate costs
it the way production actually buys: model by model, and only for the condition
band the buyer is willing to pay for. So every part carries a count for each
status a technician could have recorded, and the modal picks one band per
group ("Cosmetic Part Damage? = Major" -> how many of this model need a Major
panel).

Note on Yes/No polarity: "Yes" always means the classifier's original finding
(the part is required / needs sourcing), regardless of how the group's filter
label reads in English. Renaming "Critical Part Status" to "Critical Part
Available?" did not flip which answer counts as needing a part — an operator
still picks "Yes" for a part that is missing/faulty, the way they always have.
Flipping that polarity to match the new wording literally (Yes = present) is
a separate, bigger change (classifiers, JS defaults, workbook headers) that
was deliberately not made alongside a same-turn rename.

Three groups, fixed by the business:

  Critical  CPU / RAM / Hard Drive             status: Yes | No
  Internal  the thirteen serviceable parts     status: Yes | No
  Cosmetic  the seven body / display parts     status: Yes | No | Minor | Major

Yes/No parts reuse the Required=Yes rules from services.parts_required, so a
count here can never disagree with the Required badge on Device Detail. The
cosmetic parts are graded instead of flagged: the status is the worst severity
recorded across that part's IQC fields.
"""
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.device import Device
from models.iqc_inspection import IQCInspection
from services.parts_required import PARTS_MATRIX
from services.part_estimation import _DEVICE_COLS as _BASE_DEVICE_COLS
from services.part_estimation import _IQC_COLS as _BASE_IQC_COLS

# ── Columns ───────────────────────────────────────────────────────────────────
# The Required=Yes rules need everything services.part_estimation already
# selects; the additions below are what this module's own classifiers read.
# Importing the base tuples keeps the two lists from drifting apart when a rule
# starts reading a new column.
_DEVICE_COLS = tuple(dict.fromkeys(_BASE_DEVICE_COLS + ("cpu",)))

_IQC_COLS = tuple(dict.fromkeys(_BASE_IQC_COLS + (
    "battery_cable", "usb_a_ports", "usb_c_ports", "ethernet_ports",
    "panel_a_scratch", "panel_b_scratch", "panel_c_scratch", "panel_d_scratch",
    "screen_scratch", "screen_discoloration", "screen_patch",
    "touchpad_scratch", "hinge_cover",
)))

YES_NO = ("Yes", "No")
SEVERITY = ("Yes", "No", "Minor", "Major")

_RULES = {label: fn for label, _c, _k, fn in PARTS_MATRIX}


def _blank(val):
    """True when a text field carries nothing a buyer could act on."""
    if val is None:
        return True
    return str(val).strip().lower() in (
        "", "-", "n/a", "n / a", "none", "unknown", "not available", "not checked")


def _missing_count(val):
    """Port-count fields: absent or zero means the port is not there."""
    return val is None or int(val) == 0


def _rule(label):
    """Yes/No classifier borrowed from the Parts Consumption matrix."""
    fn = _RULES[label]
    return lambda i, d: "Yes" if fn(i, d) else "No"


def _flag(fn):
    return lambda i, d: "Yes" if fn(i, d) else "No"


# Worst-wins ranking. "Yes" sits between "No" and "Minor": it is a defect the
# technician recorded without grading, so it must not outrank a graded one.
_SEV_NAMES = ("No", "Yes", "Minor", "Major")


def _rank(val):
    if val is None:
        return 0
    s = str(val).strip().lower()
    if not s or s in ("no", "-", "n/a", "none", "not checked", "not available"):
        return 0
    # Historic wording ("Major Broken", "Minor Scratch") ranks the same as the
    # current one-word scale, so pre-unification inspections still band.
    if "major" in s:
        return 3
    if "minor" in s:
        return 2
    return 1


def _severity(*fields):
    """Worst severity across a cosmetic part's IQC fields."""
    def fn(i, _d):
        return _SEV_NAMES[max(_rank(getattr(i, f, None)) for f in fields)]
    return fn


# ── The three groups ─────────────────────────────────────────────────────────
# (group key, heading, filter label, allowed statuses, [(part name, classifier)])
PART_GROUPS = [
    ("critical", "Critical", "Critical Part Available?", YES_NO, [
        # No IQC field records the processor; a blank CPU on the device is the
        # only evidence the machine needs one.
        ("CPU",              _flag(lambda i, d: d is not None and _blank(d.cpu))),
        ("RAM",              _rule("RAM")),
        ("Hard Drive",       _rule("Hard Drive")),
    ]),
    ("internal", "Internal", "Internal Part Working?", YES_NO, [
        ("Battery Cable",    _flag(lambda i, d: _blank(i.battery_cable)
                                   or str(i.battery_cable).strip().lower() == "no")),
        ("Internal Battery", _rule("Internal Battery")),
        ("Keyboard",         _rule("Keyboard")),
        ("Touchpad",         _rule("Touchpad")),
        ("USB A Ports",      _flag(lambda i, d: _missing_count(i.usb_a_ports))),
        ("USB C Ports",      _flag(lambda i, d: _missing_count(i.usb_c_ports))),
        ("Ethernet Ports",   _flag(lambda i, d: _missing_count(i.ethernet_ports))),
        ("Speaker Status",   _rule("Speaker")),
        ("Wi-Fi",            _rule("Wi-Fi")),
        ("Web Cam",          _rule("Web Cam")),
        ("HDD Connector",    _rule("HDD Connector")),
        ("Motherboard",      _rule("Motherboard")),
        ("DVD Drive",        _rule("DVD Drive")),
    ]),
    # Touchpad appears once, though it is both an internal and a cosmetic part:
    # here it is graded on its scratch field, above it is flagged on whether it
    # works. Costing the same name twice in one group would double-count it.
    ("cosmetic", "Cosmetic", "Cosmetic Part Damage?", SEVERITY, [
        ("Display Panel",    _severity("panel_a_scratch", "panel_a_broken", "panel_a_dent")),
        ("Bezel Frame",      _severity("panel_c_scratch", "panel_c_broken", "panel_c_dent")),
        ("Screen",           _severity("screen_discoloration", "screen_patch",
                                       "screen_scratch", "screen_broken")),
        ("Touchpad",         _severity("touchpad_scratch")),
        ("Hinge",            _severity("hinge_cover")),
        ("Bottom Base",      _severity("panel_b_scratch", "panel_b_broken")),
        ("Palmrest",         _severity("panel_d_scratch", "panel_d_broken", "panel_d_dent")),
    ]),
]

GROUP_STATUSES = {key: list(statuses) for key, _h, _f, statuses, _p in PART_GROUPS}


def group_meta() -> list[dict]:
    """Group headings / filters / part names — everything the modal renders
    before any lot is chosen."""
    return [{
        "key": key, "heading": heading, "filter_label": filter_label,
        "statuses": list(statuses), "parts": [name for name, _fn in parts],
    } for key, heading, filter_label, statuses, parts in PART_GROUPS]


def _select_cols():
    cols = [Device.model, Device.brand, Device.device_type, Device.sub_category]
    cols += [getattr(Device, c) for c in _DEVICE_COLS]
    cols += [getattr(IQCInspection, c) for c in _IQC_COLS]
    return cols


class _NullIQC:
    def __getattr__(self, _name):
        return None


def model_key(model: str, make: str, device_type: str) -> str:
    """Stable identity for one Model Summary row.

    The browser sends this back with the prices, so it has to survive a
    round-trip and mean the same thing on both sides: case-folded, so "HP" and
    "Hp" are one model here exactly as they are on the PO Preview summary.
    """
    return "|".join(p.strip().upper() for p in (model or "", make or "", device_type or ""))


async def lot_model_matrix(db: AsyncSession, lot_id) -> list[dict]:
    """Model Summary rows for a lot, each carrying a full status breakdown.

    [{key, model, make, device_type, qty,
      counts: {group: {part: {status: n}}}}]

    counts[group][part][status] is how many tags of that model were recorded at
    that status, so the modal can re-price a whole group by changing one
    dropdown instead of asking the server again.
    """
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
        # device_type is NULL on roughly a quarter of devices while
        # sub_category is set — same fallback the PO Preview summary uses.
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
                "counts": {g: {name: {s: 0 for s in statuses} for name, _fn in parts}
                           for g, _h, _f, statuses, parts in PART_GROUPS},
            }
        entry["qty"] += 1
        spell = ((model or "").strip(), (make or "").strip(), (dtype or "").strip())
        entry["spellings"][spell] = entry["spellings"].get(spell, 0) + 1

        for g, _h, _f, statuses, parts in PART_GROUPS:
            bucket = entry["counts"][g]
            for name, fn in parts:
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


def quantities_for(matrix: list[dict], selections: dict) -> dict:
    """Server-side re-derivation of every quantity the modal displayed.

    selections is {model_key: {group: status}}. Returns
    {model_key: {group: {part: qty}}} using only the counts computed from IQC —
    the browser's numbers are never trusted, only its status choices are.
    """
    out: dict = {}
    for row in matrix:
        chosen = selections.get(row["key"]) or {}
        per_group = {}
        for g, _h, _f, statuses, parts in PART_GROUPS:
            status = chosen.get(g)
            # "Select" (or anything unrecognised) costs nothing — it is how the
            # operator drops a whole group out of the estimate.
            if status not in statuses:
                per_group[g] = {name: 0 for name, _fn in parts}
                continue
            per_group[g] = {name: row["counts"][g][name].get(status, 0)
                            for name, _fn in parts}
        out[row["key"]] = per_group
    return out
