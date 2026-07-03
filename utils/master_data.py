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
