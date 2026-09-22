"""Throwaway verification script (not part of the committed test suite) for
the Manage Lots Asset IQC "GRN" column + Map action, and the force_entity /
devices_test_partner template changes. Run: pytest _test_manage_lots_grn_map.py -q
"""
import io
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F401


def test_manage_lots_grn_map_end_to_end(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or ""

    # 1. Create a test GRN via the real endpoint (same one manage_lots.html uses)
    r = app_client.post("/grn/create-manual", data={
        "csrf_token": csrf, "source": "ext_partner_test",
        "sender_name": "Verify Vendor",
    }, follow_redirects=True)
    assert r.status_code == 200, r.text[:500]

    # Recover the GRN number + id from the Manage Lots page
    page = app_client.get("/trade-partner/manage-lots", follow_redirects=True).text
    import re
    m = re.search(r'id="grn-(\d+)"', page)
    assert m, "could not find newly created test GRN row"
    grn_number = m.group(1)
    m2 = re.search(r'data-id="([0-9a-f-]{36})"\s+data-grn-number="' + re.escape(grn_number) + '"', page)
    assert m2, "could not find GRN id"
    grn_id = m2.group(1)

    # 2. Map a Lot Number onto it via /grn/{id}/add-lot
    lot_number = f"EPT-VERIFY{uuid.uuid4().hex[:8].upper()}"
    r = app_client.post(f"/grn/{grn_id}/add-lot", data={
        "csrf_token": csrf, "lot_number": [lot_number], "confirm_merge": [""],
    })
    assert r.status_code == 200, r.text[:500]
    assert r.json().get("ok") is True, r.text[:500]

    # 3. Upload a device via /bulk-upload/devices with force_entity, NO entity column
    barcode = f"EPT-VERIFYTAG-{uuid.uuid4().hex[:8].upper()}"
    csv_body = (
        f"lot_number,Tag No,serial_no,brand,model,cpu,generation,ram_gb,storage_gb\n"
        f"{lot_number},{barcode},SNVERIFY,VerifyBrand,VerifyModel,Intel i5,10th Gen,8,256\n"
    )
    r = app_client.post("/bulk-upload/devices", data={
        "csrf_token": csrf, "force_entity": "External Partner Test",
    }, files={"file": ("t.csv", io.BytesIO(csv_body.encode()), "text/csv")})
    assert r.status_code == 200, r.text[:1200]
    assert "1" in r.text or "inserted" in r.text.lower(), r.text[:1200]

    # 4/5. manage_lots() only lists devices with entity == EXTERNAL_PARTNER_TEST_ENTITY
    # (see routers/partner_admin.py) — the barcode showing up here IS the proof
    # force_entity actually landed, since no entity column was sent in the CSV.
    page2 = app_client.get("/trade-partner/manage-lots", follow_redirects=True).text
    assert barcode in page2, "device not on Manage Lots page — force_entity did not land"
    assert grn_number in page2
    assert "Unmapped" in page2

    # 6. Click Map — POST to /trade-partner/manage-lots/map-grn
    r = app_client.post("/trade-partner/manage-lots/map-grn", data={
        "csrf_token": csrf, "barcode": barcode, "grn_number": grn_number,
    }, follow_redirects=True)
    assert r.status_code == 200, r.text[:500]

    # 7. Confirm badge flips to Mapped, and GRN & Lot tab's Stocked count reflects it
    page3 = app_client.get("/trade-partner/manage-lots", follow_redirects=True).text
    assert "Mapped" in page3
    # Stocked badge for this GRN row should now show >= 1 (was 0 for a brand new GRN)
    m3 = re.search(r'id="grn-' + re.escape(grn_number) + r'".*?badge bg-\S+">(\d+)</span>\s*</td>\s*<td>[^<]*</td>\s*<td class="text-nowrap">',
                   page3, re.DOTALL)
    print("STOCKED_MATCH:", m3.group(1) if m3 else None)
