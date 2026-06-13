"""
Trash — soft-delete for Lots and Devices.
Trashed items are hidden from main lists and shown here.
Admin can restore or request permanent deletion.
"""
from templates_config import templates
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

router = APIRouter(prefix="/trash", tags=["trash"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager)


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
