"""One-off backfill: promote IQC-stage tags that already carry a GRN to Stock Inward.

Before commit 6e12e8e, entering a GRN on the Add IQC form stored the number but
left the tag at Stage IQC. Because GRN in TRC's pending list selects IQC-stage
devices with NO GRN, those tags were invisible to the mapping flow and had no
route forward. This moves them the way the app now does at entry.

Matches the live behaviour exactly: closes the open IQC stage_movement with
exited_at, adds an iqc -> stock_in movement, and leaves `entity` alone (the
GRN-mapping flow force-sets OxyPC Computers; entry-with-GRN does not, and that
difference is deliberate until someone decides which is right).

    python backfill_iqc_grn_to_stock_in.py            # dry run, changes nothing
    python backfill_iqc_grn_to_stock_in.py --apply    # commit the change

Writes the affected barcodes to backfill_iqc_grn_<host>.txt so the change can be
reversed against a known list.
"""
import asyncio
import sys
from datetime import datetime

from sqlalchemy import select, or_

from database import AsyncSessionLocal, engine
from models.device import Device, DeviceStage, StageMovement
from utils.timezone import app_now

APPLY = "--apply" in sys.argv
ACTOR = "backfill:iqc-grn-to-stock-in"


async def main():
    host = engine.url.host or "local"
    print(f"DB: {host}   mode: {'APPLY' if APPLY else 'DRY RUN'}")

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Device).where(
                Device.current_stage == DeviceStage.iqc,
                Device.grn_number.isnot(None),
                Device.grn_number != "",
                Device.is_active == True,        # noqa: E712
                Device.is_trashed == False,      # noqa: E712
            ).order_by(Device.barcode)
        )).scalars().all()

        print(f"tags at Stage IQC carrying a GRN: {len(rows)}")
        if not rows:
            return

        for d in rows[:10]:
            print(f"   {d.barcode:<22} GRN {d.grn_number:<16} entity={d.entity}")
        if len(rows) > 10:
            print(f"   … and {len(rows) - 10} more")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        record = f"backfill_iqc_grn_{host.split('.')[0]}_{stamp}.txt"
        with open(record, "w", encoding="utf-8") as fh:
            for d in rows:
                fh.write(f"{d.barcode}\t{d.grn_number}\t{d.entity}\n")
        print(f"affected barcodes written to {record}")

        if not APPLY:
            print("\nDRY RUN — nothing changed. Re-run with --apply to commit.")
            return

        now = app_now()
        moved = 0
        for d in rows:
            prev = (await db.execute(
                select(StageMovement).where(
                    StageMovement.device_id == d.id,
                    StageMovement.to_stage == DeviceStage.iqc,
                    StageMovement.exited_at.is_(None),
                ).order_by(StageMovement.moved_at.desc())
            )).scalars().first()
            if prev:
                prev.exited_at = now
            db.add(StageMovement(
                device_id=d.id, from_stage=DeviceStage.iqc,
                to_stage=DeviceStage.stock_in, moved_by=ACTOR,
                notes=f"Backfill — GRN {d.grn_number} was already recorded at IQC entry",
            ))
            d.current_stage = DeviceStage.stock_in
            d.updated_at = now
            moved += 1

        await db.commit()
        print(f"\nmoved {moved} tag(s) to Stock Inward")

        left = (await db.execute(
            select(Device).where(
                Device.current_stage == DeviceStage.iqc,
                Device.grn_number.isnot(None), Device.grn_number != "",
                Device.is_active == True, Device.is_trashed == False,  # noqa: E712
            )
        )).scalars().all()
        print(f"remaining IQC tags with a GRN: {len(left)}")


asyncio.run(main())
