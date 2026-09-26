"""One-off backfill: populate StockTransfer.received_by on historical rows
left blank by the same bug fixed in routers/transfers.py on 2026-09-26 (the
"Received By" form field was a hidden, unused input, always submitted
blank).

WorkOrder.source_transfer_id is a direct foreign key back to the
StockTransfer row that created it (set by _move_devices_bulk and the main
device-transfer path whenever a device is assigned to an employee) — an
exact 1:1 link, not a fuzzy device/timestamp match. Confirmed against real
data before writing this: no StockTransfer row has more than one matching
WorkOrder via this key. received_by is set to WorkOrder.assigned_name,
falling back to assigned_username, matching the exact convention
routers/transfers.py itself uses (assigned_user.full_name or
assigned_user.username).

Rows with no matching WorkOrder (~1% locally — "transfer_to_trc" and
"Inventory to Showroom" moves, which never create a WorkOrder since they
aren't an engineer-repair-stage assignment) are left untouched: there is no
reliable source to recover an assignee from, so they stay NULL rather than
guessing.

Safe to re-run — only touches rows where received_by IS NULL or ''.

Run on the server: cd /opt/oxypc && ./venv/bin/python3 backfill_transfer_received_by.py
"""
import asyncio

from sqlalchemy import select, or_

from database import AsyncSessionLocal
from models.stock_transfer import StockTransfer
from models.work_order import WorkOrder


async def main():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(StockTransfer, WorkOrder)
            .join(WorkOrder, WorkOrder.source_transfer_id == StockTransfer.id)
            .where(or_(StockTransfer.received_by.is_(None), StockTransfer.received_by == ""))
        )).all()

        print(f"{len(rows)} row(s) with blank received_by have a matching WorkOrder.")
        if not rows:
            return

        updated = 0
        skipped_no_name = 0
        for transfer, wo in rows:
            name = wo.assigned_name or wo.assigned_username
            if not name:
                skipped_no_name += 1
                continue
            transfer.received_by = name
            updated += 1

        await db.commit()
        print(f"Backfilled {updated} row(s) from their WorkOrder's assigned employee.")
        if skipped_no_name:
            print(f"Skipped {skipped_no_name} row(s) — matching WorkOrder had no assigned_name/assigned_username either.")


if __name__ == "__main__":
    asyncio.run(main())
