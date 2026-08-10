"""Put back the lot 80 Production sourcing request that a verification probe
committed a delete for on 2026-08-10.

Every field is reconstructed from records that still exist:
  id, file name        -> the PART_ESTIMATE_FILE_REMOVED audit entry
  qty, lot, timestamps -> the surviving part_estimates row for lot 80
  confirmed / closed   -> the PRODUCTION_SOURCING_CONFIRMED and SOURCING_CLOSED
                          audit entries from 2026-08-07

Not restorable: part_estimates.file_path, which was a random hex filename that
the old audit entry did not record. The costing itself is untouched (12 lines,
23 units, Rs 400,000), so re-running Generate Estimate -> Download & Attach on
lot 80 rebuilds an identical workbook.

    python restore_lot80_sourcing_request.py            # dry run
    python restore_lot80_sourcing_request.py --apply
"""
import asyncio, sys, uuid
from datetime import datetime
sys.path.insert(0, ".")
from sqlalchemy import select
from database import AsyncSessionLocal, engine
from models.part_estimate import PartEstimate
from models.part_request import PartSourcingRequest

APPLY = "--apply" in sys.argv

SR_ID = uuid.UUID("271880c9-c6fd-4bd0-9eb6-bd4be2132e7c")
LOT_NUMBER = "80"
FILE_NAME = "Part_Estimate_80_20260807-2306.xlsx"
DEAL_ID = "42a79a6b-4e9f-482a-b18f-9bfbf8987e06"
CONFIRMED_AT = datetime(2026, 8, 7, 23, 8, 23, 822971)
CLOSED_AT = datetime(2026, 8, 7, 23, 8, 56, 169705)


async def main():
    print("DB:", engine.url.host)
    print("MODE:", "APPLY" if APPLY else "DRY RUN — nothing written")
    async with AsyncSessionLocal() as db:
        est = (await db.execute(select(PartEstimate).where(
            PartEstimate.lot_number == LOT_NUMBER))).scalars().first()
        if not est:
            print("no part_estimates row for lot 80 — cannot restore")
            return

        exists = (await db.execute(select(PartSourcingRequest).where(
            PartSourcingRequest.id == SR_ID))).scalars().first()
        if exists:
            print("sourcing request already present — nothing to do")
            return

        fields = dict(
            id=SR_ID,
            source="production",
            part_code=None,
            part_name=f"Request for {est.lot_number}",
            qty_requested=est.total_qty,
            qty_sourced=1,
            raised_by=est.created_by,
            status="closed",
            source_deal_id=DEAL_ID,
            lot_id=est.lot_id,
            lot_number=est.lot_number,
            estimate_id=est.id,
            confirmed=True,
            confirmed_by="admin",
            confirmed_at=CONFIRMED_AT,
            closed_by="admin",
            closed_at=CLOSED_AT,
            created_at=est.created_at,
        )
        print("\nwould restore part_sourcing_requests row:")
        for k, v in fields.items():
            print(f"    {k:<16} {v}")
        print(f"\nand set part_estimates.file_name = {FILE_NAME!r}"
              f"  (file_path stays NULL — the stored filename was not recorded)")

        if APPLY:
            db.add(PartSourcingRequest(**fields))
            est.file_name = FILE_NAME
            await db.commit()
            print("\nrestored.")
        else:
            print("\ndry run — re-run with --apply to write.")

asyncio.run(main())
