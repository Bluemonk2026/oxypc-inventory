"""Shared PNA (Part Not Available) lookups.

A tag is "in PNA" when it has at least one active DevicePNAPart row. The
Production Manager PNA summary (routers/stock.py trc_production_pna_summary)
only lists tags in PNA_SUMMARY_STAGES, so anything that says "same as the PNA
summary" must apply that stage filter on top of this lookup.
"""
import uuid
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.device import DeviceStage
from models.pna_part import DevicePNAPart

PNA_SUMMARY_STAGES = (DeviceStage.l1, DeviceStage.l2, DeviceStage.l3)

# asyncpg caps a statement at 32767 bound parameters.
_CHUNK = 20000


async def active_pna_parts(
    db: AsyncSession, device_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[DevicePNAPart]]:
    """Map device_id -> active PNA part rows (ordered by part name).

    Devices with no active PNA part are absent from the result.
    """
    ids = list(device_ids)
    out: dict[uuid.UUID, list[DevicePNAPart]] = {}
    for i in range(0, len(ids), _CHUNK):
        chunk = ids[i : i + _CHUNK]
        rows = (
            await db.execute(
                select(DevicePNAPart)
                .where(
                    DevicePNAPart.device_id.in_(chunk),
                    DevicePNAPart.is_active == True,  # noqa: E712
                )
                .order_by(DevicePNAPart.part_name)
            )
        ).scalars().all()
        for r in rows:
            out.setdefault(r.device_id, []).append(r)
    return out


async def pna_history(
    db: AsyncSession, device_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[DevicePNAPart]]:
    """Map device_id -> EVERY PNA part row, active or cleared, oldest mark first.

    Unmarking only flips is_active (see DevicePNAPart), so cleared rows are the
    history of what was once PNA. Re-marking a cleared part reopens its row, so
    each part contributes its latest mark/clear cycle."""
    ids = list(device_ids)
    out: dict[uuid.UUID, list[DevicePNAPart]] = {}
    for i in range(0, len(ids), _CHUNK):
        chunk = ids[i : i + _CHUNK]
        rows = (
            await db.execute(
                select(DevicePNAPart)
                .where(DevicePNAPart.device_id.in_(chunk))
                .order_by(DevicePNAPart.marked_at, DevicePNAPart.part_name)
            )
        ).scalars().all()
        for r in rows:
            out.setdefault(r.device_id, []).append(r)
    return out
