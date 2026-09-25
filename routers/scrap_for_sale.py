"""
Scrap for Sale — batches created from /transfers when Transfer Type =
Scrap for Sale. Each batch (ScrapForSale) is a Scrap ID; its Tag Numbers
and Spare Parts are the StockTransfer rows that reference it
(StockTransfer.scrap_for_sale_id) — same "the transfer log is the
membership list" pattern buckets/lots already use.
"""
import uuid as _uuid
from collections import Counter
from decimal import Decimal
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from templates_config import templates
from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage
from models.stock_transfer import StockTransfer
from models.scrap_for_sale import ScrapForSale
from auth.dependencies import get_current_user, require_roles, verify_csrf
from services.audit_engine import audit

router = APIRouter(tags=["scrap_for_sale"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager, UserRole.sales_manager)


@router.get("/scrap-for-sale", response_class=HTMLResponse)
async def scrap_for_sale_list(request: Request, db: AsyncSession = Depends(get_db),
                              current_user: User = Depends(allowed)):
    batches = (await db.execute(
        select(ScrapForSale).where(ScrapForSale.is_trashed == False)  # noqa: E712
        .order_by(ScrapForSale.scrap_id.desc())
    )).scalars().all()

    assigned_ids = {b.assigned_to_user_id for b in batches if b.assigned_to_user_id}
    user_name_map = {}
    if assigned_ids:
        user_name_map = {
            u.id: (u.full_name or u.username)
            for u in (await db.execute(select(User).where(User.id.in_(assigned_ids)))).scalars().all()
        }

    rows = []
    if batches:
        batch_ids = [b.id for b in batches]
        transfers = (await db.execute(
            select(StockTransfer, Device.model)
            .outerjoin(Device, StockTransfer.device_id == Device.id)
            .where(StockTransfer.scrap_for_sale_id.in_(batch_ids))
        )).all()
        by_batch: dict = {}
        for t, device_model in transfers:
            by_batch.setdefault(t.scrap_for_sale_id, []).append((t, device_model))

        for b in batches:
            entries = by_batch.get(b.id, [])
            tag_models = Counter()
            part_categories = Counter()
            tags_qty = 0
            parts_qty = 0
            for t, device_model in entries:
                if t.move_kind == "parts":
                    part_categories[t.model or "—"] += (t.quantity or 0)
                    parts_qty += (t.quantity or 0)
                else:
                    tag_models[device_model or "—"] += 1
                    tags_qty += 1
            rows.append({
                "id": str(b.id), "scrap_id": b.scrap_id,
                "tag_count": tags_qty, "part_count": parts_qty,
                "tag_breakdown": [{"name": n, "count": c} for n, c in sorted(tag_models.items())],
                "part_breakdown": [{"name": n, "count": c} for n, c in sorted(part_categories.items())],
                "total_qty": tags_qty + parts_qty,
                "min_price": float(b.min_selling_price) if b.min_selling_price is not None else None,
                "max_price": float(b.max_selling_price) if b.max_selling_price is not None else None,
                "status": b.status,
                "assigned_to_name": user_name_map.get(b.assigned_to_user_id, "—"),
            })

    # Devices sitting at the Scrap for Sale stage that never went through a
    # /transfers batch — reached here via a bulk stage-move (Bulk Customise,
    # IQC Customise, "Back to Inventory — Normal Scrap from repair line")
    # instead of the formal Scrap for Sale transfer, so they have no
    # ScrapForSale row and no StockTransfer link. Listed separately so they
    # are visible/actionable instead of silently missing from this page,
    # same fix pattern as the L3/L4 orphaned-WorkOrder issue fixed earlier.
    batched_device_ids = {
        t.device_id for t in (await db.execute(
            select(StockTransfer.device_id).where(StockTransfer.scrap_for_sale_id.isnot(None))
        )).scalars().all()
    }
    unbatched_result = await db.execute(
        select(Device)
        .where(Device.current_stage == DeviceStage.scrap_for_sale, Device.is_trashed == False)
        .order_by(Device.updated_at.desc())
    )
    unbatched_devices = [
        {
            "barcode": d.barcode, "brand": d.brand, "model": d.model,
            "grade": d.grade.value if d.grade else "—",
            "updated_at": d.updated_at,
        }
        for d in unbatched_result.scalars().all() if d.id not in batched_device_ids
    ]

    return templates.TemplateResponse("scrap/for_sale.html", {
        "request": request, "current_user": current_user, "rows": rows,
        "unbatched_devices": unbatched_devices,
    })


@router.post("/scrap-for-sale/{scrap_id}/price")
async def set_scrap_for_sale_price(
    request: Request, scrap_id: str,
    min_selling_price: str = Form(""), max_selling_price: str = Form(""),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(allowed),
):
    try:
        bid = _uuid.UUID(scrap_id)
    except ValueError:
        raise HTTPException(404)
    b = (await db.execute(select(ScrapForSale).where(ScrapForSale.id == bid))).scalar_one_or_none()
    if not b:
        raise HTTPException(404, "Scrap for Sale batch not found")
    try:
        b.min_selling_price = Decimal(min_selling_price) if min_selling_price.strip() else None
        b.max_selling_price = Decimal(max_selling_price) if max_selling_price.strip() else None
    except Exception:
        return RedirectResponse(url="/scrap-for-sale?error=Invalid+price", status_code=302)
    await audit(db, user=current_user, action="SCRAP_FOR_SALE_PRICE_SET",
                table_name="scrap_for_sale", record_id=str(b.id),
                new_value={"min_selling_price": str(b.min_selling_price) if b.min_selling_price is not None else None,
                           "max_selling_price": str(b.max_selling_price) if b.max_selling_price is not None else None},
                request=request)
    await db.commit()
    return RedirectResponse(url="/scrap-for-sale?success=Selling+price+updated", status_code=302)


@router.post("/scrap-for-sale/{scrap_id}/sell")
async def sell_scrap_for_sale(request: Request, scrap_id: str,
                              db: AsyncSession = Depends(get_db), current_user: User = Depends(allowed)):
    try:
        bid = _uuid.UUID(scrap_id)
    except ValueError:
        raise HTTPException(404)
    b = (await db.execute(select(ScrapForSale).where(ScrapForSale.id == bid))).scalar_one_or_none()
    if not b:
        raise HTTPException(404, "Scrap for Sale batch not found")
    b.status = "sold"
    await audit(db, user=current_user, action="SCRAP_FOR_SALE_SOLD",
                table_name="scrap_for_sale", record_id=str(b.id), new_value={"status": "sold"}, request=request)
    await db.commit()
    return RedirectResponse(url="/scrap-for-sale?success=Marked+sold", status_code=302)


@router.post("/scrap-for-sale/{scrap_id}/delete")
async def delete_scrap_for_sale(request: Request, scrap_id: str,
                                db: AsyncSession = Depends(get_db), current_user: User = Depends(allowed)):
    try:
        bid = _uuid.UUID(scrap_id)
    except ValueError:
        raise HTTPException(404)
    b = (await db.execute(select(ScrapForSale).where(ScrapForSale.id == bid))).scalar_one_or_none()
    if not b:
        raise HTTPException(404, "Scrap for Sale batch not found")
    b.is_trashed = True
    await audit(db, user=current_user, action="SCRAP_FOR_SALE_DELETED",
                table_name="scrap_for_sale", record_id=str(b.id), new_value={"is_trashed": True}, request=request)
    await db.commit()
    return RedirectResponse(url="/scrap-for-sale?success=Removed", status_code=302)
