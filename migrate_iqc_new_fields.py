"""One-shot migration: add previously-dead IQC form fields (cover_ram/dvd/storage,
hinge_condition/cover, touchpad_logicboard, storage_health_pct, fan_sound_dba,
fan_working) as real columns on iqc_inspections.

Run: python migrate_iqc_new_fields.py
Backup taken first: backups/pre_iqc_new_fields_<timestamp>.dump
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE iqc_inspections ADD COLUMN IF NOT EXISTS cover_ram VARCHAR(5) NULL",
    "ALTER TABLE iqc_inspections ADD COLUMN IF NOT EXISTS cover_dvd VARCHAR(5) NULL",
    "ALTER TABLE iqc_inspections ADD COLUMN IF NOT EXISTS cover_storage VARCHAR(5) NULL",
    "ALTER TABLE iqc_inspections ADD COLUMN IF NOT EXISTS hinge_condition VARCHAR(10) NULL",
    "ALTER TABLE iqc_inspections ADD COLUMN IF NOT EXISTS hinge_cover VARCHAR(10) NULL",
    "ALTER TABLE iqc_inspections ADD COLUMN IF NOT EXISTS touchpad_logicboard VARCHAR(10) NULL",
    "ALTER TABLE iqc_inspections ADD COLUMN IF NOT EXISTS storage_health_pct INTEGER NULL",
    "ALTER TABLE iqc_inspections ADD COLUMN IF NOT EXISTS fan_sound_dba INTEGER NULL",
    "ALTER TABLE iqc_inspections ADD COLUMN IF NOT EXISTS fan_working VARCHAR(5) NULL",
]


async def main():
    for stmt in STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
