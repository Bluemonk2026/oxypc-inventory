"""
JSON API endpoints for Smart UX auto-fill and async lookups.
All routes require an authenticated session.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models.lot import LotLineItem
from models.dealers import Dealer
from models.device import Device
from models.stage_control import AllowedTransition
from auth.dependencies import get_current_user
from models.user import User

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/lot-line-item/{item_id}")
async def get_lot_line_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return LotLineItem fields for IQC form auto-fill."""
    result = await db.execute(select(LotLineItem).where(LotLineItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Line item not found")
    return JSONResponse({
        "brand": item.brand or "",
        "model": item.model or "",
        "cpu": item.cpu or "",
        "generation": str(item.generation or ""),
        "ram_gb": str(item.ram_gb or ""),
        "storage_gb": str(item.storage_gb or ""),
        "storage_type": item.storage_type or "",
        "unit_price": str(item.unit_price or ""),
    })


@router.get("/lot-line-items-by-lot/{lot_id}")
async def get_lot_line_items(
    lot_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all line items for a lot (for IQC form dropdown population)."""
    result = await db.execute(
        select(LotLineItem).where(LotLineItem.lot_id == lot_id).order_by(LotLineItem.sub_category)
    )
    items = result.scalars().all()
    return JSONResponse([{
        "id": str(i.id),
        "sub_category": i.sub_category or "",
        "brand": i.brand or "",
        "model": i.model or "",
        "unit_price": str(i.unit_price or "0"),
    } for i in items])


@router.get("/dealers/search")
async def search_dealers(
    q: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full-text dealer search for typeahead/autocomplete widgets."""
    result = await db.execute(
        select(Dealer)
        .where(Dealer.business_name.ilike(f"%{q}%"))
        .limit(10)
    )
    dealers = result.scalars().all()
    return JSONResponse([{
        "id": str(d.id),
        "name": d.business_name,
        "phone": d.phone or "",
        "state": d.state or "",
        "city": d.city or "",
    } for d in dealers])


@router.get("/device/{device_id}/next-stages")
async def get_next_stages(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return allowed next stages for a device based on AllowedTransitions table."""
    dev = (await db.execute(
        select(Device).where(Device.id == device_id)
    )).scalar_one_or_none()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    if not dev.current_stage:
        return JSONResponse([])
    transitions = (await db.execute(
        select(AllowedTransition).where(
            AllowedTransition.from_stage == dev.current_stage.value
        )
    )).scalars().all()
    return JSONResponse([{
        "stage": t.to_stage,
        "label": t.to_stage.replace("_", " ").title(),
    } for t in transitions])
