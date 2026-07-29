"""Shared Date Range filter parsing.

Used by All Inventory, Product IQC, Inventory Manager (Stock Inwards),
Production Manager and GRN Report so the five pages behave identically.
"""
from datetime import datetime, timedelta


def parse_date_range(date_from: str = "", date_to: str = ""):
    """('YYYY-MM-DD', 'YYYY-MM-DD') -> (start, end_exclusive).

    The end date is pushed to the following midnight so a single-day range
    includes everything recorded on that day, not just 00:00:00. Unparseable
    or blank input yields None for that bound rather than an error — a bad
    date should not blank the page.
    """
    def _p(s):
        try:
            return datetime.strptime((s or "").strip(), "%Y-%m-%d")
        except (ValueError, TypeError):
            return None

    start = _p(date_from)
    end = _p(date_to)
    if end:
        end = end + timedelta(days=1)
    return start, end


def apply_date_range(filters: list, column, date_from: str = "", date_to: str = ""):
    """Append the range predicates for `column` to `filters`. Returns (from, to)
    so callers can echo the raw values back to the template."""
    start, end = parse_date_range(date_from, date_to)
    if start is not None:
        filters.append(column >= start)
    if end is not None:
        filters.append(column < end)
    return start, end
