"""Production Manager (/trc-production) — Repair Line section (2026-09-02):

 - "Final QC Fail (Bucket)" and "Buckets in Repair Line" tabs both had a
   plain-text/badge "Bucket ID" cell. Both now use the same clickable
   trc-view-tags link (already used by the Bucket Allocation tab) wired to
   ONE global delegated click handler, reusing the existing "Tags in
   Bucket" modal + GET /api/buckets/{id}/tags endpoint — no new backend
   route needed.
 - "Buckets in Repair Line" (loadProdAllocationTable, client-side) now also
   drops any bucket with device_count == 0 — reported as showing empty
   buckets with nothing to act on. "Final QC Fail (Bucket)" is server-
   rendered from a query that only ever groups buckets with >=1 matching
   device, so it was already structurally free of this bug — verified here
   rather than "fixed", so a future refactor doesn't reintroduce it
   unnoticed.
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


def _seed_fqc_fail_bucket_device(barcode, bucket_number):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        bucket = Bucket(bucket_number="{bucket_number}", name="FQC Fail Test Bucket",
                        assigned_to_production=False)
        db.add(bucket)
        await db.flush()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="X", model="Y",
                     current_stage=DeviceStage.l1, final_qc_status="fail",
                     fqc_failure_reason="Hardware", bucket_id=bucket.id)
        db.add(dev)
        await db.commit()
        print(bucket.id)

asyncio.run(main())
""")


def _cleanup(barcode, bucket_number):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            await db.delete(dev)
        bkt = (await db.execute(select(Bucket).where(Bucket.bucket_number == "{bucket_number}"))).scalar_one_or_none()
        if bkt:
            await db.delete(bkt)
        await db.commit()

asyncio.run(main())
""")


def test_fqc_fail_bucket_id_is_clickable(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITTRCFQC{suffix}"
    bucket_number = f"BKTFQCFAIL{suffix}"
    bucket_id = _seed_fqc_fail_bucket_device(barcode, bucket_number)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get("/trc-production", follow_redirects=True).text

        assert bucket_number in html
        assert f'class="font-monospace fw-bold text-decoration-none trc-view-tags" data-id="{bucket_id}"' in html
    finally:
        _cleanup(barcode, bucket_number)


def test_fqc_fail_bucket_query_never_returns_a_zero_count_group():
    """Structural guard, not a live-data assertion: the router groups
    fqc_fail_buckets FROM the matching devices themselves (count starts at 0
    and is incremented in the same loop iteration that creates the group),
    so a bucket can only appear here with count >= 1."""
    src = open(pathlib.Path(ROOT) / "routers" / "stock.py", encoding="utf-8").read()
    block = src.split("fqc_fail_grouped = {}", 1)[1].split("fqc_fail_buckets = list", 1)[0]
    assert '"count": 0' in block
    assert 'g["count"] += 1' in block


def test_buckets_in_repair_line_js_filters_zero_count_and_is_clickable():
    src = open(pathlib.Path(ROOT) / "templates" / "lots" / "trc_production.html", encoding="utf-8").read()
    js = src.split("function loadProdAllocationTable", 1)[1].split("loadProdAllocationTable();", 1)[0]
    assert "b.device_count > 0" in js
    assert "trc-view-tags" in js
    assert "bg-secondary\">'+b.bucket_number" not in js  # old non-clickable badge cell is gone


def test_one_delegated_handler_covers_all_three_bucket_id_links():
    src = open(pathlib.Path(ROOT) / "templates" / "lots" / "trc_production.html", encoding="utf-8").read()
    assert src.count("$(document).on('click', '.trc-view-tags'") == 1
    assert src.count('class="trc-view-tags"') == 0  # class always carries other classes too
    assert src.count("trc-view-tags") == 4  # 3 markup usages + 1 handler binding
