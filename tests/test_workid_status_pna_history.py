"""WorkID Status — PNA History: parts that were PNA while a WorkID was open."""
import types
from datetime import datetime

import routers.workid_status as ws


def _p(name, marked, cleared=None, by="eng1", src="parts_consumption", cby="eng2"):
    return types.SimpleNamespace(
        part_name=name, marked_by=by, marked_at=marked, source=src,
        is_active=cleared is None, cleared_at=cleared,
        cleared_by=cby if cleared else None)


START = datetime(2026, 10, 5, 9, 0)
END = datetime(2026, 10, 5, 17, 0)


def test_part_marked_during_workid_is_listed_with_who_and_when():
    h = ws._pna_history_lines([_p("Keyboard", datetime(2026, 10, 5, 10, 0))], START, END)
    assert len(h) == 1
    assert h[0]["part"] == "Keyboard" and h[0]["source"] == "L1/L2"
    assert h[0]["marked_by"] == "eng1" and h[0]["marked_at"] == "05-10-2026 10:00"
    assert h[0]["active"] is True and h[0]["cleared_at"] == ""


def test_l3l4_source_and_cleared_details():
    h = ws._pna_history_lines(
        [_p("Battery", datetime(2026, 10, 5, 10, 0), datetime(2026, 10, 5, 12, 30), src="l3l4")],
        START, END)
    assert h[0]["source"] == "L3/L4" and h[0]["active"] is False
    assert h[0]["cleared_by"] == "eng2" and h[0]["cleared_at"] == "05-10-2026 12:30"


def test_events_outside_the_workid_window_are_excluded():
    before = _p("Fan", datetime(2026, 10, 1, 9, 0), datetime(2026, 10, 4, 9, 0))   # cleared before start
    after = _p("Screen", datetime(2026, 10, 6, 9, 0))                              # marked after end
    spanning = _p("Hinge", datetime(2026, 10, 1, 9, 0))                            # still PNA through the window
    h = ws._pna_history_lines([before, after, spanning], START, END)
    assert [x["part"] for x in h] == ["Hinge"]


def test_ongoing_workid_has_open_ended_window():
    h = ws._pna_history_lines([_p("Fan", datetime(2026, 12, 1, 9, 0))], START, None)
    assert [x["part"] for x in h] == ["Fan"]


def test_text_for_csv():
    lines = ws._pna_history_lines(
        [_p("Keyboard", datetime(2026, 10, 5, 10, 0)),
         _p("Battery", datetime(2026, 10, 5, 11, 0), datetime(2026, 10, 5, 12, 0), src="l3l4")],
        START, END)
    t = ws._pna_history_text(lines)
    assert "Keyboard (L1/L2): marked by eng1 05-10-2026 10:00; still PNA" in t
    assert "Battery (L3/L4): marked by eng1 05-10-2026 11:00; cleared by eng2 05-10-2026 12:00" in t
    assert " | " in t
    assert ws._pna_history_text([]) == ""
