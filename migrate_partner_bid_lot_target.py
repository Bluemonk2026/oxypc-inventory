"""One-shot migration: let a partner bid target a Lot as well as a Listing.

partner_bids.listing_id was NOT NULL because bidding originally existed only
against published listings. Bids placed from the catalog's "Lots Available to
You" table have no listing behind them, so that constraint has to be relaxed
and lot_id given its foreign key.

The startup provisioner cannot do either: it only ever ADDs columns, never
alters an existing column's nullability, and never adds constraints.

A CHECK enforces exactly one target. Without it a row with both (or neither)
set is representable, and every reader would need its own opinion about which
one wins — the kind of ambiguity that only ever surfaces as a wrong lot being
marked won.

Safe to run repeatedly.

Run: python migrate_partner_bid_lot_target.py
"""
import asyncio
from sqlalchemy import text
from database import engine


async def main():
    async with engine.begin() as conn:
        col = (await conn.execute(text("""
            select is_nullable from information_schema.columns
            where table_name = 'partner_bids' and column_name = 'listing_id'
        """))).scalar()
        if col == "NO":
            print("listing_id is NOT NULL -> dropping the constraint")
            await conn.execute(text(
                "ALTER TABLE partner_bids ALTER COLUMN listing_id DROP NOT NULL"))
        else:
            print("listing_id already nullable")

        has_lot = (await conn.execute(text("""
            select 1 from information_schema.columns
            where table_name = 'partner_bids' and column_name = 'lot_id'
        """))).scalar()
        if not has_lot:
            print("adding lot_id column")
            await conn.execute(text(
                "ALTER TABLE partner_bids ADD COLUMN lot_id UUID NULL"))

        has_fk = (await conn.execute(text("""
            select 1 from information_schema.table_constraints tc
            join information_schema.key_column_usage kcu
              on tc.constraint_name = kcu.constraint_name
            where tc.table_name = 'partner_bids'
              and tc.constraint_type = 'FOREIGN KEY'
              and kcu.column_name = 'lot_id'
            limit 1
        """))).scalar()
        if has_fk:
            print("lot_id FK already present")
        else:
            print("adding FK partner_bids.lot_id -> lots.id")
            await conn.execute(text(
                "ALTER TABLE partner_bids ADD CONSTRAINT fk_partner_bids_lot "
                "FOREIGN KEY (lot_id) REFERENCES lots(id)"))

        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_partner_bids_lot_id "
            "ON partner_bids (lot_id)"))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_partner_bids_lot_amount "
            "ON partner_bids (lot_id, bid_amount)"))

        has_chk = (await conn.execute(text("""
            select 1 from information_schema.table_constraints
            where table_name = 'partner_bids'
              and constraint_name = 'ck_partner_bids_one_target'
        """))).scalar()
        if has_chk:
            print("one-target CHECK already present")
        else:
            print("adding CHECK: exactly one of listing_id / lot_id")
            await conn.execute(text(
                "ALTER TABLE partner_bids ADD CONSTRAINT ck_partner_bids_one_target "
                "CHECK ((listing_id IS NULL) <> (lot_id IS NULL))"))

    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
