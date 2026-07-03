"""Throwaway verification for the Master Data dropdown audit expansion:
cache warms correctly, master_options() Jinja global serves values, and a
representative sample of newly-wired pages render without error and show
the expected option values."""
import asyncio
from httpx import AsyncClient, ASGITransport
from main import app
from database import get_db, AsyncSessionLocal
from auth.dependencies import get_current_user
from models.user import UserRole
from utils.master_data import refresh_master_cache, master_options


class FakeAdmin:
    id = None
    username = "verify_admin"
    role = UserRole.admin
    status = True
    full_name = "Verify Admin"


async def override_user():
    return FakeAdmin()


async def override_db():
    async with AsyncSessionLocal() as db:
        yield db


app.dependency_overrides[get_current_user] = override_user
app.dependency_overrides[get_db] = override_db


async def main():
    async with AsyncSessionLocal() as db:
        await refresh_master_cache(db)
    assert "goods_returned" in master_options("dealer_credit_reason")
    assert "trc_to_showroom" in master_options("transfer_type")
    assert "sell" in master_options("market_trade_type")
    assert "Monitor / TFT" in master_options("market_item_category")
    print("Cache warm + master_options() OK")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.cookies.set("csrf_token", "verify-csrf-token")

        pages = [
            ("/dealers/new", ["retail", "wholesale"]),
            ("/sales/new", ["Maharashtra", "30_days"]),
            ("/transfers/new", ["TRC to Showroom"]),
            ("/transfers", ["TRC → Showroom"]),
            ("/whatsapp", ["Dealer Group"]),
            ("/spare-parts/ram", ["Removed from device"]),
            ("/spare-parts/consume", ["L1"]),
            ("/attendance", ["Present"]),
            ("/iqc/new", ["C0", "C3"]),
            ("/market", ["Selling", "Refurbished"]),
        ]
        for url, expected in pages:
            r = await c.get(url)
            status = r.status_code
            ok = status == 200
            missing = [e for e in expected if ok and e not in r.text]
            print(f"{url}: status={status} " + ("OK" if ok and not missing else f"ISSUE missing={missing}"))

    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
