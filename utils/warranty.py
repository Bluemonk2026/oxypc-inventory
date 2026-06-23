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
