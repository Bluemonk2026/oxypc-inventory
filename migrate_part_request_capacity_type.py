"""One-shot migration: add part_capacity/part_type columns to part_requests
for the New Part Request / Replace Request modal's new fields.

Run: python migrate_part_request_capacity_type.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE part_requests ADD COLUMN IF NOT EXISTS part_capacity VARCHAR(50)",
    "ALTER TABLE part_requests ADD COLUMN IF NOT EXISTS part_type VARCHAR(50)",
]


async def main():
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt}")
            await conn.execute(text(stmt))
    print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(main())
