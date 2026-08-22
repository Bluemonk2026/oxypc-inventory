"""Every device-creation path must recognise an existing barcode regardless of
case, so a tag re-typed, re-scanned, or read off a second label with different
capitalisation is caught as a duplicate rather than silently creating a second,
independent Device row for the same physical unit — the failure that produced
1,495 duplicate pairs (and Rs 2.76 crore of sales recorded against phantom
rows) on production before this fix.

Covers all five creation paths: bulk_upload.py (IQC bulk CSV), stock.py
(single + bulk lot registration), iqc.py (manual IQC Entry), iqc_api.py
(OxyQC EXE machine API, X-OxyQC-Key), api_v1/iqc.py (OxyQC EXE JSON API,
Bearer token).

Everything here goes through app_client's own HTTP surface rather than a
separate `db` fixture — the app's engine binds asyncpg connections to the loop
that opened them, and TestClient runs its own, so mixing an async db session
into the same test as app_client calls fails cross-loop (see
tests/test_iqc_new_user.py's docstring for the same constraint).
"""
import io
import re
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def _make_lot(app_client, csrf):
    """Create a lot through the real endpoint and recover its UUID from the
    listing page — /lots/new's redirect doesn't carry it."""
    lot_number = f"CASETEST{uuid.uuid4().hex[:10].upper()}"
    r = app_client.post("/lots/new", data={
        "csrf_token": csrf, "lot_number": lot_number, "supplier_name": "Test Supplier",
        "buying_price": "1000", "qty": "5", "purchase_date": "2026-01-01",
    }, follow_redirects=True)
    assert r.status_code == 200, r.text[:800]

    listing = app_client.get(f"/lots?q={lot_number}", follow_redirects=True).text
    m = re.search(r'/lots/([0-9a-f-]{36})"[^>]*>' + re.escape(lot_number), listing)
    assert m, f"could not find the created lot {lot_number} in the listing"
    return lot_number, m.group(1)


def _stage_of(app_client, barcode):
    """How many devices (any case) currently answer to this barcode, read
    through the app's own search rather than a raw DB query."""
    r = app_client.get(f"/devices/data?search[value]={barcode}&start=0&length=50",
                       follow_redirects=True)
    data = r.json().get("data") or []
    return sum(1 for row in data if barcode.upper() in str(row).upper())


# ── 1. Bulk Upload (IQC bulk CSV entry) ──────────────────────────────────────

def test_bulk_upload_catches_a_case_differing_duplicate(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or ""
    lot_number, lot_id = _make_lot(app_client, csrf)

    barcode = f"CASE{uuid.uuid4().hex[:8].upper()}"
    csv1 = f"tag_number,lot_number\n{barcode},{lot_number}\n"
    r1 = app_client.post("/bulk-upload/devices", data={"csrf_token": csrf},
                         files={"file": ("t1.csv", io.BytesIO(csv1.encode()), "text/csv")})
    assert r1.status_code == 200, r1.text[:800]

    # Second upload of the same physical tag, different case — this is the
    # exact production sequence (a lot re-uploaded days later) that produced
    # 1,495 duplicate device rows before this fix. The result page renders the
    # duplicate-review modal instead of silently importing a second device.
    csv2 = f"tag_number,lot_number\n{barcode.lower()},{lot_number}\n"
    r2 = app_client.post("/bulk-upload/devices", data={"csrf_token": csrf},
                         files={"file": ("t2.csv", io.BytesIO(csv2.encode()), "text/csv")})
    assert r2.status_code == 200, r2.text[:800]
    assert f'data-tag="{barcode.lower()}"' in r2.text, (
        "the case-differing tag was not flagged as a duplicate for review")

    assert _stage_of(app_client, barcode) == 1, "a second device row was created"


# ── 2. Stock — single-device lot registration ────────────────────────────────

def test_stock_register_device_rejects_case_differing_duplicate(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or ""
    lot_number, lot_id = _make_lot(app_client, csrf)

    barcode = f"CASE{uuid.uuid4().hex[:8].upper()}"
    # register-device posts a pure JSON body, so CSRF is satisfied via the
    # X-CSRF-Token header fallback rather than a form field.
    r1 = app_client.post(f"/lots/{lot_id}/register-device",
                         json={"barcode": barcode}, headers={"X-CSRF-Token": csrf})
    assert r1.status_code == 200, f"{r1.status_code}: {r1.text[:800]}"
    assert r1.json().get("ok") is True, r1.text[:800]

    r2 = app_client.post(f"/lots/{lot_id}/register-device",
                         json={"barcode": barcode.lower()}, headers={"X-CSRF-Token": csrf})
    assert r2.status_code == 409, r2.text[:800]
    assert _stage_of(app_client, barcode) == 1


# ── 3. Stock — bulk CSV lot registration ─────────────────────────────────────

def test_stock_register_bulk_csv_skips_case_differing_duplicate(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or ""
    lot_number, lot_id = _make_lot(app_client, csrf)

    barcode = f"CASE{uuid.uuid4().hex[:8].upper()}"
    r1 = app_client.post(f"/lots/{lot_id}/register-device", json={"barcode": barcode},
                         headers={"X-CSRF-Token": csrf})
    assert r1.status_code == 200, r1.text[:800]

    csv_body = f"barcode\n{barcode.lower()}\n"
    r2 = app_client.post(f"/lots/{lot_id}/register-bulk-csv",
                         data={"csrf_token": csrf},
                         files={"file": ("tags.csv", io.BytesIO(csv_body.encode()), "text/csv")})
    assert r2.status_code == 200, r2.text[:800]
    assert r2.json().get("skipped", 0) >= 1, r2.json()
    assert _stage_of(app_client, barcode) == 1


# ── 4. Manual IQC Entry ───────────────────────────────────────────────────────

def test_manual_iqc_entry_shows_already_exists_for_case_differing_tag(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or ""
    lot_number, lot_id = _make_lot(app_client, csrf)

    barcode = f"CASE{uuid.uuid4().hex[:8].upper()}"
    r1 = app_client.post(f"/lots/{lot_id}/register-device", json={"barcode": barcode},
                         headers={"X-CSRF-Token": csrf})
    assert r1.status_code == 200, r1.text[:800]

    r2 = app_client.post("/iqc/new", data={
        "csrf_token": csrf, "barcode": barcode.lower(), "lot_id": lot_id,
    }, follow_redirects=True)
    assert r2.status_code == 200, r2.text[:800]
    assert "already exists" in r2.text
    assert _stage_of(app_client, barcode) == 1


# ── 5. OxyQC EXE machine API (X-OxyQC-Key) ───────────────────────────────────

def test_iqc_api_check_and_submit_are_case_insensitive(app_client, make_user):  # noqa: F811
    from config import OXYQC_API_KEY

    username, password = make_user("admin")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or ""
    lot_number, lot_id = _make_lot(app_client, csrf)

    barcode = f"CASE{uuid.uuid4().hex[:8].upper()}"
    r1 = app_client.post(f"/lots/{lot_id}/register-device", json={"barcode": barcode},
                         headers={"X-CSRF-Token": csrf})
    assert r1.status_code == 200, r1.text[:800]

    headers = {"X-OxyQC-Key": OXYQC_API_KEY}
    r2 = app_client.get(f"/iqc/api/check/{barcode.lower()}", headers=headers)
    assert r2.status_code == 200, r2.text[:500]
    assert r2.json()["exists"] is True, (
        "check endpoint reported a case-differing existing tag as not found")

    r3 = app_client.post("/iqc/api/submit", headers=headers, json={
        "barcode": barcode.lower(), "lot_id": lot_id,
    })
    assert r3.status_code == 409, r3.text[:800]
    assert _stage_of(app_client, barcode) == 1


# ── 6. OxyQC EXE JSON API v1 (Bearer token) ─────────────────────────────────

def test_api_v1_register_and_lookup_are_case_insensitive(app_client, make_user):  # noqa: F811
    import subprocess
    import sys as _sys
    import json as _json

    # Minted out-of-process for the same cross-loop reason described in the
    # module docstring — inserting via an in-process async session here would
    # bind the connection to a loop app_client's own requests don't share.
    script = (
        "import asyncio, sys, uuid; sys.path.insert(0, '.')\n"
        "from database import AsyncSessionLocal\n"
        "from models.api_key import APIKey\n"
        "async def m():\n"
        "    raw, h = APIKey.generate()\n"
        "    async with AsyncSessionLocal() as db:\n"
        "        db.add(APIKey(id=uuid.uuid4(), name='test-key', key_prefix=raw[:12],\n"
        "                      key_hash=h, scopes=['iqc:read','iqc:write'], created_by='test'))\n"
        "        await db.commit()\n"
        "    print(raw)\n"
        "asyncio.run(m())\n"
    )
    out = subprocess.run([_sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    raw_key = out.stdout.strip().splitlines()[-1]
    headers = {"Authorization": f"Bearer {raw_key}"}

    username, password = make_user("admin")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or ""
    lot_number, lot_id = _make_lot(app_client, csrf)

    barcode = f"CASE{uuid.uuid4().hex[:8].upper()}"
    r1 = app_client.post(f"/lots/{lot_id}/register-device", json={"barcode": barcode},
                         headers={"X-CSRF-Token": csrf})
    assert r1.status_code == 200, r1.text[:800]

    r2 = app_client.get(f"/api/v1/iqc/lookup?barcode={barcode.lower()}", headers=headers)
    assert r2.status_code == 200, r2.text[:500]

    r3 = app_client.post("/api/v1/iqc/register", headers=headers, json={
        "barcode": barcode.lower(), "lot_id": lot_id,
    })
    assert r3.status_code == 409, r3.text[:800]
    assert _stage_of(app_client, barcode) == 1
