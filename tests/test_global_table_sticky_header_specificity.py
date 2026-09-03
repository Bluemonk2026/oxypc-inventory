"""Frozen-column sticky header CSS specificity (static/css/app.css), found
2026-09-03 and reported as "works with 2 frozen columns but not 1":

DataTables' own bootstrap5 CSS sets `position: relative` on every sortable
header cell for its sort-arrow icon (table.dataTable thead>tr>th.sorting,
specificity 0,2,4). The first-frozen-column rule
(.gtable-scroll-wrap thead th:first-child, specificity 0,2,2) lost to it
whenever column 1 was actually sortable — true on every page except a
checkbox-first one, where DataTables applies "sorting_disabled" instead
(a class that vendor rule doesn't target). The second-frozen-column rule
happened to survive only because its extra [data-freeze-cols="2"]
attribute selector (0,3,1) outranks the vendor rule — a coincidence, not a
guarantee. Nothing to do with browser engine: this always loses in every
browser once column 1 is sortable. Fixed with !important on both rules so
neither depends on out-specificity-ing a third-party stylesheet.
"""
import pathlib

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _css():
    return (pathlib.Path(ROOT) / "static" / "css" / "app.css").read_text(encoding="utf-8")


def test_first_frozen_column_sticky_is_important():
    css = _css()
    rule = css[css.index(".gtable-scroll-wrap td:first-child,"):][:250]
    assert "position: sticky !important;" in rule


def test_second_frozen_column_sticky_is_important():
    css = _css()
    rule = css[css.index('.gtable-scroll-wrap[data-freeze-cols="2"] td:nth-child(2),'):][:250]
    assert "position: sticky !important;" in rule
