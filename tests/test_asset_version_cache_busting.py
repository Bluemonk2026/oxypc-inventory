"""Regression: every /static/... asset tagged with the ?v={{ ASSET_VERSION }}
cache-busting stamp in templates/base.html must also be one of the files
templates_config._VERSIONED_ASSETS derives that version number from —
otherwise editing that asset alone never moves ASSET_VERSION, and any
browser that already cached it under the unchanged ?v=N URL keeps serving
the stale copy indefinitely, even across server restarts.

Found 2026-09-03: static/js/global-table.js was tagged with ?v=ASSET_VERSION
in base.html but missing from _VERSIONED_ASSETS. Symptom in the field: the
frozen-column header (position:sticky, added to global-table.js after some
browsers had already cached an older copy) scrolled away like a normal
column in one browser but stayed pinned in another — both hitting the same
deployed HEAD. Looked like a cross-browser position:sticky gap; was really
a stale-cache gap in this version-computation list.
"""
import pathlib
import re

import templates_config

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _versioned_asset_paths_in_base_html():
    src = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    # Matches href="/static/css/app.css?v={{ ASSET_VERSION }}" and
    # src="/static/js/global-table.js?v={{ ASSET_VERSION }}" alike.
    hits = re.findall(r'/static/([^"\']+)\?v=\{\{\s*ASSET_VERSION\s*\}\}', src)
    assert hits, "expected at least one ?v={{ ASSET_VERSION }}-tagged asset in base.html"
    return [ROOT / "static" / rel for rel in hits]


def test_every_asset_version_tagged_file_feeds_the_version_number():
    tagged = _versioned_asset_paths_in_base_html()
    versioned = {pathlib.Path(p).resolve() for p in templates_config._VERSIONED_ASSETS}
    missing = [p for p in tagged if p.resolve() not in versioned]
    assert not missing, (
        "these assets carry the ?v=ASSET_VERSION cache-bust stamp in base.html "
        "but are missing from templates_config._VERSIONED_ASSETS, so editing "
        "them alone never busts a browser's cache: "
        + ", ".join(str(p) for p in missing)
    )


def test_global_table_js_specifically_feeds_the_version_number():
    # The exact file this was found on — kept as its own explicit assertion
    # so a future refactor of _VERSIONED_ASSETS can't silently drop it again
    # without a named test failing.
    versioned = {pathlib.Path(p).resolve() for p in templates_config._VERSIONED_ASSETS}
    expected = (ROOT / "static" / "js" / "global-table.js").resolve()
    assert expected in versioned


def test_multiselect_filter_js_is_tagged_and_feeds_the_version_number():
    # 2026-09-18: same stale-cache gap, same shape — the dropdown-positioning
    # fix landed in this file, but its <script src> in
    # templates/workid_status/list.html had no ?v= stamp (this script tag
    # lives on a per-page template, not base.html, so the general scan above
    # never covered it). A browser that had already loaded the old copy kept
    # running it after the server-side deploy, so the Stage filter dropdown
    # looked unfixed even though the code shipped correctly.
    src = (ROOT / "templates" / "workid_status" / "list.html").read_text(encoding="utf-8")
    assert '/static/js/multiselect-filter.js?v={{ ASSET_VERSION }}' in src
    versioned = {pathlib.Path(p).resolve() for p in templates_config._VERSIONED_ASSETS}
    expected = (ROOT / "static" / "js" / "multiselect-filter.js").resolve()
    assert expected in versioned
