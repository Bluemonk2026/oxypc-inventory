"""One-off backfill: populate company_id + the frozen company snapshot
fields (models/sales.py Sale.company_*) on every Sale recorded BEFORE those
columns existed.

Best-effort by design: matches each sale's device's CURRENT entity to the
Company Setting row tagged with that same entity (falls back to the oldest
active company if no match, same rule create_sale() uses going forward).
This is a best guess for history — if a device's entity ownership changed
since the original sale, the backfilled company may not be the one that was
actually true on the sale date. Approved explicitly by Pankaj (2026-08-27)
with that tradeoff understood, rather than leaving historical invoices on
the old "always oldest active company" default forever.

Only touches sales where company_name IS NULL (i.e. never touched by
create_sale's new resolution logic) — safe to re-run, a no-op on sales
already resolved.

Run on the server: cd /opt/oxypc && ./venv/bin/python3 backfill_sale_company.py
"""
import asyncio

from sqlalchemy import select

from database import AsyncSessionLocal
from models.sales import Sale
from models.device import Device
from models.company import Company


async def main():
    async with AsyncSessionLocal() as db:
        active_companies = (await db.execute(
            select(Company).where(Company.is_active == True).order_by(Company.created_at)
        )).scalars().all()
        if not active_companies:
            print("No active Company rows exist — nothing to backfill against. Aborting.")
            return
        company_by_entity = {}
        for c in active_companies:
            company_by_entity.setdefault(c.company_entity, c)
        fallback_company = active_companies[0]

        sales = (await db.execute(
            select(Sale, Device)
            .join(Device, Sale.device_id == Device.id)
            .where(Sale.company_name.is_(None))
        )).all()

        print(f"{len(sales)} sale(s) with no company snapshot found.")
        if not sales:
            return

        updated = 0
        by_company_count = {}
        for sale, device in sales:
            company = company_by_entity.get(device.entity, fallback_company)
            sale.company_id = company.id
            sale.company_name = company.company_name
            sale.company_address = company.company_address
            sale.company_gstin = company.company_gstin
            sale.company_state = company.company_state
            sale.company_state_code = company.company_state_code
            sale.company_phone = company.company_phone
            sale.company_email = company.company_email
            by_company_count[company.company_name] = by_company_count.get(company.company_name, 0) + 1
            updated += 1

        await db.commit()
        print(f"Backfilled {updated} sale(s).")
        for name, count in sorted(by_company_count.items(), key=lambda kv: -kv[1]):
            print(f"  {name}: {count}")


if __name__ == "__main__":
    asyncio.run(main())
