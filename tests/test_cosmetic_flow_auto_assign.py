"""Cosmetic mid-pipeline "Move to <next stage>" — Flow Data auto-assign
(routers/cosmetic.py advance_stage, _resolve_flow_next_user;
templates/cosmetic/stage.html directMoveOrManual):

 - Clicking Move with no engineer picked first tries to auto-assign the tag
   to whoever the CURRENT USER's own Flow Data row says handles the NEXT
   stage — no modal. E.g. Yogesh (Cleaning) clicking "Move to Putty" is
   auto-assigned to whoever sits in the Putty column of the flow row that
   has Yogesh in the Cleaning column.
 - Falls back to the pre-existing "select a user" 400 (which the frontend
   turns into the manual-pick modal) when: no flow row has this user in the
   current stage's column, that row's next-stage cell is blank, or the
   next-stage user is no longer active or no longer permitted for that
   stage — a broken/stale Flow Data row must never block the move.
 - Water Sanding's "Move to Cosmetic Completed" never needs an assignee at
   all (Cosmetic Completed is a Cosmetic-Manager-handled holding stage, not
   a per-tag hand-off) — same exemption Cosmetic Completed's own
   "Move to Final QC" already had.
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


def _seed_device_at(stage, barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        db.add(Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.{stage}))
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


def _seed_flow_row(cleaning=None, putty=None, dry_sanding=None):
    row_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from database import AsyncSessionLocal
from models.cosmetic_flow import CosmeticFlowRow

async def main():
    async with AsyncSessionLocal() as db:
        row = CosmeticFlowRow(
            cleaning_user_id={f'"{cleaning}"' if cleaning else "None"},
            putty_user_id={f'"{putty}"' if putty else "None"},
            dry_sanding_user_id={f'"{dry_sanding}"' if dry_sanding else "None"},
        )
        db.add(row)
        await db.flush()
        print(row.id)
        await db.commit()

asyncio.run(main())
""")
    return row_id


def _cleanup_flow_row(row_id):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.cosmetic_flow import CosmeticFlowRow

async def main():
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(CosmeticFlowRow).where(
            CosmeticFlowRow.id == "{row_id}"))).scalar_one_or_none()
        if row:
            await db.delete(row)
        await db.commit()

asyncio.run(main())
""")


def _user_id(username):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == "{username}"))).scalar_one()
        print(u.id)

asyncio.run(main())
""")


def _device_state(barcode):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        wo = (await db.execute(select(WorkOrder).where(WorkOrder.device_id == dev.id)
              .order_by(WorkOrder.assigned_at.desc()))).scalars().first()
        print("stage=" + dev.current_stage.value)
        print("assigned_username=" + str(wo.assigned_username if wo else None))

asyncio.run(main())
""")


def test_flow_auto_assign_moves_without_modal_when_flow_matches(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITFLOWA{suffix}"
    mover_username, mover_password = make_user("cosmetic_cleaning")
    target_username, _ = make_user("cosmetic_putty")
    mover_id = _user_id(mover_username)
    target_id = _user_id(target_username)

    _seed_device_at("cleaning", barcode)
    row_id = _seed_flow_row(cleaning=mover_id, putty=target_id)
    try:
        _login(app_client, mover_username, mover_password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        r = app_client.post("/cosmetic/advance", data={"csrf_token": csrf, "barcode": barcode},
                            follow_redirects=False)
        assert r.status_code == 200, r.text[:400]

        state = _device_state(barcode)
        assert "stage=putty" in state
        assert f"assigned_username={target_username}" in state
    finally:
        _cleanup_device(barcode)
        _cleanup_flow_row(row_id)


def test_flow_auto_assign_two_hop_chain_matches_worked_example(app_client, make_user):  # noqa: F811
    """Mirrors the exact scenario reported: Yogesh (Cleaning) moving to Putty
    lands on Lalo; Lalo (Putty) moving to Dry Sanding lands on Priyakshi —
    both hops read the SAME flow row, keyed by whoever is currently moving."""
    suffix = uuid.uuid4().hex[:6]
    barcode_1 = f"ITFLOWB1{suffix}"
    barcode_2 = f"ITFLOWB2{suffix}"
    yogesh_u, yogesh_p = make_user("cosmetic_cleaning")
    lalo_u, lalo_p = make_user("cosmetic_putty")
    priyakshi_u, _ = make_user("cosmetic_dry_sanding")
    yogesh_id, lalo_id, priyakshi_id = _user_id(yogesh_u), _user_id(lalo_u), _user_id(priyakshi_u)

    _seed_device_at("cleaning", barcode_1)
    _seed_device_at("putty", barcode_2)
    row_id = _seed_flow_row(cleaning=yogesh_id, putty=lalo_id, dry_sanding=priyakshi_id)
    try:
        # Hop 1: Yogesh moves barcode_1 Cleaning -> Putty, lands on Lalo.
        _login(app_client, yogesh_u, yogesh_p)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        r1 = app_client.post("/cosmetic/advance", data={"csrf_token": csrf, "barcode": barcode_1},
                             follow_redirects=False)
        assert r1.status_code == 200, r1.text[:400]
        assert f"assigned_username={lalo_u}" in _device_state(barcode_1)

        # Hop 2: Lalo moves barcode_2 Putty -> Dry Sanding, lands on Priyakshi.
        app_client.cookies.clear()
        _login(app_client, lalo_u, lalo_p)
        csrf2 = app_client.cookies.get("csrf_token") or "dummy"
        r2 = app_client.post("/cosmetic/advance", data={"csrf_token": csrf2, "barcode": barcode_2},
                             follow_redirects=False)
        assert r2.status_code == 200, r2.text[:400]
        state2 = _device_state(barcode_2)
        assert "stage=dry_sanding" in state2
        assert f"assigned_username={priyakshi_u}" in state2
    finally:
        _cleanup_device(barcode_1)
        _cleanup_device(barcode_2)
        _cleanup_flow_row(row_id)


def test_flow_auto_assign_falls_back_when_no_flow_row_matches(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITFLOWNONE{suffix}"
    mover_username, mover_password = make_user("cosmetic_cleaning")
    _seed_device_at("cleaning", barcode)
    try:
        _login(app_client, mover_username, mover_password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        r = app_client.post("/cosmetic/advance", data={"csrf_token": csrf, "barcode": barcode})
        assert r.status_code == 400
        assert "Select a user" in r.text
    finally:
        _cleanup_device(barcode)


def test_flow_auto_assign_falls_back_when_next_cell_blank(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITFLOWBLANK{suffix}"
    mover_username, mover_password = make_user("cosmetic_cleaning")
    mover_id = _user_id(mover_username)
    _seed_device_at("cleaning", barcode)
    row_id = _seed_flow_row(cleaning=mover_id, putty=None)
    try:
        _login(app_client, mover_username, mover_password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        r = app_client.post("/cosmetic/advance", data={"csrf_token": csrf, "barcode": barcode})
        assert r.status_code == 400
        assert "Select a user" in r.text
    finally:
        _cleanup_device(barcode)
        _cleanup_flow_row(row_id)


def test_flow_auto_assign_falls_back_when_next_user_inactive(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITFLOWINACT{suffix}"
    mover_username, mover_password = make_user("cosmetic_cleaning")
    target_username, _ = make_user("cosmetic_putty")
    mover_id = _user_id(mover_username)
    target_id = _user_id(target_username)
    _seed_device_at("cleaning", barcode)
    row_id = _seed_flow_row(cleaning=mover_id, putty=target_id)
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == "{target_username}"))).scalar_one()
        u.status = False
        await db.commit()

asyncio.run(main())
""")
    try:
        _login(app_client, mover_username, mover_password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        r = app_client.post("/cosmetic/advance", data={"csrf_token": csrf, "barcode": barcode})
        assert r.status_code == 400
        assert "Select a user" in r.text
    finally:
        _cleanup_device(barcode)
        _cleanup_flow_row(row_id)


def test_water_sanding_move_never_needs_an_assignee(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITFLOWWS{suffix}"
    username, password = make_user("cosmetic_water_sanding")
    _seed_device_at("water_sanding", barcode)
    try:
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        r = app_client.post("/cosmetic/advance", data={"csrf_token": csrf, "barcode": barcode},
                            follow_redirects=False)
        assert r.status_code == 200, r.text[:400]
        assert "stage=cosmetic_completed" in _device_state(barcode)
    finally:
        _cleanup_device(barcode)


def test_stage_page_uses_direct_move_not_modal_onclick():
    src = open(pathlib.Path(ROOT) / "templates" / "cosmetic" / "stage.html", encoding="utf-8").read()
    assert "directMoveOrManual(" in src
    assert "onclick=\"openMoveModal(" not in src
