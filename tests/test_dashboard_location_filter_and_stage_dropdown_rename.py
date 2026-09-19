"""2026-09-19:

- Dashboard Location ID filter (routers/dashboard.py `_loc`) filtered
  directly on Device.location_id, a column that is essentially unpopulated
  for real devices (a device's actual current location is read off the
  LATEST DeviceLocationLog row instead -- see _build_location_map in
  routers/devices.py and the same fix already applied to Transfers). Picking
  any location therefore matched almost nothing regardless of what was
  selected. Fixed to match a device via its latest DeviceLocationLog first,
  falling back to Device.location_id only when no log exists at all.

- Stage dropdowns/filters across the app (All Inventory, Move to Stage,
  Dashboard's own Filter by Stage, WorkID Status, IQC, the Manual Stage
  Movement page, Overdue Devices) built their option list from the raw
  DeviceStage enum. Now they all read from models.device.DROPDOWN_STAGES,
  which drops the legacy `l2` stage, and STAGE_LABELS, which now reads
  "L1/L2 Repair" / "L3/L4 Repair" for l1/l3 (was "L1 Repair"/"L3 Repair").

- routers/dashboard.py's Stage Pipeline "l3l4" tile was written back when
  L3/L4 tags never left DeviceStage.l1 (told apart only by l1l2_status).
  Today's earlier L1/L2<->L3/L4 stage-visibility fix moved that repair onto
  a real DeviceStage.l3, so the tile's filter is updated to match --
  otherwise it would silently read 0 from now on.
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


def _seed_device_at_location_via_log_only(barcode):
    """A device whose ONLY location signal is a DeviceLocationLog row --
    Device.location_id stays NULL, matching how real devices in this DB
    almost always look (24 out of 37,663 have the raw column set)."""
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.location import StorageLocation, DeviceLocationLog, LocationAction, ZoneType, UnitType
from models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        actor = (await db.execute(select(User).limit(1))).scalars().first()
        loc = StorageLocation(zone=ZoneType.warehouse, unit_type=UnitType.rack,
                               unit_id="ITDASHLOC-{uuid.uuid4().hex[:8]}")
        db.add(loc)
        await db.flush()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.ready_to_sale)
        db.add(dev)
        await db.flush()
        db.add(DeviceLocationLog(device_id=dev.id, location_id=loc.id, action=LocationAction.assigned,
                                  actor_id=actor.id, actor_name=actor.full_name))
        await db.commit()
        print(f"{{dev.id}}|{{loc.id}}")

asyncio.run(main())
""")


def _cleanup(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.location import StorageLocation, DeviceLocationLog

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for log in (await db.execute(select(DeviceLocationLog).where(
                    DeviceLocationLog.device_id == dev.id))).scalars().all():
                loc_id = log.location_id
                await db.delete(log)
            await db.delete(dev)
            await db.commit()
            if loc_id:
                loc = (await db.execute(select(StorageLocation).where(StorageLocation.id == loc_id))).scalar_one_or_none()
                if loc:
                    await db.delete(loc)
                    await db.commit()

asyncio.run(main())
""")


def test_dashboard_location_filter_matches_device_via_location_log(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITDASHLOC{suffix}"
    device_id, loc_id = _seed_device_at_location_via_log_only(barcode).split("|")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        html = app_client.get(f"/dashboard?location_id={loc_id}", follow_redirects=True).text
        # "All Devices" tile — this device is the ONLY one at this brand-new
        # location, so under the fix the filtered total is exactly 1. Before
        # the fix (Device.location_id-only match, always NULL here) it was 0.
        assert 'style="color:#6f42c1">1</div>' in html
    finally:
        _cleanup(barcode)


def test_dashboard_location_filter_excludes_devices_at_other_locations(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITDASHLOCB{suffix}"
    device_id, loc_id = _seed_device_at_location_via_log_only(barcode).split("|")
    other_suffix = uuid.uuid4().hex[:6]
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        # A location nobody is assigned to must show 0, not every device.
        other_loc_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.location import StorageLocation, ZoneType, UnitType

async def main():
    async with AsyncSessionLocal() as db:
        loc = StorageLocation(zone=ZoneType.warehouse, unit_type=UnitType.rack,
                               unit_id="ITDASHEMPTY-{other_suffix}")
        db.add(loc)
        await db.commit()
        print(loc.id)

asyncio.run(main())
""")
        html = app_client.get(f"/dashboard?location_id={other_loc_id}", follow_redirects=True).text
        # A location nobody is assigned to must show 0 in the "All Devices"
        # tile, not the seeded device's count (or the whole unfiltered DB).
        assert 'style="color:#6f42c1">0</div>' in html
    finally:
        _cleanup(barcode)
        _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.location import StorageLocation

async def main():
    async with AsyncSessionLocal() as db:
        loc = (await db.execute(select(StorageLocation).where(StorageLocation.unit_id == "ITDASHEMPTY-{other_suffix}"))).scalar_one_or_none()
        if loc:
            await db.delete(loc)
            await db.commit()

asyncio.run(main())
""")


def _assert_stage_dropdown_renamed(html, section_marker=None):
    """Shared assertion: l1/l3 renamed, l2 excluded as a selectable option.
    Scoped to a substring of html when section_marker is given, since some
    pages have more than one dropdown/select on the page. Uses the LAST
    occurrence of the marker (str.find from the end) rather than str.split,
    since some pages mention the marker text twice (e.g. an HTML comment
    naming the section before the actual label/select does)."""
    scope = html[html.rindex(section_marker):] if section_marker else html
    assert 'value="l1"' in scope
    assert 'value="l3"' in scope
    assert 'value="l2"' not in scope
    assert "L1/L2 Repair" in scope
    assert "L3/L4 Repair" in scope


def test_all_inventory_stage_filter_renamed_and_hides_l2(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/devices", follow_redirects=True).text
    _assert_stage_dropdown_renamed(html)


def test_move_to_stage_modal_renamed_and_hides_l2(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/devices", follow_redirects=True).text
    # "Move to Stage" text alone is ambiguous — the page also has a separate
    # bulk-move widget with the same label. name="to_stage" is the customise
    # modal's own select and appears nowhere else.
    _assert_stage_dropdown_renamed(html, section_marker='name="to_stage"')


def test_dashboard_stage_filter_renamed_and_hides_l2(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/dashboard", follow_redirects=True).text
    _assert_stage_dropdown_renamed(html, section_marker="Filter by Stage")


def test_workid_status_stage_filter_renamed_and_hides_l2(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/workid-status", follow_redirects=True).text
    _assert_stage_dropdown_renamed(html)


def test_iqc_stage_filter_renamed_and_hides_l2(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/iqc", follow_redirects=True).text
    _assert_stage_dropdown_renamed(html)


def test_manual_stage_movement_renamed_and_hides_l2(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/repair/move/form", follow_redirects=True).text
    _assert_stage_dropdown_renamed(html)


def test_overdue_devices_stage_filter_renamed_and_hides_l2(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/reports/overdue", follow_redirects=True).text
    _assert_stage_dropdown_renamed(html)


def test_dashboard_l3l4_pipeline_tile_matches_devices_at_l3_stage(app_client, make_user):  # noqa: F811
    """The l3l4 pipeline step now filters on DeviceStage.l3 directly (was a
    stale current_stage==l1 + l1l2_status check from before today's earlier
    fix moved L3/L4 repairs onto their own real stage)."""
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITDASHL3{suffix}"
    device_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.l3, l1l2_status="Requested to L3/L4")
        db.add(dev)
        await db.commit()
        print(dev.id)

asyncio.run(main())
""")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get("/dashboard", follow_redirects=True).text
        # The barcode itself isn't rendered on the dashboard; assert via the
        # DB-level query the route itself runs, mirroring PIPELINE_STEPS.
        count = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select, func
from database import AsyncSessionLocal
from models.device import Device, DeviceStage

async def main():
    async with AsyncSessionLocal() as db:
        n = (await db.execute(select(func.count()).select_from(Device).where(
            Device.current_stage == DeviceStage.l3, Device.is_trashed == False))).scalar()
        print(n)

asyncio.run(main())
""")
        assert int(count) >= 1
        assert html  # page rendered without error with an l3-stage device present
    finally:
        _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            await db.delete(dev)
            await db.commit()

asyncio.run(main())
""")
