"""
OxyPC Application Timezone Utility
====================================
Single source of truth for "what time is it now" in the configured app timezone.

Usage in models (Column default):
    from utils.timezone import app_now
    created_at = Column(DateTime, default=app_now)

Usage in routers (explicit timestamp):
    from utils.timezone import app_now
    record.updated_at = app_now()

The active timezone is set at startup by loading app_timezone from app_settings,
and updated whenever admin changes the timezone in Company Settings.

Default: Asia/Kolkata (IST = UTC+5:30)
"""
from __future__ import annotations

import pytz
from datetime import datetime, date

# ── Module-level timezone state ────────────────────────────────────────────────
_DEFAULT_TZ_NAME: str = "Asia/Kolkata"
_app_tz = pytz.timezone(_DEFAULT_TZ_NAME)
_app_tz_name: str = _DEFAULT_TZ_NAME


# ── Public API ─────────────────────────────────────────────────────────────────

def set_app_timezone(tz_name: str) -> None:
    """Update the active application timezone.
    Called once at startup (from app_settings in DB) and when admin saves settings.
    Invalid timezone names are silently ignored — current timezone is preserved.
    """
    global _app_tz, _app_tz_name
    try:
        _app_tz = pytz.timezone(tz_name)
        _app_tz_name = tz_name
    except (pytz.exceptions.UnknownTimeZoneError, AttributeError, KeyError):
        pass  # keep current valid timezone


def get_app_timezone_name() -> str:
    """Return the name of the currently active timezone (e.g. 'Asia/Kolkata')."""
    return _app_tz_name


def app_now() -> datetime:
    """Return current datetime in the configured app timezone, as a naive datetime.
    Use this everywhere you previously used datetime.utcnow().
    Stored values will be in the configured local timezone.
    """
    return datetime.now(_app_tz).replace(tzinfo=None)


def app_today() -> date:
    """Return today's date in the configured app timezone."""
    return app_now().date()


# ── Jinja2 / display helpers ───────────────────────────────────────────────────

def format_dt(dt: datetime | None, fmt: str = "%d-%m-%Y %H:%M") -> str:
    """Format a datetime for display. Returns '—' for None."""
    if dt is None:
        return "—"
    return dt.strftime(fmt)


def format_date(dt: datetime | None) -> str:
    return format_dt(dt, "%d-%m-%Y")
