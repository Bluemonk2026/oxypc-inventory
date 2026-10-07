"""All Inventory export: trailing "PNA" and "Stock" columns.

PNA   = "Yes" only when the tag is in the Production Manager PNA summary scope
        (active PNA part AND stage in l1/l2/l3 AND is_active AND not trashed).
Stock = only for ready_to_sale tags: sub-lot present -> "As-Is Lot", else
        "Ready for Sale"; blank for every other stage.

Calls routers.devices._export_rows directly with transient Device objects and
a stubbed session, so no database is touched.
"""
import asyncio
import csv
import io
import uuid
from types import SimpleNamespace

from models.device import Device, DeviceStage
from routers import devices as devices_router
from routers.devices import _EXPORT_HEADER, _export_rows, _pna_label, _stock_label


def _dev(barcode, stage, sub_lot=None, is_active=True, is_trashed=False):
    return Device(
        id=uuid.uuid4(), barcode=barcode, current_stage=stage,
        sub_lot_number=sub_lot, is_active=is_active, is_trashed=is_trashed,
    )


class _EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _StubDB:
    async def execute(self, *_a, **_k):
        return _EmptyResult()


def _run_export(monkeypatch, devices, pna_ids):
    async def fake_pna(_db, ids):
        return {i: [SimpleNamespace()] for i in ids if i in pna_ids}

    async def fake_locmap(_db, _ids):
        return {}

    monkeypatch.setattr("services.pna_lookup.active_pna_parts", fake_pna)
    monkeypatch.setattr(devices_router, "_build_location_map", fake_locmap)

    async def go():
        resp = await _export_rows(_StubDB(), [(d, "LOT-1") for d in devices])
        body = b""
        async for chunk in resp.body_iterator:
            body += chunk
        return body

    text = asyncio.run(go()).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    return rows[0], {r[0]: r for r in rows[1:]}


def test_header_ends_with_pna_and_stock():
    assert _EXPORT_HEADER[-2:] == ["PNA", "Stock"]
    assert _EXPORT_HEADER[-4:-2] == ["Created", "Updated"]


def test_stock_label_rules():
    assert _stock_label(_dev("A", DeviceStage.ready_to_sale)) == "Ready for Sale"
    assert _stock_label(_dev("B", DeviceStage.ready_to_sale, sub_lot="  ")) == "Ready for Sale"
    assert _stock_label(_dev("C", DeviceStage.ready_to_sale, sub_lot="SL-9")) == "As-Is Lot"
    assert _stock_label(_dev("D", DeviceStage.l2, sub_lot="SL-9")) == ""
    assert _stock_label(_dev("E", DeviceStage.iqc)) == ""


def test_pna_label_scope():
    ok = _dev("A", DeviceStage.l1)
    assert _pna_label(ok, {ok.id}) == "Yes"
    for stage in (DeviceStage.l2, DeviceStage.l3):
        d = _dev("S", stage)
        assert _pna_label(d, {d.id}) == "Yes"
    other_stage = _dev("B", DeviceStage.ready_to_sale)
    assert _pna_label(other_stage, {other_stage.id}) == "No"
    no_part = _dev("C", DeviceStage.l1)
    assert _pna_label(no_part, set()) == "No"
    inactive = _dev("D", DeviceStage.l1, is_active=False)
    assert _pna_label(inactive, {inactive.id}) == "No"
    trashed = _dev("E", DeviceStage.l1, is_trashed=True)
    assert _pna_label(trashed, {trashed.id}) == "No"


def test_export_rows_end_to_end_values(monkeypatch):
    pna_l2 = _dev("T-PNA-L2", DeviceStage.l2)
    l2_no_pna = _dev("T-L2-CLEAN", DeviceStage.l2)
    pna_other_stage = _dev("T-PNA-RTS", DeviceStage.ready_to_sale)          # PNA row, wrong stage
    rts_plain = _dev("T-RTS", DeviceStage.ready_to_sale)
    rts_sublot = _dev("T-RTS-SUB", DeviceStage.ready_to_sale, sub_lot="SL-1")
    iqc_dev = _dev("T-IQC", DeviceStage.iqc)
    # l2_no_pna stands in for a device whose only PNA row is inactive: the
    # lookup (active_pna_parts) never returns it, so it is absent from pna_ids.
    pna_ids = {pna_l2.id, pna_other_stage.id}

    header, by_barcode = _run_export(
        monkeypatch,
        [pna_l2, l2_no_pna, pna_other_stage, rts_plain, rts_sublot, iqc_dev],
        pna_ids,
    )
    assert header[-2:] == ["PNA", "Stock"]
    pna_i, stock_i = header.index("PNA"), header.index("Stock")

    def cells(b):
        return by_barcode[b][pna_i], by_barcode[b][stock_i]

    assert cells("T-PNA-L2") == ("Yes", "")
    assert cells("T-L2-CLEAN") == ("No", "")
    assert cells("T-PNA-RTS") == ("No", "Ready for Sale")
    assert cells("T-RTS") == ("No", "Ready for Sale")
    assert cells("T-RTS-SUB") == ("No", "As-Is Lot")
    assert cells("T-IQC") == ("No", "")
    assert all(len(r) == len(header) for r in by_barcode.values())
