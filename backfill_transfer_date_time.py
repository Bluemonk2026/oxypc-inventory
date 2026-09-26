"""One-off backfill: fix StockTransfer.transfer_date rows stuck at midnight.

Every transfer created before the 2026-09-26 fix went through a bug where
the "Transfer Date" form field (a readonly, date-only input pre-filled with
today's date) was parsed via datetime.strptime(transfer_date, "%Y-%m-%d")
and stored directly, discarding the time of day — so /transfers always
showed 00:00 regardless of when the transfer actually happened. Fixed going
forward in routers/transfers.py (transfer_date now always uses app_now()).

StockTransfer.created_at was never touched by this bug — it always used its
own column default (app_now()), set independently of the buggy transfer_date
assignment — and reliably holds the true creation timestamp. Confirmed
against real data before writing this: 0 rows have both fields at midnight,
and 0 rows have transfer_date and created_at on different calendar dates.
Backfill copies created_at onto transfer_date wherever transfer_date's time
is exactly midnight.

Safe to re-run — only touches rows where transfer_date's time is midnight,
so already-backfilled (or never-buggy) rows are a no-op.

Run on the server: cd /opt/oxypc && ./venv/bin/python3 backfill_transfer_date_time.py
"""
import asyncio

from sqlalchemy import select, func

from database import AsyncSessionLocal
from models.stock_transfer import StockTransfer


async def main():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(StockTransfer).where(
                StockTransfer.transfer_date == func.date_trunc('day', StockTransfer.transfer_date),
                StockTransfer.created_at.isnot(None),
            )
        )).scalars().all()

        print(f"{len(rows)} row(s) have transfer_date stuck at midnight.")
        if not rows:
            return

        updated = 0
        skipped_no_real_time = 0
        for row in rows:
            if row.created_at.time().replace(microsecond=0) == row.transfer_date.time():
                skipped_no_real_time += 1
                continue
            row.transfer_date = row.created_at
            updated += 1

        await db.commit()
        print(f"Backfilled {updated} row(s) from created_at.")
        if skipped_no_real_time:
            print(f"Skipped {skipped_no_real_time} row(s) — created_at was also midnight, no real time to recover.")


if __name__ == "__main__":
    asyncio.run(main())
