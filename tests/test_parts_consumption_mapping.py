"""Parts Consumption: the consolidated 31-name list, its two sections, the
Master Data passthrough, and the legacy aliases that keep old requests matched.
"""
import json
import pytest

from tests.test_iqc_new_user import make_user  # noqa: F401  (fixture)
from services.parts_required import (
    PARTS_MATRIX, LEGACY_LABELS, MAIN, ADDITIONAL,
    compute_required, extra_master_labels, rules_by_label,
)
from models.master import MASTER_SEED
from utils.master_data import _MASTER_CACHE


def _labels(rows):
    return [r["label"] for r in rows]


def test_matrix_matches_the_master_seed_exactly():
    """The table and the dropdown must not drift apart — that drift is the
    whole reason parts were requested under names Stores could not pick."""
    assert _labels(compute_required(None, None)) == MASTER_SEED["part_category"]


def test_sections_split_twentytwo_and_nine():
    rows = compute_required(None, None)
    assert [r["label"] for r in rows if r["section"] == MAIN][-1] == "DVD Drive"
    assert sum(1 for r in rows if r["section"] == MAIN) == 22
    assert sum(1 for r in rows if r["section"] == ADDITIONAL) == 9


def test_adapter_is_gone():
    assert "Adapter" not in _labels(compute_required(None, None))


def test_new_master_value_lands_under_additional_parts():
    original = _MASTER_CACHE.get("part_category")
    try:
        _MASTER_CACHE["part_category"] = MASTER_SEED["part_category"] + ["Fingerprint Reader"]
        rows = compute_required(None, None, include_master_extras=True)
        extra = [r for r in rows if r["label"] == "Fingerprint Reader"]
        assert len(extra) == 1
        assert extra[0]["section"] == ADDITIONAL
        assert extra[0]["required"] is False
        # It must be last — appended, never interleaved into the fixed list.
        assert rows[-1]["label"] == "Fingerprint Reader"
    finally:
        if original is None:
            _MASTER_CACHE.pop("part_category", None)
        else:
            _MASTER_CACHE["part_category"] = original


def test_master_extras_are_deduped_case_insensitively():
    original = _MASTER_CACHE.get("part_category")
    try:
        _MASTER_CACHE["part_category"] = ["ram", "RAM Cover", "  hard drive  "]
        assert extra_master_labels() == []
    finally:
        if original is None:
            _MASTER_CACHE.pop("part_category", None)
        else:
            _MASTER_CACHE["part_category"] = original


def test_extras_are_off_by_default():
    """Repair queues count required parts; an extra can never be required, so
    including it there would only add rows that always answer No."""
    assert len(compute_required(None, None)) == len(PARTS_MATRIX)


@pytest.mark.parametrize("old,new", [
    ("Display Panel", "Panel"), ("Display", "Screen"), ("Web Cam", "Camera"),
    ("Charging Port", "DC Jack"), ("Ethernet Ports", "LAN Port"),
    ("USB Ports", "USB Port"), ("Touchpad", "Logic Card"),
    ("Wi-Fi", "Wi-Fi Card"), ("Palm rest", "Touchpad Cover"),
])
def test_every_rename_carries_a_legacy_alias(old, new):
    assert old in LEGACY_LABELS[new], f"{old} would orphan its in-flight requests"


def test_part_estimation_can_still_resolve_its_old_column_names():
    """Part Estimation asks for rules by its own column headers, which are
    stored against historical estimates and so were not renamed."""
    rules = rules_by_label()
    for name in ("Wi-Fi", "Web Cam", "Touchpad", "HDD Connector", "Speaker"):
        assert name in rules


def test_external_battery_shares_the_internal_battery_rule():
    by_label = {r[0]: r[3] for r in PARTS_MATRIX}
    assert by_label["External Battery"] is by_label["Internal Battery"]


def test_device_detail_renders_both_section_headings(app_client, make_user):  # noqa: F811
    """A Jinja error in the new heading block would 500 the page the floor
    opens on every tag, so assert it actually renders."""
    import re
    from tests.test_iqc_new_user import _login
    username, password = make_user("inventory_manager")
    _login(app_client, username, password)

    # The list is DataTables server-side, so the HTML carries no row links —
    # take a real barcode from the same JSON endpoint the table uses.
    data = app_client.get("/devices/data?start=0&length=1", follow_redirects=True)
    try:
        rows = data.json().get("data") or []
    except Exception:
        rows = []
    if not rows:
        pytest.skip("no device in the fixture DB to open")
    # Rows are lists of rendered HTML cells; take the barcode from a row link.
    # Matched against the raw body so JSON escaping of the quote cannot hide it,
    # and filtered against the router's non-barcode paths.
    RESERVED = {"data", "export", "barcodes", "api"}
    barcode = ""
    for cand in re.findall(r"/devices/([A-Za-z0-9_-]+)", data.text):
        if cand not in RESERVED:
            barcode = cand
            break
    if not barcode:
        pytest.skip("device row carries no barcode")

    html = app_client.get(f"/devices/{barcode}", follow_redirects=True).text
    assert "MAIN PARTS" in html
    assert "ADDITIONAL PARTS" in html
    assert html.index("MAIN PARTS") < html.index("ADDITIONAL PARTS")
    for label in ("Logic Card", "Wi-Fi Card", "DC Jack", "Touchpad Cover", "Battery Cable"):
        assert label in html, f"{label} missing from Parts Consumption"
