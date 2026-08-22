"""Cosmetic & Paint — placeholder Fail button, Cleaning and Water Sanding only.

The button has no backend of its own yet; it opens a shared "under
development" modal, so the only thing worth pinning down is exactly which
stage pages show it. Each stage page only renders its Action column (and so
the button) once a device sits there, so the test seeds one via a subprocess
against the real DB — same isolation reason as make_user's setup/teardown in
test_iqc_new_user.py: the async engine is bound to whichever loop opened it,
and TestClient runs its own, so touching it from this process directly can
deadlock or fail with a misleading error.
"""
import pathlib
import subprocess
import sys
import uuid

import pytest

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)

_SETUP_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        assert lot, "need at least one Lot in the DB"
        d = Device(barcode="{barcode}", lot_id=lot.id, brand="TestBrand",
                   model="TestModel", current_stage=DeviceStage("{stage}"))
        db.add(d)
        await db.commit()

asyncio.run(main())
"""

_TEARDOWN_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        d = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if d:
            d.is_active = False
            d.is_trashed = True
        await db.commit()

asyncio.run(main())
"""


@pytest.fixture()
def device_at_stage():
    """Factory: seed one throwaway device at a given cosmetic stage, retired
    (is_trashed) afterward — this project never hard-deletes rows."""
    created = []

    def _run(src, barcode, stage):
        r = subprocess.run(
            [sys.executable, "-c", src.format(root=ROOT, barcode=barcode, stage=stage)],
            capture_output=True, text=True, cwd=ROOT, timeout=120,
        )
        if r.returncode != 0:
            raise RuntimeError(f"device setup failed:\n{r.stdout}\n{r.stderr}")

    def _make(stage):
        barcode = f"ITESTCOS{uuid.uuid4().hex[:8].upper()}"
        _run(_SETUP_SRC, barcode, stage)
        created.append(barcode)
        return barcode

    yield _make

    for barcode in created:
        _run(_TEARDOWN_SRC, barcode, "")


STAGES_WITH_FAIL = ["cleaning", "water_sanding"]
STAGES_WITHOUT_FAIL = ["dry_sanding", "masking", "painting"]


def _stage_html(app_client, make_user, device_at_stage, stage):  # noqa: F811
    device_at_stage(stage)
    username, password = make_user("admin")
    _login(app_client, username, password)
    return app_client.get(f"/cosmetic/{stage}", follow_redirects=True).text


@pytest.mark.parametrize("stage", STAGES_WITH_FAIL)
def test_fail_button_shown_on_cleaning_and_water_sanding(app_client, make_user, device_at_stage, stage):  # noqa: F811
    html = _stage_html(app_client, make_user, device_at_stage, stage)
    assert 'data-bs-target="#failUnderDevModal"' in html
    assert "under development" in html.lower()


@pytest.mark.parametrize("stage", STAGES_WITHOUT_FAIL)
def test_fail_button_hidden_on_other_cosmetic_stages(app_client, make_user, device_at_stage, stage):  # noqa: F811
    html = _stage_html(app_client, make_user, device_at_stage, stage)
    assert 'data-bs-target="#failUnderDevModal"' not in html
