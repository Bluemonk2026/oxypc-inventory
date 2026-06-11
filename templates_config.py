import os
from fastapi.templating import Jinja2Templates

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


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

# ── Permission helper — usable in any template as has_perm(role, module, action) ──
from models.role_permissions import has_perm as _has_perm
templates.env.globals["has_perm"] = _has_perm
