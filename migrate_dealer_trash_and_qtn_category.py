"""
OxyPC Inventory — Dealer soft-delete + Quotation PO-Category migration.

Additive, non-destructive. Adds:
  - dealers.trashed_at (TIMESTAMP NULL), dealers.trashed_by (VARCHAR(50) NULL)
    → soft-delete / Trash pattern for dealers (Item B).
  - dealer_quotation_items.po_category (VARCHAR(100) NULL)
    → PO Category per quotation line item (Item C).

Usage: python migrate_dealer_trash_and_qtn_category.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE dealers ADD COLUMN IF NOT EXISTS trashed_at TIMESTAMP NULL",
    "ALTER TABLE dealers ADD COLUMN IF NOT EXISTS trashed_by VARCHAR(50) NULL",
    "ALTER TABLE dealer_quotation_items ADD COLUMN IF NOT EXISTS po_category VARCHAR(100) NULL",
]


async def main():
    for stmt in STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
