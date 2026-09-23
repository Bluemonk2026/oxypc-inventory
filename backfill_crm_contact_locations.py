"""
OxyPC Inventory — Backfill crm_contact_locations from existing CRM contacts.

For every CRM contact that has no Location rows yet, creates ONE default
Location from the contact's existing flat address/city/state/email fields
(even if those are blank — still creates the row so the Locations UI has
something to show), then re-parents that contact's existing
crm_contact_numbers rows (currently linked via the legacy contact_id column)
onto the new default Location via the new location_id column.

IDEMPOTENT: skips any contact that already has >=1 Location row, so it is
safe to run multiple times and on both dev and production.

Prerequisite: crm_contact_locations table and crm_contact_numbers.location_id
column must already exist. The app creates/adds these automatically at
startup (db_validator), so run this AFTER the app has been restarted /
redeployed with the new models.

Usage: python backfill_crm_contact_locations.py
"""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from config import DATABASE_URL


CREATE_DEFAULT_LOCATIONS_SQL = """
INSERT INTO crm_contact_locations (id, contact_id, contact_email, address, city, state, sort_order, created_at)
SELECT gen_random_uuid(), c.id, c.email, c.address, c.city, c.state, 0, now()
FROM crm_contacts c
WHERE NOT EXISTS (
    SELECT 1 FROM crm_contact_locations l WHERE l.contact_id = c.id
)
"""

REPARENT_CONTACT_NUMBERS_SQL = """
UPDATE crm_contact_numbers n
SET location_id = l.id
FROM crm_contact_locations l
WHERE n.contact_id = l.contact_id
  AND n.location_id IS NULL
"""


async def run():
    print("=" * 55)
    print("  OxyPC — Backfill crm_contact_locations")
    print("=" * 55)

    engine = create_async_engine(DATABASE_URL, echo=False)

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            exists = (await conn.execute(text(
                "SELECT to_regclass('public.crm_contact_locations')"
            ))).scalar()
            has_col = (await conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='crm_contact_numbers' AND column_name='location_id'"
            ))).scalar()
        if not exists or not has_col:
            print("\nERROR: crm_contact_locations table or crm_contact_numbers.location_id column missing.")
            print("  Restart/redeploy the app first (startup auto-creates them), then re-run.")
            await engine.dispose()
            sys.exit(1)
        print("  DB connection + schema: OK\n")
    except Exception as e:
        print(f"\nERROR: Cannot connect to database.\n  {e}")
        await engine.dispose()
        sys.exit(1)

    async with engine.begin() as conn:
        print("[1/2] Creating one default Location per contact missing rows...")
        result = await conn.execute(text(CREATE_DEFAULT_LOCATIONS_SQL))
        print(f"    locations created: {result.rowcount}")

        print("[2/2] Re-parenting existing Contact Numbers onto default Locations...")
        result = await conn.execute(text(REPARENT_CONTACT_NUMBERS_SQL))
        print(f"    contact numbers re-parented: {result.rowcount}")

    await engine.dispose()
    print("\nBackfill complete.")


if __name__ == "__main__":
    asyncio.run(run())
