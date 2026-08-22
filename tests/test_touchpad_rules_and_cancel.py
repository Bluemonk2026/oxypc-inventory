"""Touchpad / Logic Card required-rules, their order, and the cancelled-request
regression that left an engineer unable to re-raise a request.
"""
import inspect

import pytest

from services.parts_required import compute_required, MAIN, ADDITIONAL
from models.master import MASTER_SEED


class _IQC:
    """Only the three fields the two rules read."""
    def __init__(self, working=None, missing=None, logicboard=None):
        self.touchpad_working = working
        self.touchpad_missing = missing
        self.touchpad_logicboard = logicboard

    def __getattr__(self, _name):        # every other IQC field reads as None
        return None


def _req(iqc):
    return {r["label"]: r["required"] for r in compute_required(iqc, None)}


@pytest.mark.parametrize("working,missing,expected", [
    ("No",  "No",  True),    # not working
    ("Yes", "Yes", True),    # missing
    ("No",  "Yes", True),    # both
    ("Yes", "No",  False),   # healthy
])
def test_touchpad_rule(working, missing, expected):
    assert _req(_IQC(working, missing))["Touchpad"] is expected


def test_touchpad_blank_is_not_required():
    """18,476 of 26,207 live IQC rows never had touchpad_working filled.
    Treating blank as unverified flagged Touchpad on 70% of tags on missing
    data alone, which is noise rather than a signal Stores can act on."""
    assert _req(_IQC(None, None))["Touchpad"] is False
    assert _req(_IQC("", ""))["Touchpad"] is False


@pytest.mark.parametrize("logicboard,expected", [
    ("Yes", True), ("No", False), (None, False), ("", False),
])
def test_logic_card_rule(logicboard, expected):
    assert _req(_IQC("Yes", "No", logicboard))["Logic Card"] is expected


def test_the_two_rules_are_independent():
    """They read different IQC fields, which is why they are two rows."""
    both = _req(_IQC("No", "No", "Yes"))
    assert both["Touchpad"] is True and both["Logic Card"] is True
    neither = _req(_IQC("Yes", "No", "No"))
    assert neither["Touchpad"] is False and neither["Logic Card"] is False


def test_logic_card_sits_after_touchpad_in_main():
    rows = compute_required(None, None)
    labels = [r["label"] for r in rows]
    assert labels[labels.index("Touchpad") + 1] == "Logic Card"
    assert labels[labels.index("Touchpad") - 1] == "Motherboard"
    by_label = {r["label"]: r for r in rows}
    assert by_label["Logic Card"]["section"] == MAIN
    assert by_label["Click Button"]["section"] == ADDITIONAL


def test_seed_and_matrix_stay_in_step():
    assert [r["label"] for r in compute_required(None, None)] == MASTER_SEED["part_category"]


def test_cancelled_request_frees_the_action_buttons():
    """Cancelling a request used to pin the row to a 'cancelled' badge with no
    buttons, so the part could never be requested again on that tag."""
    from routers import devices

    src = inspect.getsource(devices.device_detail)
    block = src.split("req_by_part = {}", 1)[1].split("consumed_by_part", 1)[0]
    assert 'r.status == "cancelled"' in block
    assert "continue" in block
