from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from utils.timezone import app_now
from models.lot import Lot

UNASSIGNED_LOT_NUMBER = "UNASSIGNED"


async def build_lot_stats(db: AsyncSession, lots: list) -> list:
    """Attach registered-device and sold counts to each Lot.

    Two grouped queries regardless of how many lots are passed — never one per
    lot. The app server and the database sit on opposite sides of the Pacific,
    so a per-row query loop here would cost a round trip per lot.

    Returns [{"lot": Lot, "devices": int, "sold": int}, …] in the order given.
    """
    from models.device import Device, DeviceStage

    lot_ids = [lot.id for lot in lots]
    dev_counts: dict = {}
    sold_counts: dict = {}
    if lot_ids:
        dev_counts = dict((await db.execute(
            select(Device.lot_id, func.count(Device.id))
            .where(Device.lot_id.in_(lot_ids), Device.is_active == True)
            .group_by(Device.lot_id)
        )).fetchall())
        sold_counts = dict((await db.execute(
            select(Device.lot_id, func.count(Device.id))
            .where(Device.lot_id.in_(lot_ids), Device.current_stage == DeviceStage.sold)
            .group_by(Device.lot_id)
        )).fetchall())
    return [
        {"lot": lot, "devices": dev_counts.get(lot.id, 0), "sold": sold_counts.get(lot.id, 0)}
        for lot in lots
    ]


async def get_or_create_unassigned_lot(db: AsyncSession) -> Lot:
    """Return the system 'UNASSIGNED' Lot, creating it if missing.

    Device.lot_id is a NOT NULL FK and dozens of queries app-wide INNER JOIN
    Device to Lot, so making the Lot field optional on IQC Entry / Device Edit
    is implemented by silently attaching un-lotted devices to this sentinel
    Lot rather than allowing a NULL FK.

    Check-then-insert has a real race window the first time this ever runs
    (or any time the row has been removed): two IQC Entry submissions with no
    Lot selected, close enough together, can both see "missing" and both try
    to INSERT lot_number='UNASSIGNED', which is UNIQUE — the loser's flush()
    raised an unhandled IntegrityError that surfaced to that user as a raw
    500 (observed: the row's own created_at shows exactly this happening in
    production). Recover by re-reading — the winner's row is what we want
    anyway.
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
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await db.execute(select(Lot).where(Lot.lot_number == UNASSIGNED_LOT_NUMBER))
        lot = existing.scalar_one_or_none()
        if not lot:
            raise  # something other than the expected race — don't swallow it
    return lot
