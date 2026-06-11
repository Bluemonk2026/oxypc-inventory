"""
JSON API — Lots
GET /api/v1/lots                list with pagination + filters
GET /api/v1/lots/{lot_number}   single lot detail
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.lot import Lot
from models.api_key import APIKey
from auth.api_key import require_scope
from schemas.lot import LotOut, LotListItem
from schemas.common import PaginatedResponse

router = APIRouter(prefix="/lots", tags=["api-v1-lots"])


@router.get("", response_model=PaginatedResponse[LotListItem])
async def list_lots(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    supplier: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _key: APIKey = Depends(require_scope("lots:read")),
):
    query = select(Lot)
    if supplier:
        query = query.where(Lot.supplier_name.ilike(f"%{supplier}%"))
    if status:
        query = query.where(Lot.status == status)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(
        query.order_by(Lot.purchase_date.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    lots = result.scalars().all()
    total_pages = max(1, (total + page_size - 1) // page_size)
    return PaginatedResponse[LotListItem](
        items=[LotListItem.model_validate(l) for l in lots],
        total=total, page=page, page_size=page_size, total_pages=total_pages,
    )


@router.get("/{lot_number}", response_model=LotOut)
async def get_lot(
    lot_number: str,
    db: AsyncSession = Depends(get_db),
    _key: APIKey = Depends(require_scope("lots:read")),
):
    result = await db.execute(select(Lot).where(Lot.lot_number == lot_number))
    lot = result.scalar_one_or_none()
    if not lot:
        raise HTTPException(status_code=404, detail=f"Lot '{lot_number}' not found")
    return LotOut.model_validate(lot)
