import os
from fastapi.templating import Jinja2Templates

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# ── Static asset cache-busting ────────────────────────────────────────────────
# Browsers cache /static/* aggressively since StaticFiles sends no explicit
# Cache-Control header (only Last-Modified/ETag), so CSS/JS edits can silently
# not show up for users until a hard refresh. Append this as a ?v= query string
# on asset URLs so every restart forces a fresh fetch.
try:
    ASSET_VERSION = str(int(os.path.getmtime(os.path.join(BASE_DIR, "static", "css", "app.css"))))
except OSError:
    ASSET_VERSION = "1"
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION


# ── Datetime display filters ──────────────────────────────────────────────────
# Timestamps are now stored in the configured app timezone (default: IST/Asia/Kolkata).
# These filters simply format the stored value directly — no UTC conversion needed.
# Old records stored as UTC will display UTC time (slightly off) — acceptable
# for this internal system; new records going forward will show IST correctly.

def ist_format(dt, fmt="%d-%m-%Y %H:%M"):
    """Jinja2 filter: format a datetime for display (stored in app timezone)."""
    if dt is None:
        return "—"
    return dt.strftime(fmt)


def ist_date(dt):
    return ist_format(dt, "%d-%m-%Y")


def ist_time(dt):
    return ist_format(dt, "%H:%M")


def ist_datetime(dt):
    return ist_format(dt, "%d-%m-%Y %H:%M")


# Register Jinja2 filters
templates.env.filters["ist"]          = ist_format    # {{ dt | ist }}
templates.env.filters["ist_date"]     = ist_date      # {{ dt | ist_date }}
templates.env.filters["ist_time"]     = ist_time      # {{ dt | ist_time }}
templates.env.filters["ist_datetime"] = ist_datetime  # {{ dt | ist_datetime }}

# ── Permission helpers — usable in any template ──
#   has_perm(role, module, action)  → single-module check (matrix-driven)
#   any_perm(role, *modules)        → True if ANY listed module is enabled
#                                      (used to show a nav SECTION header only when
#                                       at least one of its modules is visible).
from models.role_permissions import has_perm as _has_perm


def _any_perm(role, *modules):
    return any(_has_perm(role, m, "enable") for m in modules)


templates.env.globals["has_perm"] = _has_perm
templates.env.globals["any_perm"] = _any_perm

_ROLE_DISPLAY = {
    "admin": "Admin",
    "inventory_manager": "Inventory Manager",
    "iqc_inspector": "IQC Handler",
    "l1_engineer": "L1 Engineer",
    "l2_engineer": "L2 Engineer",
    "l3_engineer": "L3/L4 Engineer",
    "qc_inspector": "QC Handler",
    "sales": "Sourcing Sales",
    "spare_parts_manager": "Parts Manager",
    "telecaller": "Telecaller Sales",
    "sales_manager": "Sales Manager",
}


def _prettify_role(val: str) -> str:
    """'trc_manager' → 'TRC Manager': words ≤3 chars uppercased, longer words title-cased."""
    return " ".join(w.upper() if len(w) <= 3 else w.capitalize() for w in val.replace("_", " ").split())


def _role_display(role):
    val = str(getattr(role, "value", role))
    return _ROLE_DISPLAY.get(val, _prettify_role(val))


templates.env.globals["role_display"] = _role_display
templates.env.globals["ROLE_DISPLAY_MAP"] = _ROLE_DISPLAY
