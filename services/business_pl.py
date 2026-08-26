"""Shared Parts/Labour COGS-per-year computation — the single source both
Business P&L's Monthly Breakdown table (routers/reports.py business_pl) and
the Dashboard's Financial Summary card (routers/dashboard.py) call, so the
two never disagree on the same year's Parts Cost / Labour Cost figures.

Mirrors business_pl()'s own query shape and override-merge logic exactly;
extracted here so a future change to either only has to happen once.
"""
from sqlalchemy import select, func, extract
from sqlalchemy.ext.asyncio import AsyncSession

from models.device import Device
from models.engines import RepairAttempt
from models.sales import Sale
from models.spare_parts import SparePartConsumption
from models.business_pl_override import BusinessPLOverride


async def compute_year_parts_labour_cogs(db: AsyncSession, year: int) -> tuple[list, list]:
    """Returns (monthly_parts_cogs, monthly_labour_cogs) — 12-element lists,
    Jan..Dec, for `year`, with any admin overrides (/reports/business-pl/override)
    already applied. Callers needing the yearly total just sum() the list."""
    parts_result = await db.execute(
        select(
            extract("month", Sale.sold_at).label("month"),
            func.coalesce(func.sum(SparePartConsumption.total_cost), 0).label("parts_cost"),
        )
        .join(Device, SparePartConsumption.device_id == Device.id)
        .join(Sale, Sale.device_id == Device.id)
        .where(SparePartConsumption.device_id.isnot(None))
        .where(extract("year", Sale.sold_at) == year)
        .group_by(extract("month", Sale.sold_at))
    )
    parts_by_month = {int(r.month): float(r.parts_cost) for r in parts_result}
    monthly_parts_cogs = [parts_by_month.get(m, 0.0) for m in range(1, 13)]

    labour_result = await db.execute(
        select(
            extract("month", Sale.sold_at).label("month"),
            func.coalesce(func.sum(RepairAttempt.cost), 0).label("labour_cost"),
        )
        .join(Device, RepairAttempt.device_id == Device.id)
        .join(Sale, Sale.device_id == Device.id)
        .where(extract("year", Sale.sold_at) == year)
        .group_by(extract("month", Sale.sold_at))
    )
    labour_by_month = {int(r.month): float(r.labour_cost) for r in labour_result}
    monthly_labour_cogs = [labour_by_month.get(m, 0.0) for m in range(1, 13)]

    overrides = {
        o.month: o for o in (await db.execute(
            select(BusinessPLOverride).where(BusinessPLOverride.year == year)
        )).scalars().all()
    }
    for idx in range(12):
        o = overrides.get(idx + 1)
        if not o:
            continue
        if o.parts_cogs_override is not None:
            monthly_parts_cogs[idx] = float(o.parts_cogs_override)
        if o.labour_cogs_override is not None:
            monthly_labour_cogs[idx] = float(o.labour_cogs_override)

    return monthly_parts_cogs, monthly_labour_cogs
