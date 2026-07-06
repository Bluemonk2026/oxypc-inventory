"""One-shot migration: add monthly_quantity column to dealer_calls.

Run: python migrate_dealer_call_monthly_qty.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE dealer_calls ADD COLUMN IF NOT EXISTS monthly_quantity INTEGER NULL",
]


async def main():
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt}")
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
