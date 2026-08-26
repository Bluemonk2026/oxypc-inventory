"""Shared helper for fetching admin-managed Master Data dropdown options.

Two ways to use this in a route/template:

1. Router-side, when you need the list in Python (e.g. to validate a submitted
   value): `await master_values(db, "payment_mode")`.
2. Template-side, via the Jinja global `master_options('payment_mode')` —
   backed by an in-memory cache (mirrors the role-permissions cache pattern in
   models/role_permissions.py) so templates can pull dropdown options directly
   without every router call site having to fetch and pass them explicitly.
   Warmed at startup and refreshed whenever admin adds/edits/toggles/deletes
   a value on /admin/master.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.master import MasterData

# category -> [values...], active only, in display order. See module docstring.
_MASTER_CACHE: dict = {}


async def master_values(db: AsyncSession, category: str) -> list:
    """Return active option values for a Master Data category, in display order."""
    result = await db.execute(
        select(MasterData.value)
        .where(MasterData.category == category, MasterData.is_active == True)
        .order_by(MasterData.display_order, MasterData.value)
    )
    return [row[0] for row in result.all()]


# Used when the 'entity' Master Data category has not been populated on a given
# database — without it, an unconfigured install shows an empty Entity dropdown
# and rejects every entity on bulk upload.
ENTITY_FALLBACK = ["Deshwal", "OxyPC Computers", "Renew Circuits"]


async def entity_values(db: AsyncSession) -> list:
    """Active Entity options, falling back to the three known entities when the
    category has not been configured. Single source of truth for the Entity
    dropdown on Entity Movement, the All Inventory filter, and bulk-upload
    validation — these previously each carried their own copy of the fallback
    list, so adding a fourth entity meant finding every one of them."""
    return await master_values(db, "entity") or list(ENTITY_FALLBACK)


async def report_year_values(db: AsyncSession) -> list:
    """Active Year options for the Dashboard's Year filter and Business P&L's
    year tabs — single source so the two never disagree on which years are
    offered. Falls back to a rolling 5-year window (current year ± 2) when the
    'report_year' category hasn't been configured yet, same fallback pattern
    as entity_values() above."""
    vals = await master_values(db, "report_year")
    if vals:
        return vals
    from utils.timezone import app_now
    y = app_now().year
    return [str(v) for v in range(y - 2, y + 3)]


async def refresh_master_cache(db: AsyncSession) -> None:
    """Reload the full in-memory cache from DB. Call at startup and after any
    admin add/edit/toggle/delete on /admin/master."""
    result = await db.execute(
        select(MasterData.category, MasterData.value)
        .where(MasterData.is_active == True)
        .order_by(MasterData.category, MasterData.display_order, MasterData.value)
    )
    fresh: dict = {}
    for category, value in result.all():
        fresh.setdefault(category, []).append(value)
    _MASTER_CACHE.clear()
    _MASTER_CACHE.update(fresh)


def master_options(category: str) -> list:
    """Synchronous Jinja-global accessor — reads the warm cache, never hits the DB."""
    return _MASTER_CACHE.get(category, [])
