"""
JSON API — Sales
GET /api/v1/sales                  list with pagination + filters
GET /api/v1/sales/{sale_number}    single sale detail
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.sales import Sale
from models.api_key import APIKey
from auth.api_key import require_scope
from schemas.sale import SaleOut, SaleListItem
from schemas.common import PaginatedResponse

router = APIRouter(prefix="/sales", tags=["api-v1-sales"])


@router.get("", response_model=PaginatedResponse[SaleListItem])
async def list_sales(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sold_by: Optional[str] = Query(default=None),
    customer: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _key: APIKey = Depends(require_scope("sales:read")),
):
    query = select(Sale)
    if sold_by:
        query = query.where(Sale.sold_by == sold_by)
    if customer:
        query = query.where(Sale.customer_name.ilike(f"%{customer}%"))

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(
        query.order_by(Sale.sold_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    sales = result.scalars().all()
    total_pages = max(1, (total + page_size - 1) // page_size)
    return PaginatedResponse[SaleListItem](
        items=[SaleListItem.model_validate(s) for s in sales],
        total=total, page=page, page_size=page_size, total_pages=total_pages,
    )


@router.get("/{sale_number}", response_model=SaleOut)
async def get_sale(
    sale_number: str,
    db: AsyncSession = Depends(get_db),
    _key: APIKey = Depends(require_scope("sales:read")),
):
    result = await db.execute(select(Sale).where(Sale.sale_number == sale_number))
    sale = result.scalar_one_or_none()
    if not sale:
        raise HTTPException(status_code=404, detail=f"Sale '{sale_number}' not found")
    return SaleOut.model_validate(sale)
