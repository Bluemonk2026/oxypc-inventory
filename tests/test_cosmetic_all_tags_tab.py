""""All Tags" last tab on the Cosmetic & Paint hub (routers/cosmetic.py
cosmetic_all_tags, templates/cosmetic/all_tags.html):
 - Flat table of every tag anywhere in the 8-stage pipeline, same columns as
   the Received table minus WorkID, plus a Stage column instead of Action.
 - "Assigned to" resolves per-device by ITS OWN current stage's
   MOVE_STAGE_CODE, not a single fixed stage.
 - The tab itself is appended to the existing tab bar on every cosmetic page.
 - Manager/Member visibility applies exactly as on every other cosmetic page.
"""
import pathlib
import subprocess
import sys
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def _seed_device_with_assignment(stage, barcode, stage_code, assigned_username, assigned_name):
    work_id = uuid.uuid4().hex[:12].zfill(12)[:12]
    # Keep it purely numeric-looking is not required — WorkID is just String(12)
    # unique here, no format validation on the read path this test exercises.
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.{stage})
        db.add(dev)
        await db.flush()
        db.add(WorkOrder(work_id="{work_id}", device_id=dev.id, barcode="{barcode}",
                         stage="{stage_code}", assigned_username="{assigned_username}",
                         assigned_name="{assigned_name}", status="pending",
                         created_by="itest"))
        await db.commit()

asyncio.run(main())
""")


def _cleanup_device(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device, StageMovement
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for wo in (await db.execute(select(WorkOrder).where(WorkOrder.device_id == dev.id))).scalars().all():
                await db.delete(wo)
            for m in (await db.execute(select(StageMovement).where(
                    StageMovement.device_id == dev.id))).scalars().all():
                await db.delete(m)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def test_all_tags_lists_devices_across_stages_with_correct_assignment_and_stage(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode_clean = f"ITALLCLEAN{suffix}"
    barcode_putty = f"ITALLPUTTY{suffix}"
    _seed_device_with_assignment("cleaning", barcode_clean, "clean", "eng_one_itest", "Eng One")
    _seed_device_with_assignment("putty", barcode_putty, "putty", "eng_two_itest", "Eng Two")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get("/cosmetic/all_tags", follow_redirects=True).text

        assert "<th>WorkID</th>" not in html
        assert "<th>Stage</th>" in html

        clean_row = html.split(f'<code>{barcode_clean}</code>', 1)[1].split('</tr>', 1)[0]
        assert "Eng One" in clean_row
        assert "Cleaning" in clean_row
        # data-order carries the sortable ISO date so DataTables sorts
        # chronologically, not alphabetically on the "26-Aug 14:30" text.
        assert 'data-order="' in clean_row

        putty_row = html.split(f'<code>{barcode_putty}</code>', 1)[1].split('</tr>', 1)[0]
        assert "Eng Two" in putty_row
        assert "Putty" in putty_row
    finally:
        _cleanup_device(barcode_clean)
        _cleanup_device(barcode_putty)


def test_all_tags_stage_badge_has_visible_css_and_sorts_by_assigned_date_desc():
    # Regression: ".badge.bg-teal" with no background rule renders invisible
    # (bootstrap's .badge sets color:#fff, no background of its own) — the
    # Stage badge text was present in the DOM but not visible on screen.
    css_src = open(pathlib.Path(ROOT) / "static" / "css" / "app.css", encoding="utf-8").read()
    assert ".bg-teal" in css_src
    assert "background-color" in css_src.split(".bg-teal", 1)[1].split("}", 1)[0]

    src = open(pathlib.Path(ROOT) / "templates" / "cosmetic" / "all_tags.html", encoding="utf-8").read()
    assert "order: [[8, 'desc']]" in src  # column 8 = Assigned Date


def test_all_tags_tab_appended_to_every_stage_pages_tab_bar(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    for path in ("/cosmetic/cosmetic_received", "/cosmetic/cleaning", "/cosmetic/cosmetic_completed"):
        html = app_client.get(path, follow_redirects=True).text
        assert 'href="/cosmetic/all_tags"' in html
        assert "All Tags" in html


def test_all_tags_non_manager_sees_only_own_assigned_tags(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode_mine = f"ITALLMINE{suffix}"
    barcode_other = f"ITALLOTHER{suffix}"
    username, password = make_user("qc_inspector")
    _seed_device_with_assignment("cleaning", barcode_mine, "clean", username, "Mine")
    _seed_device_with_assignment("putty", barcode_other, "putty", "someone_else_itest", "Other")
    try:
        _login(app_client, username, password)
        html = app_client.get("/cosmetic/all_tags", follow_redirects=True).text
        assert barcode_mine in html
        assert barcode_other not in html
    finally:
        _cleanup_device(barcode_mine)
        _cleanup_device(barcode_other)
