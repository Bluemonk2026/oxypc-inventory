"""
OxyPC Inventory — Dealer Call Purchase Quantity Migration
Adds `purchase_quantity` to dealer_calls, distinct from the existing `qty`
(Required Quantity) column, for the Dealer Call Log form.

Usage: python migrate_dealer_purchase_qty.py
Backup taken first: backups/pre_dealer_purchase_qty_<timestamp>.dump
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE dealer_calls ADD COLUMN IF NOT EXISTS purchase_quantity INTEGER NULL",
]


async def main():
    for stmt in STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
