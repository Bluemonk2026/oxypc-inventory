"""
One-off data backfill — not a schema migration, no column changes.

Fixes Lots that were mapped to a GRN via the "Add Lot" flow BEFORE the
2026-08-14 fix that made grn_add_lot() also set Lot.grn_system_number.
Those Lots have a real GRNImport pointing at them (GRNImport.lot_id) but
Lot.grn_system_number is still NULL, so Product IQC's Lot Numbers tab
"GRN #" column and the Edit Lot page's "GRN System Number" field show
blank even though the mapping itself is correct.

Only touches Lots where grn_system_number IS NULL — never overwrites an
existing value. Idempotent — safe to run more than once.

Usage: python backfill_lot_grn_system_number.py
"""
import asyncio
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.grn_import import GRNImport


async def main():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Lot, GRNImport.grn_number)
            .join(GRNImport, GRNImport.lot_id == Lot.id)
            .where(Lot.grn_system_number.is_(None), GRNImport.is_deleted == False)
            .order_by(GRNImport.created_at.desc())
        )).all()

        # A Lot can have more than one mapped GRN (merge case) — keep the
        # first (most recent) match per lot, matching grn_add_lot's own
        # "most recent GRN wins" convention used elsewhere (get_lot_meta).
        seen = set()
        updated = 0
        for lot, grn_number in rows:
            if lot.id in seen or not grn_number:
                continue
            seen.add(lot.id)
            lot.grn_system_number = grn_number
            updated += 1
            print(f"  Lot {lot.lot_number} -> grn_system_number = {grn_number}")

        await db.commit()
        print(f"Backfilled {updated} lot(s).")


if __name__ == "__main__":
    asyncio.run(main())
