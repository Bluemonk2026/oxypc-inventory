"""Stress Test checklist (+7 items, repeat tag updates the attached report) and
Final QC (Export Stress/QC report next to the Tag Number, Touch Type radio)."""
import json
import pathlib
import re
import subprocess
import sys
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)

NEW_ITEMS = ["HDMI Port", "Microphone", "Touch Screen", "Cosmetic Check",
             "Diagnostic Cleaning Test", "Startup/Critical Drivers", "Software/License Key"]


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=90)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    lines = r.stdout.strip().splitlines()
    return lines[-1] if lines else ""


SEED = r'''
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        db.add(Device(barcode="{tag}A", lot_id=lot.id, brand="B", model="M",
                      current_stage=DeviceStage.qc_check))
        db.add(Device(barcode="{tag}T", lot_id=lot.id, brand="B", model="M",
                      current_stage=DeviceStage.final_qc, touch_type="Touch"))
        db.add(Device(barcode="{tag}N", lot_id=lot.id, brand="B", model="M",
                      current_stage=DeviceStage.final_qc))
        await db.commit()
asyncio.run(main())
'''

# Prints a JSON line: all stress rows for the tag + the device's touch_type
QUERY = r'''
import asyncio, sys, json, os
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.stress import StressTestResult

async def main():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(StressTestResult).where(
            StressTestResult.barcode == "{barcode}").order_by(StressTestResult.id))).scalars().all()
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        print(json.dumps({{
            "rows": [{{"id": r.id, "overall": r.overall_status, "results": r.results_json,
                      "pdf": r.pdf_path, "pdf_exists": bool(r.pdf_path and os.path.exists(r.pdf_path)),
                      "pdf_size": os.path.getsize(r.pdf_path) if r.pdf_path and os.path.exists(r.pdf_path) else 0}}
                     for r in rows],
            "touch_type": dev.touch_type if dev else None,
            "stage": dev.current_stage.value if dev else None}}))
asyncio.run(main())
'''

CLEAN = r'''
import asyncio, sys, os
sys.path.insert(0, r"{root}")
from sqlalchemy import text
from database import AsyncSessionLocal
async def main():
    async with AsyncSessionLocal() as db:
        pdfs = (await db.execute(text("select pdf_path from stress_test_results where barcode like '{tag}%'"))).scalars().all()
        ids = "select id from devices where barcode like '{tag}%'"
        await db.execute(text("delete from stress_test_results where barcode like '{tag}%'"))
        await db.execute(text("delete from work_orders where device_id in (" + ids + ")"))
        await db.execute(text("delete from stage_movements where device_id in (" + ids + ")"))
        await db.execute(text("delete from devices where barcode like '{tag}%'"))
        await db.commit()
    for p in pdfs:
        try:
            if p: os.remove(p)
        except OSError:
            pass
asyncio.run(main())
'''


def _state(barcode):
    return json.loads(_run(QUERY.format(root=ROOT, barcode=barcode)))


def _csrf(client):
    return client.cookies.get("csrf_token") or "dummy"


# ── checklist definition ─────────────────────────────────────────────────────
def test_seven_new_items_are_in_the_checklist_after_the_original_twenty():
    from models.stress import STRESS_CHECKLIST_ITEMS, STRESS_NA_ITEMS
    assert len(STRESS_CHECKLIST_ITEMS) == 27 and len(set(STRESS_CHECKLIST_ITEMS)) == 27
    assert STRESS_CHECKLIST_ITEMS[20:] == NEW_ITEMS
    assert STRESS_CHECKLIST_ITEMS[19] == "Power Button"          # originals untouched
    assert STRESS_NA_ITEMS == ["Touch Screen"]                    # "if exists"


def test_stress_page_payload_carries_the_new_items(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/qc", follow_redirects=True).text
    m = re.search(r"const CHECKLIST_ITEMS = (\[.*?\]);", html, re.S)
    assert m, "CHECKLIST_ITEMS not rendered"
    items = json.loads(m.group(1))
    for name in NEW_ITEMS:
        assert name in items, name
    assert 'const NA_ITEMS = ["Touch Screen"]' in html
    assert 'data-touch="' in html or "start-test-btn" in html


def test_report_pdf_lists_na_and_new_items():
    from types import SimpleNamespace
    from datetime import datetime
    from models.stress import STRESS_CHECKLIST_ITEMS
    from routers.stress_api import _build_results, _pdf_text, _result_status_summary
    results = _build_results(["Microphone"], ["Touch Screen"])
    assert list(results) == STRESS_CHECKLIST_ITEMS
    assert results["Microphone"] == "fail" and results["Touch Screen"] == "na" and results["HDMI Port"] == "pass"
    assert _result_status_summary("na")[0] == "N/A"
    rec = SimpleNamespace(barcode="X", brand="B", model_name="M", run_by="u", run_at=datetime.now(),
                          duration=None, overall_status="FAIL", results_json=results)
    text = _pdf_text(rec).decode()
    for name in NEW_ITEMS:
        assert name in text, name


# ── repeat tag updates the attached report ───────────────────────────────────
def test_repeat_tag_updates_the_existing_report_row_and_file(app_client, make_user):  # noqa: F811
    tag = "ITSTR" + uuid.uuid4().hex[:6].upper()
    _run(SEED.format(root=ROOT, tag=tag))
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        bc = tag + "A"

        r1 = app_client.post(f"/stress/{bc}/save", data={"failed_items": "Microphone,HDMI Port",
                                                          "na_items": "", "csrf_token": _csrf(app_client)})
        assert r1.status_code == 200, r1.text
        first = r1.json()
        assert first["saved"] and first["overall_status"] == "FAIL"
        s1 = _state(bc)
        assert len(s1["rows"]) == 1 and s1["rows"][0]["pdf_exists"]
        assert s1["rows"][0]["results"]["Microphone"] == "fail"

        # Same tag comes back into the stress stage -> the attached report is updated in place
        r2 = app_client.post(f"/stress/{bc}/save", data={"failed_items": "", "na_items": "Touch Screen",
                                                          "csrf_token": _csrf(app_client)})
        assert r2.status_code == 200, r2.text
        assert r2.json()["result_id"] == first["result_id"]
        s2 = _state(bc)
        assert len(s2["rows"]) == 1, "repeat tag must not attach a second report"
        row = s2["rows"][0]
        assert row["id"] == s1["rows"][0]["id"] and row["pdf"] == s1["rows"][0]["pdf"]   # same row, same file
        assert row["overall"] == "PASS"
        assert row["results"]["Microphone"] == "pass" and row["results"]["Touch Screen"] == "na"
        assert set(row["results"]) >= set(NEW_ITEMS)
        assert row["pdf_exists"] and row["pdf_size"] > 0

        # Complete (the other exit of the stage) also reuses the one row
        r3 = app_client.post(f"/stress/{bc}/complete-to-paint", data={"na_items": "", "csrf_token": _csrf(app_client)},
                             follow_redirects=False)
        assert r3.status_code in (302, 303, 307), r3.text[:200]
        s3 = _state(bc)
        assert len(s3["rows"]) == 1 and s3["rows"][0]["id"] == first["result_id"]
        assert s3["rows"][0]["results"]["Touch Screen"] == "pass"
    finally:
        _run(CLEAN.format(root=ROOT, tag=tag))


# ── Final QC: export button + Touch Type radio ──────────────────────────────
def _pane(html, barcode):
    """The device header + Final QC form chunk for one tag."""
    i = html.index(f'/devices/{barcode}"')
    j = html.find('fqc-detail-pane', i)
    return html[i: j if j != -1 else len(html)]


def test_final_qc_radio_is_preselected_and_export_button_follows_the_report(app_client, make_user):  # noqa: F811
    tag = "ITFQT" + uuid.uuid4().hex[:6].upper()
    _run(SEED.format(root=ROOT, tag=tag))
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get("/cosmetic/final_qc", follow_redirects=True).text

        touch = _pane(html, tag + "T")
        assert re.search(r'value="Touch"\s+checked', touch) and not re.search(r'value="Non-Touch"\s+checked', touch)
        plain = _pane(html, tag + "N")                       # NULL -> default Non-Touch
        assert re.search(r'value="Non-Touch"\s+checked', plain) and not re.search(r'value="Touch"\s+checked', plain)
        # No report yet -> disabled Export
        assert "fqc-export-report disabled" in plain and f"/stress/{tag}N/report" not in plain

        # Give the tag a stress report -> Export becomes a link to it
        r = app_client.post(f"/stress/{tag}N/save", data={"failed_items": "", "na_items": "",
                                                           "csrf_token": _csrf(app_client)})
        assert r.status_code == 200, r.text
        html2 = app_client.get("/cosmetic/final_qc", follow_redirects=True).text
        plain2 = _pane(html2, tag + "N")
        assert f'/stress/{tag}N/report?result_id={r.json()["result_id"]}' in plain2
        dl = app_client.get(f"/stress/{tag}N/report")
        assert dl.status_code == 200 and len(dl.content) > 0
    finally:
        _run(CLEAN.format(root=ROOT, tag=tag))


def test_final_qc_submit_saves_touch_type(app_client, make_user):  # noqa: F811
    tag = "ITFQS" + uuid.uuid4().hex[:6].upper()
    _run(SEED.format(root=ROOT, tag=tag))
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        # NULL device, operator picks Touch
        r = app_client.post("/cosmetic/advance", data={
            "barcode": tag + "N", "final_qc_status": "fail", "failure_reason": "", "notes": "itest",
            "touch_type": "Touch", "csrf_token": _csrf(app_client)}, follow_redirects=False)
        assert r.status_code in (302, 303, 307), r.text[:300]
        assert _state(tag + "N")["touch_type"] == "Touch"
        # Touch device flipped to Non-Touch
        r = app_client.post("/cosmetic/advance", data={
            "barcode": tag + "T", "final_qc_status": "fail", "failure_reason": "", "notes": "itest",
            "touch_type": "Non-Touch", "csrf_token": _csrf(app_client)}, follow_redirects=False)
        assert r.status_code in (302, 303, 307), r.text[:300]
        assert _state(tag + "T")["touch_type"] == "Non-Touch"
    finally:
        _run(CLEAN.format(root=ROOT, tag=tag))
