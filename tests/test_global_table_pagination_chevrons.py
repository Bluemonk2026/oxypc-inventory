"""Global Table pagination (static/js/global-table.js, 2026-09-03):
Previous/Next replaced with chevron icons (bi-chevron-left/right) — the
page-number links themselves (1, 2, ..., ellipsis, last page) are
DataTables' own default numbers renderer, untouched by this change.

Verified live on /devices: page 1 renders "‹ 1 2 3 4 5 … 1968 ›"; jumping
to page 51 of ~1968 renders "‹ 1 … 50 51 52 … 1968 ›" with the current
page centered between ellipses on both sides — both chevrons still
navigate correctly.
"""
import pathlib

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _js():
    return (pathlib.Path(ROOT) / "static" / "js" / "global-table.js").read_text(encoding="utf-8")


def test_paginate_language_uses_chevron_icons_not_text():
    js = _js()
    assert "previous: '<i class=\"bi bi-chevron-left\"></i>'" in js
    assert "next: '<i class=\"bi bi-chevron-right\"></i>'" in js


def test_paginate_override_is_nested_under_the_base_language_object():
    # Must live inside `language: {...}` so initGlobalTable's deep-merge
    # ($.extend(true, ...)) combines it with a caller's own language
    # overrides instead of one replacing the other wholesale.
    js = _js()
    lang_block = js[js.index("language: {"):js.index("paginate: {") + 400]
    assert "search: ''" in lang_block
    assert "paginate: {" in lang_block
