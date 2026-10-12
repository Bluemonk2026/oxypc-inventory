"""Block Tags page: New Block Tag modal scan-to-select + selected count, and the
Upload (blockid, tag_number) -> select-matching-rows feature (2026-10-12)."""
import asyncio
import io
import json
import pathlib
import types
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = (ROOT / "templates" / "block_tags" / "list.html").read_text(encoding="utf-8")


# ── Template wiring ──────────────────────────────────────────────────────────
def test_search_label_shows_live_selected_count():
    assert 'id="nbSelCount"' in TEMPLATE
    assert "Search Tags" in TEMPLATE and "selected:" in TEMPLATE
    # renderNbSelected is what every add/remove path calls, so the count follows it
    body = TEMPLATE.split("function renderNbSelected()")[1].split("}\n", 1)[0]
    assert "nbSelCount" in body and "nbSelectedTags.size" in body


def test_exact_match_autoselects_clears_and_refocuses():
    assert "async function nbSearch(" in TEMPLATE
    # exact (case-insensitive) barcode match is selected without a click ...
    assert "toUpperCase() === want" in TEMPLATE
    assert "nbSelectedTags.set(exact.id, exact)" in TEMPLATE
    # ... then the box is cleared and refocused for the next scan
    after = TEMPLATE.split("nbSelectedTags.set(exact.id, exact)")[1][:600]
    assert "input.value = ''" in after and "input.focus()" in after
    # scanner flows: debounce on input AND Enter key
    assert "e.key !== 'Enter'" in TEMPLATE
    assert "setTimeout(function () { nbSearch(q, false); }, 200)" in TEMPLATE
    # modal focuses the box when opened
    assert "shown.bs.modal" in TEMPLATE and "getElementById('nbTagSearch').focus()" in TEMPLATE


def test_not_found_hint_is_non_blocking():
    assert 'id="nbScanHint"' in TEMPLATE
    assert "not found" in TEMPLATE
    assert "alert(" not in TEMPLATE.split("async function nbSearch(")[1].split("function renderNbSelected")[0]


def test_upload_button_and_client_wiring():
    assert 'id="blockUploadBtn"' in TEMPLATE and "bi-upload" in TEMPLATE
    assert 'id="blockUploadFile"' in TEMPLATE and ".xlsx" in TEMPLATE and ".csv" in TEMPLATE
    assert "/block-tags/upload-select" in TEMPLATE
    # matches go into the cross-page selection set, then the bulk buttons refresh
    js = TEMPLATE.split("getElementById('blockUploadFile').addEventListener('change'")[1]
    assert "selectedBlockIds.add(id)" in js and "updateBlockExportBtn()" in js
    assert "not_found" in js and 'id="blockUploadMsg"' in TEMPLATE
    assert "csrf_token" in js


def test_upload_select_route_registered_before_dynamic_routes():
    from routers.block_tags import router
    paths = [(r.path, sorted(r.methods)) for r in router.routes if hasattr(r, "methods")]
    assert ("/block-tags/upload-select", ["POST"]) in paths


# ── Parser ───────────────────────────────────────────────────────────────────
def test_parser_accepts_header_spellings_and_dedupes():
    from routers.block_tags import parse_block_tag_upload
    for head in ("blockid,tag_number", "Block ID,Tag Number", "block_id,barcode", "BlockID;Tag No"):
        delim = ";" if ";" in head else ","
        raw = (head + "\n01102026-SHELF-0001{d}T100\n01102026-SHELF-0001{d}t100\n"
               "01102026-SHELF-0002{d}T200\n,T300\n").format(d=delim).encode()
        pairs, errors = parse_block_tag_upload("x.csv", raw)
        assert pairs == [("01102026-SHELF-0001", "T100"), ("01102026-SHELF-0002", "T200")], head
        assert len(errors) == 1 and "Row 5" in errors[0]


def test_parser_rejects_missing_columns_and_empty():
    from routers.block_tags import parse_block_tag_upload
    assert parse_block_tag_upload("x.csv", b"tag_number\nT1\n")[0] == []
    assert "blockid" in parse_block_tag_upload("x.csv", b"tag_number\nT1\n")[1][0]
    assert parse_block_tag_upload("x.csv", b"")[0] == []


def test_parser_reads_xlsx():
    import openpyxl
    from routers.block_tags import parse_block_tag_upload
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Block ID", "Tag Number", "Notes"])
    ws.append(["B-1", "T1", "x"])
    ws.append(["B-1", 22, None])        # numeric tag cell
    ws.append([None, None, None])
    buf = io.BytesIO()
    wb.save(buf)
    pairs, errors = parse_block_tag_upload("pairs.xlsx", buf.getvalue())
    assert pairs == [("B-1", "T1"), ("B-1", "22")] and errors == []


# ── Endpoint matching (fake session: no DB needed) ───────────────────────────
class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, stmt):
        return _FakeResult(self._rows)


def _call_upload(filename, raw, db_rows):
    from routers.block_tags import upload_select
    f = types.SimpleNamespace(filename=filename, read=None)

    async def _read():
        return raw
    f.read = _read
    resp = asyncio.run(upload_select(file=f, db=_FakeDB(db_rows), current_user=None))
    return resp.status_code, json.loads(resp.body)


def test_upload_select_matches_blockid_and_tag_pairs_case_insensitively():
    i1, i2, i3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db_rows = [
        (i1, "01102026-SHELF-0001", "T100"),
        (i2, "01102026-SHELF-0001", "T101"),
        (i3, "01102026-SHELF-0002", "T100"),   # same tag, different block: only matches its own pair
    ]
    raw = (b"blockid,tag_number\n"
           b"01102026-shelf-0001,t100\n"       # matches i1 (case-insensitive)
           b"01102026-SHELF-0002,T101\n"       # tag exists but under another block -> not found
           b"01102026-SHELF-0009,T999\n")      # nothing
    status, body = _call_upload("pairs.csv", raw, db_rows)
    assert status == 200 and body["ok"] is True
    assert body["ids"] == [str(i1)]
    assert body["matched"] == 1 and body["total"] == 3
    assert body["not_found"] == ["01102026-SHELF-0002 / T101", "01102026-SHELF-0009 / T999"]


def test_upload_select_bad_file_is_400():
    status, body = _call_upload("bad.csv", b"foo,bar\n1,2\n", [])
    assert status == 400 and body["ok"] is False and "blockid" in body["error"]
