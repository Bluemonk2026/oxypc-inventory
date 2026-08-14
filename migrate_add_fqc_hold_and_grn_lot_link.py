"""
OxyPC Inventory — Final QC hold-stage + GRN/Lot linking migration

Adds:
  - DeviceStage enum values 'final_qc_pass_hold' and 'final_qc_fail_hold'
  - devices.fqc_failure_reason (TEXT, nullable)
  - devices.fqc_pass_notes (TEXT, nullable)
  - grn_imports.lot_id (UUID, FK -> lots.id, nullable, indexed)
  - grn_imports.purchase_date (DATE, nullable)
  - grn_imports.grn_date (DATE, nullable)
  - grn_imports.po_number (VARCHAR(50), nullable)
  - grn_imports.vehicle_number (VARCHAR(50), nullable)
  - grn_imports.e_way_bill (VARCHAR(50), nullable)
  - grn_imports.notes (TEXT, nullable)

Idempotent — safe to run more than once. Each statement runs in its own
transaction (matches migrate_fix_prod_uuid_drift.py's convention) so that
the ALTER TYPE ... ADD VALUE statements commit before anything in this
same run could reference the new enum values.

Usage: python migrate_add_fqc_hold_and_grn_lot_link.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TYPE devicestage ADD VALUE IF NOT EXISTS 'final_qc_pass_hold'",
    "ALTER TYPE devicestage ADD VALUE IF NOT EXISTS 'final_qc_fail_hold'",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS fqc_failure_reason TEXT",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS fqc_pass_notes TEXT",
    "ALTER TABLE grn_imports ADD COLUMN IF NOT EXISTS lot_id UUID REFERENCES lots(id)",
    "CREATE INDEX IF NOT EXISTS ix_grn_imports_lot_id ON grn_imports (lot_id)",
    "ALTER TABLE grn_imports ADD COLUMN IF NOT EXISTS purchase_date DATE",
    "ALTER TABLE grn_imports ADD COLUMN IF NOT EXISTS grn_date DATE",
    "ALTER TABLE grn_imports ADD COLUMN IF NOT EXISTS po_number VARCHAR(50)",
    "ALTER TABLE grn_imports ADD COLUMN IF NOT EXISTS vehicle_number VARCHAR(50)",
    "ALTER TABLE grn_imports ADD COLUMN IF NOT EXISTS e_way_bill VARCHAR(50)",
    "ALTER TABLE grn_imports ADD COLUMN IF NOT EXISTS notes TEXT",
]


async def main():
    for stmt in STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
