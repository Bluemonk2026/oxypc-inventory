""""Failed from Final QC" badge (Production Manager, L1/L2, Stress Test,
Cosmetic Received) gets an info icon next to it (2026-09-03) showing the
tag's Fail Note (Device.fqc_final_notes, set on the Final QC fail form —
see templates/cosmetic/final_qc.html) as a native Bootstrap tooltip. Falls
back to a placeholder message when no note was recorded (the pre-2026-09-03
required-field gap — see test_final_qc_required_field_validation.py).

All four tables are client-side DataTables (every row already in the DOM
at load, no ajax/serverSide), so a single page-load
`document.querySelectorAll('[data-bs-toggle="tooltip"]')` init correctly
covers every row on every page, not just the first.
"""
import pathlib

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)

FILES = [
    ("cosmetic", "received.html"),
    ("lots", "trc_production.html"),
    ("qc", "list.html"),
    ("repair", "l1.html"),
]


def _read(folder, name):
    return (pathlib.Path(ROOT) / "templates" / folder / name).read_text(encoding="utf-8")


def test_every_page_has_the_fail_note_info_icon_next_to_the_badge():
    for folder, name in FILES:
        src = _read(folder, name)
        block = src[src.index('<span class="badge bg-danger">Failed from Final QC</span>'):][:300]
        assert 'data-bs-toggle="tooltip"' in block, (folder, name)
        assert "bi-info-circle" in block, (folder, name)
        assert "device.fqc_final_notes or 'No fail note recorded'" in block, (folder, name)


def test_every_page_initializes_bootstrap_tooltips():
    for folder, name in FILES:
        src = _read(folder, name)
        assert "new bootstrap.Tooltip(el)" in src, (folder, name)
