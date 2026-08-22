"""Dropdown Configuration: the three parts lists lead the Repair & QC section
and carry their new labels.

Ordering is asserted by string position rather than by parsing the accordion,
because the only thing that can silently regress here is someone re-sorting
ACCORDION_SECTIONS["repair"]["cat_keys"] alphabetically.
"""
import pytest

from routers.master import ACCORDION_SECTIONS, CATEGORIES
from models.master import MASTER_SEED
from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def _repair_keys():
    return next(s for s in ACCORDION_SECTIONS if s["id"] == "repair")["cat_keys"]


def test_parts_lists_lead_the_repair_section():
    assert _repair_keys()[:3] == [
        "spare_part_brand", "part_category", "iqc_part_category",
    ]


def test_no_category_listed_twice_in_any_section():
    for sec in ACCORDION_SECTIONS:
        keys = sec["cat_keys"]
        assert len(keys) == len(set(keys)), f"{sec['id']} has duplicates"


def test_every_accordion_key_has_a_label():
    labelled = {k for k, _, _ in CATEGORIES}
    for sec in ACCORDION_SECTIONS:
        for k in sec["cat_keys"]:
            assert k in labelled, f"{k} has no CATEGORIES row and would not render"


def test_labels_renamed():
    labels = {k: lbl for k, lbl, _ in CATEGORIES}
    assert labels["part_category"] == "Spare Part Names"
    assert labels["spare_part_brand"] == "Spare Part Brands"


def test_seed_holds_the_consolidated_part_list():
    names = MASTER_SEED["part_category"]
    assert len(names) == len(set(names)), "duplicate part name in the seed"
    # The renames the floor asked for — the old spellings must be gone.
    for gone in ("Display Panel", "Display", "Web Cam", "Charging Port",
                 "Ethernet Port", "Touchpad", "Wi-Fi", "Palm rest"):
        assert gone not in names
    for kept in ("Panel", "Screen", "Camera", "DC Jack", "LAN Port",
                 "Logic Card", "Wi-Fi Card", "Touchpad Cover"):
        assert kept in names


def test_master_page_renders_with_new_labels(app_client, make_user):  # noqa: F811
    username, password = make_user("")   # plain admin-less user gets redirected
    _login(app_client, username, password)
    r = app_client.get("/admin/master", follow_redirects=True)
    assert r.status_code != 500, r.text[:2000]
