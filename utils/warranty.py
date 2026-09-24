"""
OxyPC Warranty Utility
======================
Single source of truth for device warranty derivation.

Policy: warranty runs for WARRANTY_DAYS (30) days from the most recent Sale date
(Sale.sold_at) of a device. A device that was never sold has no warranty.

Definition (per spec):
  - Active   -> "Warranty Left: <N> days"  where N = 30 - days_passed_since_sale
  - Expired  -> "Warranty Expired on <DD Mon YYYY>"  (sale_date + 30 days)

Used by Ready to Sale, Ready to Dispatch, Process Return and L3 replacement views.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from utils.timezone import app_now

WARRANTY_DAYS = 30


def warranty_from_sold_at(sold_at: datetime | None) -> dict | None:
    """Return a warranty descriptor dict for a given sale timestamp, or None if
    there is no sale (hence no warranty).

    Dict shape:
        {"status": "active"|"expired", "days_left": int, "expiry": datetime,
         "label": str}
    """
    if not sold_at:
        return None
    expiry = sold_at + timedelta(days=WARRANTY_DAYS)
    now = app_now()
    if now <= expiry:
        days_left = (expiry.date() - now.date()).days
        if days_left < 0:
            days_left = 0
        return {
            "status": "active",
            "days_left": days_left,
            "expiry": expiry,
            "label": f"Warranty Left: {days_left} days",
        }
    return {
        "status": "expired",
        "days_left": 0,
        "expiry": expiry,
        "label": f"Warranty Expired on {expiry.strftime('%d %b %Y')}",
    }


def warranty_label(sold_at: datetime | None, none_text: str = "—") -> str:
    """Convenience: just the display label, with a fallback when no warranty."""
    w = warranty_from_sold_at(sold_at)
    return w["label"] if w else none_text


WARRANTY_DURATIONS = {
    "none": None,
    "30_days": timedelta(days=30),
    "6_months": timedelta(days=182),
    "1_year": timedelta(days=365),
}


def compute_warranty_expiry(sold_at: datetime, warranty_type: str) -> datetime | None:
    """Server-side computation of warranty_expires_at from sold_at + warranty_type.
    Returns None for warranty_type == 'none' or unrecognized values."""
    if not sold_at:
        return None
    delta = WARRANTY_DURATIONS.get(warranty_type)
    if delta is None:
        return None
    return sold_at + delta


def effective_warranty_for_sale(sale) -> dict | None:
    """Same descriptor shape as warranty_from_sold_at (status/days_left/expiry/
    label), but gives precedence to an explicit Sale.warranty_type +
    warranty_expires_at (set at sale time, or pushed forward by Extended
    Warranty) over the implicit WARRANTY_DAYS-from-sold_at default. Falls back
    to warranty_from_sold_at when this sale never had a warranty_type chosen.

    Use this instead of warranty_from_sold_at anywhere the result needs to
    agree with warranty_status_for_sale (the RMA/Extended Warranty status) for
    the same sale — warranty_from_sold_at never looks at warranty_expires_at
    at all, so after a warranty extension it kept reporting "Out of Warranty"
    on Process Return's "Warranty Status" field while RMA Warranty correctly
    said "In Warranty" for the same tag, and Process Return's paid-repair-
    charge banner keyed off the stale one.
    """
    if not sale:
        return None
    wtype = getattr(sale, "warranty_type", None) or "none"
    expires_at = getattr(sale, "warranty_expires_at", None)
    if wtype == "none" or not expires_at:
        return warranty_from_sold_at(getattr(sale, "sold_at", None))
    now = app_now()
    if now <= expires_at:
        days_left = max((expires_at.date() - now.date()).days, 0)
        return {
            "status": "active", "days_left": days_left, "expiry": expires_at,
            "label": f"Warranty Left: {days_left} days",
        }
    return {
        "status": "expired", "days_left": 0, "expiry": expires_at,
        "label": f"Warranty Expired on {expires_at.strftime('%d %b %Y')}",
    }


def warranty_status_for_sale(sale) -> str:
    """Return 'in_warranty' | 'out_of_warranty' | 'no_warranty' for a Sale record,
    using the Sale's own warranty_type/warranty_expires_at (Phase 1a fields).
    Falls back to 'no_warranty' when there is no sale or no warranty was selected."""
    if not sale:
        return "no_warranty"
    wtype = getattr(sale, "warranty_type", None) or "none"
    if wtype == "none":
        return "no_warranty"
    expires_at = getattr(sale, "warranty_expires_at", None)
    if not expires_at:
        return "no_warranty"
    now = app_now()
    return "in_warranty" if now <= expires_at else "out_of_warranty"


async def latest_sold_at_map(db, device_ids) -> dict:
    """Return {device_id(str): latest Sale.sold_at} for the given device ids.

    Used to build warranty columns without N+1 queries. Imports are local to
    avoid a circular import with models at module load.
    """
    from sqlalchemy import select, func
    from models.sales import Sale

    out: dict = {}
    if not device_ids:
        return out
    rows = (await db.execute(
        select(Sale.device_id, func.max(Sale.sold_at))
        .where(Sale.device_id.in_(list(device_ids)))
        .group_by(Sale.device_id)
    )).all()
    for did, sold_at in rows:
        out[str(did)] = sold_at
    return out
