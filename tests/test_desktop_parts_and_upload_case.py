"""Desktop-only optical parts, case-insensitive tag upload, and the Cosmetic
Damage filter now offering Yes instead of No.
"""
import io
import pytest

from services.parts_required import (
    compute_required, DESKTOP_ONLY, PARTS_MATRIX, _is_desktop,
)
from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


class _Dev:
    """Minimal stand-in — compute_required only reads these attributes."""
    def __init__(self, device_type):
        self.device_type = device_type
        self.ram_gb = 8
        self.storage_gb = 256
        self.storage_type = "SSD"
        self.hdd_capacity_gb = 500
        self.battery_health_pct = 90


def _labels(device_type):
    return [r["label"] for r in compute_required(None, _Dev(device_type))]


@pytest.mark.parametrize("device_type", ["Desktop", "DESKTOP", "desktop", " Desktop "])
def test_desktop_tags_keep_the_optical_rows(device_type):
    """Production carries both 'Desktop' and 'DESKTOP' — an equality check
    would have leaked the rows off the shouted ones."""
    labels = _labels(device_type)
    assert DESKTOP_ONLY.issubset(set(labels))


@pytest.mark.parametrize("device_type", ["Laptop", "Tablet", "TINY", "Server"])
def test_non_desktop_tags_drop_the_optical_rows(device_type):
    labels = _labels(device_type)
    assert not (DESKTOP_ONLY & set(labels))
    # Derived, not hardcoded — the parts list grows as names are added.
    assert len(labels) == len(PARTS_MATRIX) - len(DESKTOP_ONLY)


@pytest.mark.parametrize("device_type", [None, "", "   "])
def test_blank_type_hides_them_too(device_type):
    """A tag with no device_type recorded reads as not-a-desktop. The floor
    would rather the 8,684 typeless tags look like laptops than carry two
    optical rows that are wrong on nearly all of them; a DVD drive is still
    requestable through the New Request modal, which is not gated here."""
    assert not (DESKTOP_ONLY & set(_labels(device_type)))
    assert _is_desktop(_Dev(device_type)) is False


def test_no_device_at_all_shows_everything():
    """device=None is not a tag view — it is Part Estimation and the repair
    queues asking for the full list, so nothing is filtered out."""
    assert DESKTOP_ONLY.issubset({r["label"] for r in compute_required(None, None)})
    assert _is_desktop(None) is None


def test_upload_tags_accepts_lowercase(app_client, make_user):  # noqa: F811
    """A tag typed in lowercase must resolve, and must come back in the casing
    the database stores — the page ticks rows by exact barcode string."""
    import re
    username, password = make_user("inventory_manager")
    _login(app_client, username, password)

    data = app_client.get("/devices/data?start=0&length=1", follow_redirects=True)
    RESERVED = {"data", "export", "barcodes", "api", "upload-tags"}
    barcode = ""
    for cand in re.findall(r"/devices/([A-Za-z0-9_-]+)", data.text):
        if cand not in RESERVED:
            barcode = cand
            break
    if not barcode:
        pytest.skip("no device in the fixture DB")

    csv_body = f"tag_number\n{barcode.lower()}\n{barcode.upper()}\n"
    # The devices router carries verify_csrf, so the multipart body needs the
    # double-submit token alongside the file.
    csrf = app_client.cookies.get("csrf_token") or ""
    r = app_client.post(
        "/devices/upload-tags",
        data={"csrf_token": csrf},
        files={"file": ("tags.csv", io.BytesIO(csv_body.encode()), "text/csv")},
    )
    assert r.status_code == 200, r.text[:400]
    payload = r.json()
    assert payload["not_found"] == [], f"case-folded tag not matched: {payload}"
    assert barcode in payload["found"], (
        f"found echoed the typed casing instead of the stored barcode: {payload['found']}")


def test_cosmetic_filter_offers_yes_not_no(app_client, make_user):  # noqa: F811
    username, password = make_user("inventory_manager")
    _login(app_client, username, password)
    html = app_client.get("/part-estimation", follow_redirects=True).text

    assert 'data-scope="cosmetic" data-key="yes"' in html
    assert 'data-scope="cosmetic" data-key="no"' not in html
    # Minor / Major are untouched.
    assert 'data-scope="cosmetic" data-key="minor"' in html
    assert 'data-scope="cosmetic" data-key="major"' in html


def test_hardware_filter_key_matches_its_yes_label(app_client, make_user):  # noqa: F811
    """Hardware Damage was labelled 'Yes' but keyed data-key="no" — ticking it
    filtered for the opposite of what it said. Same bug already fixed on
    Cosmetic; this pins the same fix on Hardware."""
    username, password = make_user("inventory_manager")
    _login(app_client, username, password)
    html = app_client.get("/part-estimation", follow_redirects=True).text

    assert 'data-scope="hardware" data-key="yes"' in html
    assert 'data-scope="hardware" data-key="no"' not in html
    hw_block = html.split('Hardware Damage:', 1)[1].split('</div>', 1)[0]
    assert 'id="ce_hw_yes"' in hw_block
    assert '>Yes<' in hw_block
