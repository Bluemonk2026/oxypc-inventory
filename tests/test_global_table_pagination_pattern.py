"""Global Table pagination page-number pattern (static/js/global-table.js,
2026-09-03): near either end shows only 2 pages before the ellipsis (down
from DataTables' own default of 5), and away from both ends shows just the
current page between two ellipses — no "current-1 / current+1" neighbors.

A custom pager ($.fn.dataTable.ext.pager.gtable_numbers), not a tweak to
DataTables' built-in numbers_length: that single setting drives both the
edge-page count and the middle-window size together, and the only value
giving edge-count 2 (numbers_length=4) has a real gap — landing exactly on
page 3 of a large table falls in DataTables' own "near start" branch, whose
window ([1,2]) doesn't include page 3, so the active page is never
highlighted. Confirmed live before switching to the custom pager (page
index 2, i.e. human page 3, had NO .active button at all with
numbers_length=4). The custom pager switches to the "current page alone"
pattern as soon as the current page falls outside the edge window, instead
of at DataTables' fixed page-index threshold, so page 3 correctly renders
as "1 … 3 … last" with 3 active.

Verified live on /devices (1968 pages): page 1 -> "1 2 … 1968"; page 2 ->
"1 2 … 1968"; page 3 -> "1 … 3 … 1968" (3 active — the fixed edge case);
page 51 -> "1 … 51 … 1968"; page 1968 (last) -> "1 … 1967 1968"; page 1967
-> "1 … 1967 1968"; page 1966 -> "1 … 1966 … 1968".
"""
import pathlib

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _js():
    return (pathlib.Path(ROOT) / "static" / "js" / "global-table.js").read_text(encoding="utf-8")


def test_custom_pager_is_registered_and_wired_in():
    js = _js()
    assert "$.fn.dataTable.ext.pager.gtable_numbers = function (page, pages) {" in js
    assert "pagingType: 'gtable_numbers'," in js


def test_leading_and_trailing_edge_show_two_pages_not_five():
    js = _js()
    block = js[js.index("gtable_numbers = function"):][:1200]
    assert "var LEADING = 2;" in block


def test_middle_pattern_has_no_neighbors_around_current():
    js = _js()
    block = js[js.index("gtable_numbers = function"):][:1200]
    assert "nums = [0, 'ellipsis', page, 'ellipsis', pages - 1];" in block
