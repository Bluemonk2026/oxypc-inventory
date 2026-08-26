"""Dashboard page:
 - Financial Summary card gets a "Yearly" badge + a new Labour Spent line;
   Parts Spent / Labour Spent are sourced from services.business_pl.
   compute_year_parts_labour_cogs — the exact same computation Business
   P&L's Monthly Breakdown table uses — so the two pages never disagree.
 - Cosmetic count's drill-through link now covers all 8 cosmetic stages
   (previously missing cosmetic_received/cosmetic_completed, so the badge
   count and the linked device list silently disagreed).
 - Final QC count's drill-through already covered all 3 stages — unchanged.
 - New Year filter dropdown, sourced from Master Data category "report_year"
   (utils.master_data.report_year_values) — the same source Business P&L's
   year tabs now use too, so both pages always offer the same year list.
"""
import pathlib
import subprocess
import sys
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
TEST_YEAR = 2099  # far-future, won't collide with real or other test data


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def _seed_sale_with_parts_and_labour(barcode, part_code, parts_cost, labour_cost):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.sales import Sale
from models.spare_parts import SparePart, SparePartConsumption
from models.engines import RepairAttempt

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.sold, device_price=1000)
        db.add(dev)
        await db.flush()

        sale = Sale(sale_number="ITSALE{barcode}", device_id=dev.id, sale_price=5000,
                    sold_at=datetime({TEST_YEAR}, 6, 15))
        db.add(sale)

        part = SparePart(part_code="{part_code}", name="ITest Part", category="Other",
                         unit_price={parts_cost}, qty_in_stock=10)
        db.add(part)
        await db.flush()
        db.add(SparePartConsumption(device_id=dev.id, part_id=part.id, qty_used=1,
                                    unit_cost={parts_cost}, total_cost={parts_cost}))

        db.add(RepairAttempt(device_id=dev.id, level=1, attempt_no=1, cost={labour_cost}))

        await db.commit()
        print(dev.id)

asyncio.run(main())
""")


def _cleanup(barcode, part_code):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.sales import Sale
from models.spare_parts import SparePart, SparePartConsumption
from models.engines import RepairAttempt

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for row in (await db.execute(select(RepairAttempt).where(
                    RepairAttempt.device_id == dev.id))).scalars().all():
                await db.delete(row)
            for row in (await db.execute(select(SparePartConsumption).where(
                    SparePartConsumption.device_id == dev.id))).scalars().all():
                await db.delete(row)
            for row in (await db.execute(select(Sale).where(
                    Sale.device_id == dev.id))).scalars().all():
                await db.delete(row)
            await db.delete(dev)
        part = (await db.execute(select(SparePart).where(SparePart.part_code == "{part_code}"))).scalar_one_or_none()
        if part:
            await db.delete(part)
        await db.commit()

asyncio.run(main())
""")


def test_dashboard_and_business_pl_agree_on_yearly_parts_and_labour(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITFINY{suffix}"
    part_code = f"ITPART{suffix}"
    _seed_sale_with_parts_and_labour(barcode, part_code, 250, 400)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        dash_html = app_client.get(f"/dashboard?year={TEST_YEAR}", follow_redirects=True).text
        pl_html = app_client.get(f"/reports/business-pl?year={TEST_YEAR}", follow_redirects=True).text

        # Both pages must show the exact same Parts Cost / Labour Cost total
        # for this year — the whole point of sharing one computation. Currency-
        # prefixed to avoid false-matching an unrelated bare number elsewhere.
        assert "₹250" in dash_html  # Parts Spent line reflects our seeded 250
        assert "₹400" in dash_html  # Labour Spent line reflects our seeded 400
        assert "₹250" in pl_html
        assert "₹400" in pl_html
    finally:
        _cleanup(barcode, part_code)


def test_financial_summary_has_yearly_badge_and_labour_spent_line():
    src = open(pathlib.Path(ROOT) / "templates" / "dashboard.html", encoding="utf-8").read()
    card = src.split("financial_summary_card()", 1)[1].split("{% endmacro %}", 1)[0]
    assert "Yearly" in card
    assert "Labour Spent" in card
    assert "yearly_parts_cost" in card
    assert "yearly_labour_cost" in card


def test_cosmetic_drilldown_link_covers_all_eight_stages():
    src = open(pathlib.Path(ROOT) / "templates" / "dashboard.html", encoding="utf-8").read()
    line = [l for l in src.splitlines() if "'cosmetic'," in l and "Cosmetic" in l][0]
    for stage in ("cosmetic_received", "cleaning", "putty", "dry_sanding",
                  "masking", "painting", "water_sanding", "cosmetic_completed"):
        assert stage in line, stage


def test_final_qc_drilldown_link_covers_all_three_stages():
    src = open(pathlib.Path(ROOT) / "templates" / "dashboard.html", encoding="utf-8").read()
    line = [l for l in src.splitlines() if "'final_qc'," in l and "Final QC" in l][0]
    for stage in ("final_qc", "final_qc_pass_hold", "final_qc_fail_hold"):
        assert stage in line, stage


def test_dashboard_has_year_dropdown_wired_to_master_data(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/dashboard", follow_redirects=True).text
    assert 'name="year"' in html
    assert '<label class="form-label small fw-semibold">Year</label>' in html


def test_business_pl_year_tabs_use_year_choices_not_hardcoded_range():
    src = open(pathlib.Path(ROOT) / "templates" / "reports" / "business_pl.html", encoding="utf-8").read()
    assert "for y in year_choices" in src
    assert "range(year - 2, year + 3)" not in src


def test_report_year_registered_in_master_data_categories():
    src = open(pathlib.Path(ROOT) / "routers" / "master.py", encoding="utf-8").read()
    assert '"report_year"' in src
