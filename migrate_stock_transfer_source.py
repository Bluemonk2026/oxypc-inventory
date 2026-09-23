"""
Adds StockTransfer.source — records which endpoint created each row, so
/transfers can show only genuine /transfers/new submissions instead of every
internal auto-write (Final QC Fail routing, bucket/engineer assignment,
Stock Validate reassignment, Stock In bulk transfer) that happened to reuse
the same transfer_type ("transfer_to_trc") as a real transfer. See
models/stock_transfer.py's own comment on the column.

Backfills existing rows from the exact notes/transfer_type patterns each
write site has always used (routers/buckets.py, routers/stock.py) — anything
that doesn't match one of those known internal patterns is assumed genuine
(source='transfers_new'), which is correct for every value currently in the
table (verified: transfer_to_trc/reassign are the only two values any
non-/transfers/new write site has ever produced; every other transfer_type,
including legacy 'trc_to_showroom'/'showroom_to_trc'/'internal' values with
no current writer, only ever came from some version of /transfers/new).

Idempotent — safe to run more than once.

Usage: python migrate_stock_transfer_source.py
"""
import asyncio
from sqlalchemy import text
from database import engine

DDL_STATEMENTS = [
    "ALTER TABLE stock_transfers ADD COLUMN IF NOT EXISTS source VARCHAR(30)",
]

# Order matters: most specific pattern first, catch-all last.
BACKFILL_STATEMENTS = [
    ("department_assignment", """
        UPDATE stock_transfers
        SET source = 'department_assignment'
        WHERE source IS NULL
          AND (notes LIKE 'Final QC Fail — moved to%'
               OR notes LIKE 'Assigned via Bucket %'
               OR notes LIKE 'Assigned via Production Manager — %'
               OR notes LIKE 'Bulk assigned via Production Manager — %')
    """),
    ("stock_reassign", """
        UPDATE stock_transfers
        SET source = 'stock_reassign'
        WHERE source IS NULL
          AND (notes = 'Reassigned via Stock Validate' OR transfer_type = 'reassign')
    """),
    ("stock_bulk_transfer", """
        UPDATE stock_transfers
        SET source = 'stock_bulk_transfer'
        WHERE source IS NULL AND notes = 'Bulk stock transfer'
    """),
    ("transfers_new", """
        UPDATE stock_transfers
        SET source = 'transfers_new'
        WHERE source IS NULL
    """),
]


async def main():
    for stmt in DDL_STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))

    for label, stmt in BACKFILL_STATEMENTS:
        async with engine.begin() as conn:
            result = await conn.execute(text(stmt))
            print(f"Backfilled source='{label}' on {result.rowcount} row(s).")

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
