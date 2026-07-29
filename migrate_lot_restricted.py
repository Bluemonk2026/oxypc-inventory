"""One-shot migration: Lot.is_restricted.

Partner catalog lots are visible to every partner account by default. A lot
flagged Restricted is limited to the dealers explicitly granted it in
lot_dealer_visibility.

Run: python migrate_lot_restricted.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE lots ADD COLUMN IF NOT EXISTS is_restricted BOOLEAN NOT NULL DEFAULT false",
]


async def main():
    for stmt in STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
