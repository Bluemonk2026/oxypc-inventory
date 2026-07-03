"""One-shot migration: add reupload_requested fields to part_sourcing_requests.

Run: python migrate_sourcing_reupload.py
Backup taken first: backups/pre_sourcing_reupload_<timestamp>.dump
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE part_sourcing_requests ADD COLUMN IF NOT EXISTS reupload_requested BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE part_sourcing_requests ADD COLUMN IF NOT EXISTS reupload_requested_at TIMESTAMP NULL",
    "ALTER TABLE part_sourcing_requests ADD COLUMN IF NOT EXISTS reupload_requested_by VARCHAR(50) NULL",
]


async def main():
    for stmt in STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
