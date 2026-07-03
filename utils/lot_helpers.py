from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from utils.timezone import app_now
from models.lot import Lot

UNASSIGNED_LOT_NUMBER = "UNASSIGNED"


async def get_or_create_unassigned_lot(db: AsyncSession) -> Lot:
    """Return the system 'UNASSIGNED' Lot, creating it if missing.

    Device.lot_id is a NOT NULL FK and dozens of queries app-wide INNER JOIN
    Device to Lot, so making the Lot field optional on IQC Entry / Device Edit
    is implemented by silently attaching un-lotted devices to this sentinel
    Lot rather than allowing a NULL FK.
    """
    existing = await db.execute(select(Lot).where(Lot.lot_number == UNASSIGNED_LOT_NUMBER))
    lot = existing.scalar_one_or_none()
    if lot:
        return lot
    lot = Lot(
        lot_number=UNASSIGNED_LOT_NUMBER,
        supplier_name="Unassigned",
        buying_price=0,
        qty=0,
        purchase_date=app_now(),
    )
    db.add(lot)
    await db.flush()
    return lot
