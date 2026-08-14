"""
Adds Bucket.dept_assigned (+ _by/_at) — the real, dedicated flag for
"Production Manager's Assign Bucket action has run on this bucket",
replacing the fragile device-stage heuristic Bucket Allocation used to key
off. See models/bucket.py for the full reasoning.

Then backfills dept_assigned=True for buckets that were already assigned
under the old system, using the same StageMovement note pattern
assign_bucket() itself writes ("Bucket <number> assigned to <engineer>") as
the historical signal — so buckets genuinely already handed to an engineer
don't suddenly reappear in Bucket Allocation once this column exists.

Idempotent — safe to run more than once.

Usage: python migrate_bucket_dept_assigned.py
"""
import asyncio
from sqlalchemy import text
from database import engine

DDL_STATEMENTS = [
    "ALTER TABLE buckets ADD COLUMN IF NOT EXISTS dept_assigned BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE buckets ADD COLUMN IF NOT EXISTS dept_assigned_by VARCHAR(50)",
    "ALTER TABLE buckets ADD COLUMN IF NOT EXISTS dept_assigned_at TIMESTAMP",
]

BACKFILL_STATEMENT = """
UPDATE buckets
SET dept_assigned = true,
    dept_assigned_by = COALESCE(dept_assigned_by, 'backfill-2026-08-14'),
    dept_assigned_at = COALESCE(dept_assigned_at, now())
WHERE dept_assigned = false
  AND bucket_number IN (
    SELECT DISTINCT substring(sm.notes FROM 'Bucket (\\S+) assigned to')
    FROM stage_movements sm
    WHERE sm.notes LIKE 'Bucket % assigned to %'
  )
"""


async def main():
    for stmt in DDL_STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))

    print("Running backfill...")
    async with engine.begin() as conn:
        result = await conn.execute(text(BACKFILL_STATEMENT))
        print(f"Backfilled dept_assigned=true on {result.rowcount} bucket(s).")

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
