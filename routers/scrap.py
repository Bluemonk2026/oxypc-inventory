"""
Scrap Products — devices that were scrapped (typically from L3). Shows the L3
engineer who sent it to scrap, the device's P&L total cost, and Sell / View actions.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from templates_config import templates
from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement
from models.lot import Lot
from models.engines import DeviceCosting
from auth.dependencies import get_current_user, require_roles

router = APIRouter(tags=["scrap"])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager, UserRole.l3_engineer,
                        UserRole.sales, UserRole.sales_manager)


@router.get("/scrap-products", response_class=HTMLResponse)
async def scrap_products(request: Request, db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(allowed)):
    rows = (await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id, isouter=True)
        .where(Device.current_stage == DeviceStage.scrapped)
        .order_by(Device.updated_at.desc())
    )).all()
    device_ids = [d.id for d, _ in rows]

    # Amount = device P&L total cost (DeviceCosting); fallback to device_price * qty
    cost_map = {}
    received_map = {}
    if device_ids:
        for c in (await db.execute(
            select(DeviceCosting).where(DeviceCosting.device_id.in_(device_ids))
        )).scalars().all():
            cost_map[str(c.device_id)] = c.total_cost

        # L3 engineer who sent it to scrap = moved_by on the latest movement to 'scrapped'
        sub = (
            select(StageMovement.device_id, func.max(StageMovement.moved_at).label("latest"))
            .where(StageMovement.device_id.in_(device_ids),
                   StageMovement.to_stage == DeviceStage.scrapped)
            .group_by(StageMovement.device_id).subquery()
        )
        mv_rows = (await db.execute(
            select(StageMovement.device_id, StageMovement.moved_by, StageMovement.notes)
            .join(sub, (StageMovement.device_id == sub.c.device_id) &
                       (StageMovement.moved_at == sub.c.latest))
            .where(StageMovement.to_stage == DeviceStage.scrapped)
        )).all()
        for did, mb, nt in mv_rows:
            received_map[str(did)] = mb

    items = []
    for device, lot_number in rows:
        did = str(device.id)
        amount = cost_map.get(did)
        if amount is None and device.device_price:
            amount = device.device_price * (device.qty or 1)
        items.append({
            "barcode": device.barcode,
            "brand": device.brand or "—",
            "model": device.model or "—",
            "grade": device.grade.value if device.grade else "—",
            "received_user": received_map.get(did) or "—",
            "amount": amount,
            "updated_at": device.updated_at,
            "notes": device.notes or "",
        })

    return templates.TemplateResponse("scrap/list.html", {
        "request": request, "current_user": current_user, "items": items,
    })
