"""Desktop-only optical parts, case-insensitive tag upload, and the Cosmetic
Damage filter now offering Yes instead of No.
"""
import io
import pytest

from services.parts_required import compute_required, DESKTOP_ONLY, _is_desktop
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
    assert len(labels) == 29


@pytest.mark.parametrize("device_type", [None, "", "   "])
def test_unknown_type_still_shows_them(device_type):
    """8,684 live tags have no device_type. A blank is missing data, not
    evidence of a laptop — hiding the rows there would leave no way to request
    a DVD drive for a machine that has one."""
    assert DESKTOP_ONLY.issubset(set(_labels(device_type)))
    assert _is_desktop(_Dev(device_type)) is None


def test_no_device_at_all_shows_everything():
    assert DESKTOP_ONLY.issubset({r["label"] for r in compute_required(None, None)})


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
