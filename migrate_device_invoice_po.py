"""One-shot migration: add invoice_number and po_number columns to devices.

Run: python migrate_device_invoice_po.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS invoice_number VARCHAR(100) NULL",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS po_number VARCHAR(100) NULL",
]

async def main():
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt}")
            await conn.execute(text(stmt))
    print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(main())
