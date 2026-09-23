"""
OxyPC Inventory — Add designation + reports_to columns to users.

Idempotent — safe to run more than once.
Usage: python migrate_user_designation_reports_to.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS designation VARCHAR(100) NULL",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS reports_to VARCHAR(50) NULL",
]


async def main():
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt}")
            await conn.execute(text(stmt))
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
