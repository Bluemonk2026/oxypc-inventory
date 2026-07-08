"""
OxyPC Inventory — Backfill crm_contact_numbers from existing contact phones.

For every CRM contact that has a primary `phone` but no Contact Number rows yet,
insert one Contact Number row (person = contact_person, phone = phone) so the new
"Contacts" count/tooltip on the list page is populated for pre-existing contacts.

IDEMPOTENT: skips any contact that already has ≥1 contact-number row, so it is
safe to run multiple times and on both dev and production.

Prerequisite: the crm_contact_numbers table must already exist. The app creates
it automatically at startup (db_validator), so run this AFTER the app has been
restarted / redeployed with the new model.

Usage: python backfill_contact_numbers.py
"""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from config import DATABASE_URL


BACKFILL_SQL = """
INSERT INTO crm_contact_numbers (id, contact_id, person_name, phone, sort_order, created_at)
SELECT gen_random_uuid(), c.id, c.contact_person, c.phone, 0, now()
FROM crm_contacts c
WHERE c.phone IS NOT NULL AND c.phone <> ''
  AND NOT EXISTS (
    SELECT 1 FROM crm_contact_numbers n WHERE n.contact_id = c.id
  )
"""


async def run():
    print("=" * 55)
    print("  OxyPC — Backfill crm_contact_numbers")
    print("=" * 55)

    engine = create_async_engine(DATABASE_URL, echo=False)

    # Verify DB + table presence up front with a clear message.
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            exists = (await conn.execute(text(
                "SELECT to_regclass('public.crm_contact_numbers')"
            ))).scalar()
        if not exists:
            print("\nERROR: table crm_contact_numbers does not exist yet.")
            print("  Restart/redeploy the app first (startup auto-creates it), then re-run.")
            await engine.dispose()
            sys.exit(1)
        print("  DB connection + table: OK\n")
    except Exception as e:
        print(f"\nERROR: Cannot connect to database.\n  {e}")
        await engine.dispose()
        sys.exit(1)

    async with engine.begin() as conn:
        print("[1/1] Inserting one Contact Number per contact missing rows...")
        result = await conn.execute(text(BACKFILL_SQL))
        print(f"    rows inserted: {result.rowcount}")

    await engine.dispose()
    print("\nBackfill complete.")


if __name__ == "__main__":
    asyncio.run(run())
