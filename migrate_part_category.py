"""One-shot migration: add part_category + request_type to part_requests.

Run: python migrate_part_category.py
Backup taken first: backups/pre_part_category_<timestamp>.dump
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE part_requests ADD COLUMN IF NOT EXISTS part_category VARCHAR(100) NULL",
    "ALTER TABLE part_requests ADD COLUMN IF NOT EXISTS request_type VARCHAR(10) NOT NULL DEFAULT 'new'",
]


async def main():
    for stmt in STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
