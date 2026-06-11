"""
JSON API — Spare Parts
GET /api/v1/spare-parts               list with low-stock filter
GET /api/v1/spare-parts/{part_code}   single part detail
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.spare_parts import SparePart
from models.api_key import APIKey
from auth.api_key import require_scope
from schemas.spare_parts import SparePartOut, SparePartListItem
from schemas.common import PaginatedResponse

router = APIRouter(prefix="/spare-parts", tags=["api-v1-spare-parts"])


@router.get("", response_model=PaginatedResponse[SparePartListItem])
async def list_spare_parts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    category: Optional[str] = Query(default=None),
    low_stock: bool = Query(default=False, description="Show only parts below min_stock_alert"),
    db: AsyncSession = Depends(get_db),
    _key: APIKey = Depends(require_scope("spare_parts:read")),
):
    query = select(SparePart)
    if category:
        query = query.where(SparePart.category == category)
    if low_stock:
        query = query.where(SparePart.qty_in_stock <= SparePart.min_stock_alert)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(
        query.order_by(SparePart.name)
        .offset((page - 1) * page_size).limit(page_size)
    )
    parts = result.scalars().all()
    total_pages = max(1, (total + page_size - 1) // page_size)
    return PaginatedResponse[SparePartListItem](
        items=[SparePartListItem.model_validate(p) for p in parts],
        total=total, page=page, page_size=page_size, total_pages=total_pages,
    )


@router.get("/{part_code}", response_model=SparePartOut)
async def get_spare_part(
    part_code: str,
    db: AsyncSession = Depends(get_db),
    _key: APIKey = Depends(require_scope("spare_parts:read")),
):
    result = await db.execute(select(SparePart).where(SparePart.part_code == part_code))
    part = result.scalar_one_or_none()
    if not part:
        raise HTTPException(status_code=404, detail=f"Spare part '{part_code}' not found")
    return SparePartOut.model_validate(part)
