"""Stress Test page (templates/qc/list.html) already had a live-updating
count next to "Show N entries" (#qcAwaitingCount, updated via drawCallback) —
it just wasn't styled as the warning-badge convention used everywhere else
(L1/L2, the 8 cosmetic pages, All Tags). Style-only change.
"""
import pathlib

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def test_qc_awaiting_count_uses_warning_badge_style():
    src = open(pathlib.Path(ROOT) / "templates" / "qc" / "list.html", encoding="utf-8").read()
    assert 'id="qcAwaitingCount" class="badge bg-warning text-dark ms-2"' in src
    assert 'id="qcAwaitingCount" class="text-muted small ms-2"' not in src
    # Still updates on every draw — this was already correct, just unstyled.
    assert "drawCallback: function(){" in src
    assert "updateAwaitingCount(this.api());" in src
