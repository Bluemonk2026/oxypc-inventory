"""
Ready to Dispatch (#20) + telecaller dispatch requests (#21).

 - Telecaller raises a dispatch request from the Ready to Sale page.
 - Sales Manager approves it on the Ready to Dispatch page.
 - Approval enables the Sell button back on Ready to Sale.
"""
import uuid
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from templates_config import templates
from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage
from models.lot import Lot
from models.sales import Sale
from models.dispatch_request import TelecallerDispatchRequest
from auth.dependencies import get_current_user, require_roles, verify_csrf
from services.audit_engine import audit

router = APIRouter(tags=["dispatch"], dependencies=[Depends(verify_csrf)])

view_allowed = require_roles(UserRole.admin, UserRole.inventory_manager, UserRole.sales,
                             UserRole.sales_manager, UserRole.telecaller)
request_allowed = require_roles(UserRole.admin, UserRole.sales, UserRole.sales_manager, UserRole.telecaller)
approve_allowed = require_roles(UserRole.admin, UserRole.sales_manager)


def _as_uuid(v):
    try:
        return uuid.UUID(v)
    except Exception:
        return None


@router.get("/dispatch", response_class=HTMLResponse)
async def dispatch_list(request: Request, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(view_allowed)):
    rows = (await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id, isouter=True)
        .where(Device.current_stage == DeviceStage.ready_to_sale, Device.is_active == True)
        .order_by(Device.updated_at.desc())
    )).all()
    device_ids = [d.id for d, _ in rows]

    dr = (await db.execute(
        select(TelecallerDispatchRequest).order_by(TelecallerDispatchRequest.created_at.desc())
    )).scalars().all()
    approved_qty = {}
    for r in dr:
        if r.status == "approved":
            approved_qty[str(r.device_id)] = approved_qty.get(str(r.device_id), 0) + r.qty_requested

    sold_by = {}
    if device_ids:
        sold_rows = (await db.execute(
            select(Sale.device_id, func.count(Sale.id))
            .where(Sale.device_id.in_(device_ids)).group_by(Sale.device_id)
        )).all()
        for did, cnt in sold_rows:
            sold_by[str(did)] = cnt

    buckets = {"A": [], "B": [], "C": [], "D": []}
    for device, lot_number in rows:
        gv = device.grade.value if device.grade else None
        if gv == "A":
            key = "A"
        elif gv == "B":
            key = "B"
        elif gv == "D":
            key = "D"
        else:
            key = "C"  # C, scrap, ungraded → C
        qty = device.qty or 1
        disp = approved_qty.get(str(device.id), 0)
        buckets[key].append({
            "barcode": device.barcode, "model": device.model or device.brand or "—",
            "lot": lot_number, "qty": qty, "dispatched": disp,
            "pending": max(0, qty - disp), "sold": sold_by.get(str(device.id), 0),
        })

    # Per-grade summary for the count cards (total + dispatched/pending/sold split)
    card_stats = {}
    for g, items in buckets.items():
        card_stats[g] = {
            "total": len(items),
            "dispatched": sum(i["dispatched"] for i in items),
            "pending": sum(i["pending"] for i in items),
            "sold": sum(i["sold"] for i in items),
        }

    # Distinct telecallers for the request-section filter dropdown
    _seen = {}
    for r in dr:
        uname = r.telecaller_username or ""
        if uname and uname not in _seen:
            _seen[uname] = r.telecaller_name or uname
    telecaller_options = sorted(_seen.items(), key=lambda kv: kv[1].lower())

    return templates.TemplateResponse("dispatch/list.html", {
        "request": request, "current_user": current_user,
        "buckets": buckets, "card_stats": card_stats, "requests": dr,
        "telecaller_options": telecaller_options,
    })


@router.post("/dispatch/request")
async def create_dispatch_request(request: Request, barcode: str = Form(...), qty: int = Form(1),
                                  db: AsyncSession = Depends(get_db),
                                  current_user: User = Depends(request_allowed)):
    device = (await db.execute(select(Device).where(Device.barcode == barcode))).scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    db.add(TelecallerDispatchRequest(
        device_id=device.id, barcode=device.barcode,
        telecaller_username=current_user.username, telecaller_name=current_user.full_name,
        qty_requested=max(1, qty), qty_available=device.qty or 1,
        grade=device.grade.value if device.grade else None, status="requested",
    ))
    await audit(db, user=current_user, action="DISPATCH_REQUESTED", table_name="telecaller_dispatch_requests",
                record_id=None, new_value={"barcode": barcode, "qty": qty}, request=request)
    await db.commit()
    return RedirectResponse(url="/sales/ready?success=Dispatch+request+raised+for+" + barcode, status_code=302)


@router.post("/dispatch/{req_id}/approve")
async def approve_dispatch(req_id: str, request: Request, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(approve_allowed)):
    r = (await db.execute(
        select(TelecallerDispatchRequest).where(TelecallerDispatchRequest.id == _as_uuid(req_id))
    )).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "Request not found")
    r.status = "approved"
    r.approved_at = app_now()
    r.approved_by = current_user.username
    await audit(db, user=current_user, action="DISPATCH_APPROVED", table_name="telecaller_dispatch_requests",
                record_id=str(r.id), new_value={"barcode": r.barcode}, request=request)
    await db.commit()
    return RedirectResponse(url="/dispatch?success=Request+approved", status_code=302)
