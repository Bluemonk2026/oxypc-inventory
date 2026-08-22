"""Aggregates "which spare parts does this lot need?" from IQC data.

Runs the same PARTS_MATRIX rules the device's Parts Consumption section uses
(services/parts_required.compute_required), so a Part Estimation quantity and
a Required=Yes badge on a device can never disagree.

The full Device / IQCInspection rows are far wider than the rules need, so the
queries here select only the columns PARTS_MATRIX reads and feed them to
compute_required through SimpleNamespace stand-ins. Keep _DEVICE_COLS and
_IQC_COLS in step with services/parts_required.PARTS_MATRIX — a rule that
reads a column not listed here would silently evaluate it as None.
"""
from types import SimpleNamespace

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.device import Device
from models.iqc_inspection import IQCInspection
from services.parts_required import PARTS_MATRIX, compute_required

_DEVICE_COLS = ("ram_gb", "storage_gb", "storage_type", "hdd_capacity_gb", "battery_health_pct")

_IQC_COLS = (
    "hdd_connector", "battery_present", "keyboard_working", "keyboard_key_missing",
    "status", "screen_broken", "screen_line", "screen_dot", "screen_flickering",
    "screen_missing", "screen_functional", "screen_hinge_broken", "speaker_status",
    "touchpad_working", "touchpad_missing", "wifi_status", "webcam_status",
    "port_hdmi", "port_usb_working", "port_audio_jack", "charging_port",
    "dvd_drive", "fan_working", "power_on",
    # Cosmetic panels — feed the Display Panel / Bazel Frame / Bottom Base /
    # Palm rest rows added to PARTS_MATRIX.
    "panel_a_broken", "panel_a_missing", "panel_a_dent",
    "panel_b_broken", "panel_b_missing", "panel_b_rubber_cut",
    "panel_c_broken", "panel_c_missing", "panel_c_dent",
    "panel_d_broken", "panel_d_missing", "panel_d_dent",
)

PART_LABELS = [row[0] for row in PARTS_MATRIX]


def _active(stmt):
    return stmt.where(Device.is_active == True, Device.is_trashed == False)  # noqa: E712


def _select_cols():
    cols = [Device.lot_id]
    cols += [getattr(Device, c) for c in _DEVICE_COLS]
    cols += [getattr(IQCInspection, c) for c in _IQC_COLS]
    return cols


def _split(row):
    """(lot_id, device stand-in, iqc stand-in) from one selected row."""
    n_dev = len(_DEVICE_COLS)
    lot_id = row[0]
    device = SimpleNamespace(**dict(zip(_DEVICE_COLS, row[1:1 + n_dev])))
    iqc_vals = row[1 + n_dev:]
    # A device with no inspection row joins as all-NULL. compute_required's own
    # _NullIQC handles that case, and passing None keeps the two paths identical.
    iqc = None if all(v is None for v in iqc_vals) else SimpleNamespace(**dict(zip(_IQC_COLS, iqc_vals)))
    return lot_id, device, iqc


async def required_counts_by_lot(db: AsyncSession) -> dict:
    """{lot_id: total number of Required=Yes part rows across the lot's tags}.

    One row per (device, required part) is counted, matching the Parts
    Consumption reading: 18 tags needing RAM contribute 18.
    """
    rows = (await db.execute(
        _active(select(*_select_cols()).outerjoin(IQCInspection, IQCInspection.device_id == Device.id))
    )).all()

    totals: dict = {}
    for row in rows:
        lot_id, device, iqc = _split(row)
        if lot_id is None:
            continue
        n = sum(1 for r in compute_required(iqc, device) if r["required"])
        if n:
            totals[lot_id] = totals.get(lot_id, 0) + n
    return totals


async def device_counts_by_lot(db: AsyncSession) -> dict:
    """{lot_id: count of active tags} — the Total Products column."""
    rows = (await db.execute(
        _active(select(Device.lot_id, func.count()).group_by(Device.lot_id))
    )).all()
    return {lot_id: n for lot_id, n in rows if lot_id is not None}


async def required_parts_for_lot(db: AsyncSession, lot_id,
                                 include_zero: bool = False) -> list[dict]:
    """[{part_name, qty}] for one lot, in PARTS_MATRIX order — the same order
    and the same names as Parts Consumption on Device Detail. qty = how many of
    the lot's tags need that part.

    include_zero=True keeps parts no tag needs, so the costing modal can show
    the full list with a 0 against them. The saved estimate still stores only
    the rows with a quantity: a zero line costs nothing and would just pad the
    workbook.
    """
    rows = (await db.execute(
        _active(select(*_select_cols())
                .outerjoin(IQCInspection, IQCInspection.device_id == Device.id))
        .where(Device.lot_id == lot_id)
    )).all()

    tally = {label: 0 for label in PART_LABELS}
    for row in rows:
        _lot, device, iqc = _split(row)
        for r in compute_required(iqc, device):
            if r["required"]:
                tally[r["label"]] += 1
    return [{"part_name": label, "qty": tally[label]} for label in PART_LABELS
            if include_zero or tally[label]]
