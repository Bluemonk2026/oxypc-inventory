"""
OxyPC Inventory — Enforce uniqueness on work_orders.work_id.

Root cause fix for "duplicate WorkID for L3/L4" (found 2026-09-23):
_gen_prefixed_work_id() in routers/repair.py computed the "next" WorkID with
a plain count-then-check query and no locking, so two concurrent L1/L2 -> L3/L4
requests could compute and commit the identical WorkID for two different
devices. The app-side fix (routers/repair.py's _create_work_order_with_unique_id,
a SAVEPOINT + retry-on-IntegrityError) only works if the DB actually rejects a
duplicate — but work_orders.work_id has NO unique constraint on the live table
today (the SQLAlchemy model declares unique=True, but the table predates that
and db_validator's create_all only creates *missing* tables, never retrofits
constraints onto existing ones). This script is the other half of the fix.

Steps (idempotent, safe to run more than once):
  1. Find any existing duplicate work_id groups.
  2. For each group, keep the oldest row (min created_at, tie-broken by id)
     unchanged; regenerate a fresh, verified-unique work_id for every other
     row in the group, preserving its original prefix and digit width.
  3. Add a UNIQUE constraint on work_orders.work_id (skipped if already present).

Usage: python migrate_work_orders_unique_constraint.py
"""
import asyncio
import re
from collections import defaultdict
from sqlalchemy import text
from database import engine

CONSTRAINT_NAME = "uq_work_orders_work_id"


def _split_prefix_digits(work_id: str):
    m = re.match(r"^([A-Za-z]*-?)(\d+)$", work_id or "")
    if not m:
        return work_id or "", "", 0
    prefix, digits = m.group(1), m.group(2)
    return prefix, digits, len(digits)


async def main():
    async with engine.begin() as conn:
        dupe_rows = (await conn.execute(text(
            "SELECT work_id, count(*) c FROM work_orders GROUP BY work_id HAVING count(*) > 1"
        ))).all()

        if not dupe_rows:
            print("[1/2] No duplicate work_id values found.")
        else:
            print(f"[1/2] Found {len(dupe_rows)} duplicate work_id value(s) — deduplicating...")
            all_ids_result = await conn.execute(text("SELECT work_id FROM work_orders"))
            existing = {r[0] for r in all_ids_result.all()}

            for work_id, count in dupe_rows:
                rows = (await conn.execute(text(
                    "SELECT id FROM work_orders WHERE work_id = :wid "
                    "ORDER BY created_at ASC NULLS LAST, id ASC"
                ), {"wid": work_id})).all()
                keeper, dupes = rows[0][0], rows[1:]
                prefix, digits, width = _split_prefix_digits(work_id)
                # Find the current max numeric suffix used under this prefix so
                # replacements never collide with legitimately-allocated IDs.
                same_prefix = [wid for wid in existing if wid.startswith(prefix)]
                max_n = 0
                for wid in same_prefix:
                    _, d, _ = _split_prefix_digits(wid)
                    if d.isdigit():
                        max_n = max(max_n, int(d))
                for (dupe_id,) in dupes:
                    max_n += 1
                    new_wid = f"{prefix}{str(max_n).zfill(width)}"
                    while new_wid in existing:
                        max_n += 1
                        new_wid = f"{prefix}{str(max_n).zfill(width)}"
                    await conn.execute(text(
                        "UPDATE work_orders SET work_id = :new_wid WHERE id = :id"
                    ), {"new_wid": new_wid, "id": dupe_id})
                    existing.add(new_wid)
                    print(f"    {work_id} -> kept on {keeper}, renamed duplicate {dupe_id} to {new_wid}")

        has_constraint = (await conn.execute(text(
            "SELECT 1 FROM pg_constraint WHERE conrelid = 'work_orders'::regclass "
            "AND conname = :name"
        ), {"name": CONSTRAINT_NAME})).scalar()
        if has_constraint:
            print(f"[2/2] Constraint {CONSTRAINT_NAME} already present.")
        else:
            print(f"[2/2] Adding UNIQUE constraint {CONSTRAINT_NAME}...")
            await conn.execute(text(
                f"ALTER TABLE work_orders ADD CONSTRAINT {CONSTRAINT_NAME} UNIQUE (work_id)"
            ))
            print("    done.")

    print("\nMigration complete.")


if __name__ == "__main__":
    asyncio.run(main())
