"""All Inventory helpers shared by the Tag table (/devices/data) and the Model
Based Summary (/devices/model-summary/data), so the two always agree.

  * Token-wise AND search over Make / Model / CPU / RAM / Storage (+ caller
    extras). "HP 840 16GB i5 512" = every whitespace-separated token must match
    at least one column. RAM and Storage are numeric columns (ram_gb,
    storage_gb) plus packed text summaries, so a token like "16", "16GB",
    "16 GB" or "1TB" is matched numerically as well as textually.
  * SQL expressions for the derived columns the summary groups / filters on
    (Stock Type, Touch Type, RAM / Storage labels).
  * Pure-Python folding of the grouped rows into the summary's badge columns and
    the Total row, plus the HTML for those cells.
"""
import re
from html import escape

from sqlalchemy import and_, case, cast, func, or_, String

from models.device import Device, DeviceStage
from utils.touch_type import TOUCH, NON_TOUCH, normalize_touch, touch_abbr

# ── Search ───────────────────────────────────────────────────────────────────

# "16 GB" / "1 TB" -> "16GB" / "1TB" before splitting on whitespace.
_UNIT_GAP_RE = re.compile(r"(\d+(?:\.\d+)?)\s+(gb|tb|g|t)\b", re.I)
_NUM_UNIT_RE = re.compile(r"^(\d+(?:\.\d+)?)(gb|tb|g|t)?$", re.I)
_MAX_NUMERIC = 1_000_000  # keep integer-column comparisons inside int32


def search_tokens(text) -> list:
    """Whitespace/comma separated search tokens, with "16 GB" glued to "16GB"."""
    text = _UNIT_GAP_RE.sub(r"\1\2", str(text or ""))
    return [t for t in re.split(r"[\s,;]+", text.strip()) if t]


def _ilike(col, token):
    esc = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return col.ilike(f"%{esc}%", escape="\\")


def _gb_values(number: float, unit: str) -> list:
    """Candidate GB values a numeric token can stand for (1TB = 1000 or 1024 GB)."""
    if unit.startswith("t"):
        cands = {number * 1000, number * 1024}
    else:
        cands = {number}
    return sorted({int(c) for c in cands if c == int(c) and 0 < c <= _MAX_NUMERIC})


def token_clause(token: str, extra_cols=()):
    """One token must match Make, Model, CPU, RAM or Storage (or an extra column)."""
    ram_storage_text = [Device.ram_summary, Device.hdd_summary, Device.storage_type]
    m = _NUM_UNIT_RE.match(token)
    clauses = [_ilike(c, token) for c in ram_storage_text]
    gb = []
    if m:
        unit = (m.group(2) or "").lower()
        gb = _gb_values(float(m.group(1)), unit)
        if gb:
            clauses += [Device.ram_gb.in_(gb), Device.storage_gb.in_(gb), Device.hdd_capacity_gb.in_(gb)]
        if unit:
            # "16GB" / "1TB" only ever means RAM or Storage; skipping the free-text
            # columns keeps e.g. "1t" from matching every model with a "1T" in it.
            return or_(*clauses)
    clauses += [_ilike(c, token) for c in (Device.brand, Device.model, Device.cpu, *extra_cols)]
    return or_(*clauses)


def device_search_clause(text, extra_cols=()):
    """AND of token_clause per token, or None for an empty search."""
    tokens = search_tokens(text)
    if not tokens:
        return None
    return and_(*[token_clause(t, extra_cols) for t in tokens])


# ── Derived SQL expressions ──────────────────────────────────────────────────

STOCK_FINISH_GOOD, STOCK_AS_IS, STOCK_IN_PROGRESS = "Finish Good", "As-Is", "In Progress"
STOCK_ORDER = [STOCK_FINISH_GOOD, STOCK_AS_IS, STOCK_IN_PROGRESS]
TOUCH_ORDER = ["T", "NT"]
UNKNOWN_MAKE, UNKNOWN_MODEL, UNSET = "Unknown Make", "Unknown Model", "—"
UNASSIGNED_ENTITY, UNGRADED = "Unassigned", "Ungraded"


def stock_type_expr():
    """SQL twin of routers.devices._stock_label (kept in step by a test)."""
    has_sub = func.coalesce(func.trim(Device.sub_lot_number), "") != ""
    return case(
        (Device.current_stage.in_([DeviceStage.ready_to_sale, DeviceStage.sold]),
         case((has_sub, STOCK_AS_IS), else_=STOCK_FINISH_GOOD)),
        else_=STOCK_IN_PROGRESS,
    )


def touch_expr():
    """SQL twin of utils.touch_type.normalize_touch: 'Touch' or 'Non-Touch'."""
    return case(
        (func.lower(func.trim(func.coalesce(Device.touch_type, ""))).in_(("touch", "t", "yes", "true")), TOUCH),
        else_=NON_TOUCH,
    )


def _clean(col, unset):
    return func.coalesce(func.nullif(func.trim(col), ""), unset)


def summary_label_exprs() -> dict:
    """Group-key expressions of the Model Based Summary. Shared with the per-row
    tag modal so a group's tags are found by the very same expressions."""
    return {
        "make": _clean(Device.brand, UNKNOWN_MAKE),
        "model": _clean(Device.model, UNKNOWN_MODEL),
        "device_type": _clean(Device.device_type, UNSET),
        "cpu": _clean(Device.cpu, UNSET),
        "ram": case((Device.ram_gb > 0, cast(Device.ram_gb, String) + "GB"),
                    else_=_clean(Device.ram_summary, UNSET)),
        "storage": case((Device.storage_gb > 0,
                         func.concat_ws(" ", cast(Device.storage_gb, String) + "GB",
                                        func.nullif(func.trim(Device.storage_type), ""))),
                        else_=_clean(Device.hdd_summary, UNSET)),
    }


def make_filter_clause(values):
    """Device.brand IN (...); "Unknown Make" matches NULL/blank brands."""
    real = [v for v in values if v != UNKNOWN_MAKE]
    clauses = []
    if real:
        clauses.append(Device.brand.in_(real))
    if len(real) != len(values):
        clauses.append(or_(Device.brand.is_(None), func.trim(Device.brand) == ""))
    return or_(*clauses) if clauses else None


def touch_filter_clause(values):
    wanted = {normalize_touch(v) for v in values}
    if not wanted or wanted == {TOUCH, NON_TOUCH}:
        return None
    return touch_expr() == wanted.pop()


def stock_filter_clause(values):
    wanted = [v for v in values if v in STOCK_ORDER]
    return stock_type_expr().in_(wanted) if wanted else None


# ── Entity abbreviation ──────────────────────────────────────────────────────

def entity_abbr(name) -> str:
    """Deterministic badge abbreviation: initials of the words ('OxyPC Computers'
    -> 'OC', 'Renew Circuits' -> 'RC'; at most 4), or the first 3 letters of a
    single-word name ('Deshwal' -> 'DES')."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", str(name or "").strip()) if w]
    if not words:
        return "NA"
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(w[0] for w in words)[:4].upper()


# ── Folding grouped rows into summary rows ───────────────────────────────────

GROUP_KEYS = ("make", "model", "device_type", "cpu", "ram", "storage")


def _bump(d: dict, key, n):
    d[key] = d.get(key, 0) + n


def _new_acc() -> dict:
    return {"total_count": 0, "total_price": 0.0, "repaired_count": 0,
            "touch_counts": {}, "grade_counts": {"A": 0, "B": 0, "C": 0},
            "stock_counts": {}, "entity_counts": {}}


def _add(acc: dict, r: dict):
    n = int(r.get("n") or 0)
    acc["total_count"] += n
    acc["total_price"] += float(r.get("price") or 0)
    acc["repaired_count"] += int(r.get("repaired") or 0)
    _bump(acc["touch_counts"], touch_abbr(r.get("touch")), n)
    grade = getattr(r.get("grade"), "value", r.get("grade")) or UNGRADED
    _bump(acc["grade_counts"], str(grade), n)
    _bump(acc["stock_counts"], r.get("stock") or STOCK_IN_PROGRESS, n)
    _bump(acc["entity_counts"], (r.get("entity") or UNASSIGNED_ENTITY), n)


def _finish(acc: dict) -> dict:
    acc["total_price"] = round(acc["total_price"], 2)
    acc["unit_price"] = round(acc["total_price"] / acc["total_count"], 2) if acc["total_count"] else 0
    return acc


def fold_summary_rows(rows):
    """rows: dicts with the GROUP_KEYS plus touch, grade, stock, entity, n, price,
    repaired (one per distinct combination). Returns (groups, totals): one group
    per distinct (make, model, device_type, cpu, ram, storage), and the grand
    totals over the same rows."""
    groups, totals = {}, _new_acc()
    for r in rows:
        key = tuple(r[k] for k in GROUP_KEYS)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {**dict(zip(GROUP_KEYS, key)), **_new_acc()}
        _add(g, r)
        _add(totals, r)
    out = [_finish(g) for g in groups.values()]
    out.sort(key=lambda g: (-g["total_count"], g["make"].lower(), g["model"].lower()))
    return out, _finish(totals)


# ── Badges ───────────────────────────────────────────────────────────────────

def badge_text(label, n) -> str:
    return f"{label}-{n}"


def _grade_sort(label):
    return (label == UNGRADED, label.lower())


def ordered_counts(counts: dict, kind: str) -> list:
    """[(label, n), ...] with zero counts dropped, in a stable display order."""
    items = [(k, v) for k, v in counts.items() if v]
    if kind == "touch":
        return sorted(items, key=lambda kv: TOUCH_ORDER.index(kv[0]) if kv[0] in TOUCH_ORDER else 99)
    if kind == "stock":
        return sorted(items, key=lambda kv: STOCK_ORDER.index(kv[0]) if kv[0] in STOCK_ORDER else 99)
    if kind == "grade":
        return sorted(items, key=lambda kv: _grade_sort(kv[0]))
    return sorted(items, key=lambda kv: (-kv[1], kv[0].lower()))   # entity: biggest first


_GRADE_CLS = {"A": "success", "B": "warning text-dark", "C": "secondary", "D": "danger",
              "E": "danger", "scrap": "danger", UNGRADED: "light text-dark border"}
_STOCK_CLS = {STOCK_FINISH_GOOD: "success", STOCK_AS_IS: "warning text-dark",
              STOCK_IN_PROGRESS: "info text-dark"}
_TOUCH_CLS = {"T": "success", "NT": "secondary"}


def badges_html(counts: dict, kind: str) -> str:
    """One nowrap row of '<label>-<count>' badges."""
    parts = []
    for label, n in ordered_counts(counts, kind):
        if kind == "entity":
            text, cls, title = badge_text(entity_abbr(label), n), "light text-dark border", label
        else:
            cls = {"grade": _GRADE_CLS, "stock": _STOCK_CLS, "touch": _TOUCH_CLS}[kind].get(label, "light text-dark border")
            text, title = badge_text(label, n), label
        parts.append(f'<span class="badge bg-{cls}" title="{escape(str(title), quote=True)}">{escape(text)}</span>')
    if not parts:
        return ""
    return '<div class="d-flex flex-nowrap gap-1 text-nowrap">' + "".join(parts) + "</div>"


def count_cell_html(g: dict) -> str:
    """Total Count column: the number plus per-entity '<abbr>-<n>' badges."""
    return (f'<div class="d-flex flex-nowrap align-items-center gap-2 text-nowrap">'
            f'<strong>{g["total_count"]}</strong>{badges_html(g["entity_counts"], "entity")}</div>')


def _money(v) -> str:
    return "₹" + "{:,.0f}".format(v or 0)


def group_row_cells(g: dict, show_pricing: bool, actions_html: str) -> list:
    cells = [escape(str(g[k])) for k in GROUP_KEYS]
    cells += [badges_html(g["touch_counts"], "touch"), badges_html(g["grade_counts"], "grade"),
              badges_html(g["stock_counts"], "stock"), count_cell_html(g)]
    if show_pricing:
        cells.append(_money(g["total_price"]))
    cells.append(actions_html)
    return cells


def total_row_cells(t: dict, show_pricing: bool) -> list:
    cells = ['<strong class="summary-total-label">Total</strong>'] + [""] * (len(GROUP_KEYS) - 1)
    cells += [badges_html(t["touch_counts"], "touch"), badges_html(t["grade_counts"], "grade"),
              badges_html(t["stock_counts"], "stock"), count_cell_html(t)]
    if show_pricing:
        cells.append(f"<strong>{_money(t['total_price'])}</strong>")
    cells.append("")
    return cells
