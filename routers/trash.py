"""
Trash — soft-delete for Lots and Devices.
Trashed items are hidden from main lists and shown here.
Admin can restore or request permanent deletion.
"""
from templates_config import templates
import logging
import uuid as _uuid
from datetime import datetime
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from models.user import User, UserRole
from models.lot import Lot
from models.device import Device, DeviceStage
from auth.dependencies import require_roles, verify_csrf
from services.audit_engine import audit
from utils.fk_purge import purge_references

router = APIRouter(prefix="/trash", tags=["trash"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager)

_log = logging.getLogger("oxypc.errors")


def _confirmed(typed: str, expected: str) -> bool:
    """Permanent delete is the only action in the app with no undo, so the
    button alone is not enough — the operator has to type the lot number or tag
    number back. Case- and space-insensitive, because the point is deliberate
    intent, not transcription accuracy."""
    return (typed or "").strip().casefold() == (expected or "").strip().casefold()


@router.get("", response_class=HTMLResponse)
async def trash_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Show all trashed lots and trashed devices."""
    trashed_lots = (await db.execute(
        select(Lot).where(Lot.is_trashed == True).order_by(Lot.trashed_at.desc())
    )).scalars().all()

    trashed_devices = (await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.is_trashed == True)
        .order_by(Device.trashed_at.desc())
    )).all()

    return templates.TemplateResponse("trash/index.html", {
        "request": request,
        "current_user": current_user,
        "trashed_lots": trashed_lots,
        "trashed_devices": trashed_devices,
    })


# ── Lots ─────────────────────────────────────────────────────────────────────

@router.post("/lots/{lot_id}", response_class=HTMLResponse)
async def trash_lot(
    lot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Move a lot to trash."""
    try:
        uid = _uuid.UUID(lot_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Lot not found")

    lot = (await db.execute(select(Lot).where(Lot.id == uid))).scalar_one_or_none()
    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")

    lot.is_trashed = True
    lot.trashed_at = app_now()
    await db.commit()
    return RedirectResponse(url="/lots?success=Lot+moved+to+trash", status_code=302)


@router.post("/lots/{lot_id}/restore", response_class=HTMLResponse)
async def restore_lot(
    lot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Restore a lot from trash."""
    try:
        uid = _uuid.UUID(lot_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Lot not found")

    lot = (await db.execute(select(Lot).where(Lot.id == uid))).scalar_one_or_none()
    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")

    lot.is_trashed = False
    lot.trashed_at = None
    await db.commit()
    return RedirectResponse(url="/trash?success=Lot+restored", status_code=302)


@router.post("/lots/{lot_id}/delete", response_class=HTMLResponse)
async def delete_lot_forever(
    lot_id: str,
    request: Request,
    confirm: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Permanently delete a trashed lot, its devices, and everything that
    references them.

    Only a lot already IN the trash can be deleted here, so nothing can be
    destroyed straight off a working list — it has to be trashed first, seen in
    this page, and then confirmed by name. The cascade comes from the database's
    own foreign keys at request time (utils/fk_purge) rather than a hand-kept
    table list, which is what stopped 22 of 287 production lots from deleting
    when the list fell behind the schema.
    """
    from urllib.parse import quote
    from sqlalchemy import text as _text
    from sqlalchemy.exc import IntegrityError

    try:
        uid = _uuid.UUID(lot_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Lot not found")

    lot = (await db.execute(select(Lot).where(Lot.id == uid))).scalar_one_or_none()
    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")
    if not lot.is_trashed:
        return RedirectResponse(
            url="/trash?error=" + quote("Only a lot already in Trash can be deleted permanently"),
            status_code=302)
    if not _confirmed(confirm, lot.lot_number):
        return RedirectResponse(
            url="/trash?error=" + quote(f"Type {lot.lot_number} exactly to confirm deletion"),
            status_code=302)

    lot_number = lot.lot_number
    params = {"lot_id": str(uid)}

    device_ids = (await db.execute(
        _text("SELECT id FROM devices WHERE lot_id = :lot_id"), params)).scalars().all()
    purged = await purge_references(db, "devices", device_ids)
    if device_ids:
        await db.execute(_text("DELETE FROM devices WHERE lot_id = :lot_id"), params)
        purged.append(f"deleted {len(device_ids)} devices")
    purged += await purge_references(db, "lots", [uid])

    # Audited before the row goes, so the trail survives the record.
    await audit(
        db, action="LOT_DELETED", user=current_user,
        table_name="lots", record_id=str(uid),
        new_value={"lot_number": lot_number, "supplier": lot.supplier_name,
                   "buying_price": str(lot.buying_price), "qty": lot.qty,
                   "from": "trash", "deleted_by": current_user.username,
                   "cascade": purged},
        request=request,
    )

    await db.delete(lot)
    try:
        await db.commit()
    except IntegrityError as e:
        # Something the purge could not resolve. Leave the lot intact and name
        # the constraint instead of returning a 500 the user cannot act on.
        await db.rollback()
        _log.exception("permanent lot delete blocked by a foreign key: %s", lot_number)
        detail = getattr(getattr(e, "orig", None), "constraint_name", None) or "a related record"
        return RedirectResponse(
            url="/trash?error=" + quote(
                f"{lot_number} could not be deleted — still referenced by {detail}"),
            status_code=302)

    return RedirectResponse(
        url="/trash?success=" + quote(
            f"{lot_number} and its {len(device_ids)} device(s) deleted permanently"),
        status_code=302)


# ── Devices ───────────────────────────────────────────────────────────────────

@router.post("/devices/{barcode}", response_class=HTMLResponse)
async def trash_device(
    barcode: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Move a device to trash."""
    device = (await db.execute(
        select(Device).where(Device.barcode == barcode)
    )).scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    device.is_trashed = True
    device.trashed_at = app_now()
    await db.commit()
    return RedirectResponse(url="/devices?success=Device+moved+to+trash", status_code=302)


@router.post("/bulk/devices", response_class=HTMLResponse)
async def trash_devices_bulk(
    request: Request,
    barcodes: list[str] = Form(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Bulk soft-delete (move to Trash) the selected devices. Restorable from /trash."""
    barcodes = [b for b in (barcodes or []) if b]
    if not barcodes:
        return RedirectResponse(url="/devices?error=No+devices+selected", status_code=302)
    devices = (await db.execute(
        select(Device).where(Device.barcode.in_(barcodes), Device.is_trashed == False)
    )).scalars().all()
    now = app_now()
    for d in devices:
        d.is_trashed = True
        d.trashed_at = now
    await db.commit()
    return RedirectResponse(
        url=f"/devices?success={len(devices)}+device(s)+moved+to+trash", status_code=302)


@router.post("/devices/{barcode}/delete", response_class=HTMLResponse)
async def delete_device_forever(
    barcode: str,
    request: Request,
    confirm: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Permanently delete one trashed device and everything referencing it.

    Same shape as the lot delete above: trashed-only, confirmed by tag number,
    cascade read from the FK catalog. Its IQC inspection, stage movements,
    parts consumption and scan lines go with it; records that merely mention
    the device are unlinked, not destroyed.
    """
    from urllib.parse import quote
    from sqlalchemy.exc import IntegrityError

    device = (await db.execute(
        select(Device).where(Device.barcode == barcode)
    )).scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not device.is_trashed:
        return RedirectResponse(
            url="/trash?error=" + quote("Only a device already in Trash can be deleted permanently"),
            status_code=302)
    if not _confirmed(confirm, device.barcode):
        return RedirectResponse(
            url="/trash?error=" + quote(f"Type {device.barcode} exactly to confirm deletion"),
            status_code=302)

    tag = device.barcode
    purged = await purge_references(db, "devices", [device.id])

    await audit(
        db, action="DEVICE_DELETED", user=current_user,
        table_name="devices", record_id=str(device.id),
        new_value={"barcode": tag, "brand": device.brand, "model": device.model,
                   "grade": device.grade.value if device.grade else None,
                   "stage": device.current_stage.value if device.current_stage else None,
                   "lot_id": str(device.lot_id) if device.lot_id else None,
                   "from": "trash", "deleted_by": current_user.username,
                   "cascade": purged},
        request=request,
    )

    await db.delete(device)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        _log.exception("permanent device delete blocked by a foreign key: %s", tag)
        detail = getattr(getattr(e, "orig", None), "constraint_name", None) or "a related record"
        return RedirectResponse(
            url="/trash?error=" + quote(
                f"{tag} could not be deleted — still referenced by {detail}"),
            status_code=302)

    return RedirectResponse(
        url="/trash?success=" + quote(f"{tag} deleted permanently"), status_code=302)


@router.post("/devices/{barcode}/restore", response_class=HTMLResponse)
async def restore_device(
    barcode: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Restore a device from trash."""
    device = (await db.execute(
        select(Device).where(Device.barcode == barcode)
    )).scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    device.is_trashed = False
    device.trashed_at = None
    await db.commit()
    return RedirectResponse(url="/trash?success=Device+restored", status_code=302)
