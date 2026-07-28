"""One-shot migration for the 2026-07-28 bug-fix batch.

1. grn_imports: persist the Validate-GRN modal fields (received qty, GRN
   reference, discrepancy notes) that were previously accepted then discarded.
2. master_data: replace the qc_failure_reason option set with the approved
   Hardware / Software / Cosmetic values (old values are deactivated, not
   deleted — soft-delete policy).

Run: python migrate_fixes_20260728.py
"""
import asyncio
import uuid
from sqlalchemy import text
from database import engine

DDL = [
    "ALTER TABLE grn_imports ADD COLUMN IF NOT EXISTS received_qty INTEGER",
    "ALTER TABLE grn_imports ADD COLUMN IF NOT EXISTS validation_ref VARCHAR(100)",
    "ALTER TABLE grn_imports ADD COLUMN IF NOT EXISTS validation_notes VARCHAR(500)",
    "ALTER TABLE iqc_inspections ADD COLUMN IF NOT EXISTS touch_screen VARCHAR(15)",
]

NEW_FAILURE_REASONS = ["Hardware", "Software", "Cosmetic"]


async def main():
    async with engine.begin() as conn:
        for stmt in DDL:
            print(f"Running: {stmt}")
            await conn.execute(text(stmt))

        print("Deactivating old qc_failure_reason values…")
        await conn.execute(text(
            "UPDATE master_data SET is_active = false "
            "WHERE category = 'qc_failure_reason' "
            "AND value NOT IN ('Hardware','Software','Cosmetic')"
        ))
        for i, v in enumerate(NEW_FAILURE_REASONS):
            # :val appears twice with different inferred types under asyncpg
            # (text vs varchar) — pass it as two parameters with explicit casts.
            await conn.execute(text(
                "INSERT INTO master_data (id, category, value, display_order, is_active, created_at) "
                "SELECT :id, 'qc_failure_reason', CAST(:val AS VARCHAR(200)), :ord, true, NOW() "
                "WHERE NOT EXISTS (SELECT 1 FROM master_data "
                "  WHERE category = 'qc_failure_reason' AND value = CAST(:val2 AS VARCHAR(200)))"
            ), {"id": str(uuid.uuid4()), "val": v, "val2": v, "ord": i})
            # Re-activate in case the value existed but was inactive
            await conn.execute(text(
                "UPDATE master_data SET is_active = true "
                "WHERE category = 'qc_failure_reason' AND value = :val"
            ), {"val": v})
        print("qc_failure_reason now: Hardware / Software / Cosmetic")
    print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(main())
