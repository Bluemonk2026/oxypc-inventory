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
from models.device import Device, DeviceStage, StageMovement
from models.lot import Lot
from models.sales import Sale
from models.dispatch_request import TelecallerDispatchRequest
from auth.dependencies import get_current_user, require_roles, verify_csrf
from services.audit_engine import audit
from utils.warranty import warranty_from_sold_at, latest_sold_at_map

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

    # ── Timeline (item 10): days since device entered ready_to_sale stage ─────
    ready_at_map = {}
    if device_ids:
        ready_rows = (await db.execute(
            select(StageMovement.device_id, func.max(StageMovement.moved_at))
            .where(StageMovement.device_id.in_(device_ids),
                   StageMovement.to_stage == DeviceStage.ready_to_sale)
            .group_by(StageMovement.device_id)
        )).all()
        for did, moved_at in ready_rows:
            ready_at_map[str(did)] = moved_at
    _now = app_now()

    # ── Warranty (item 1): 30 days from most recent sale ─────────────────────
    sold_map = await latest_sold_at_map(db, device_ids)
    warranty_map = {}
    for did, sold_at in sold_map.items():
        w = warranty_from_sold_at(sold_at)
        if w:
            warranty_map[did] = w

    total_ready = len(rows)
    ready_d15 = ready_d30 = ready_d45 = ready_d60 = ready_d60plus = 0
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
        _ready_at = ready_at_map.get(str(device.id))
        _timeline = (_now - _ready_at).days if _ready_at else None
        if _timeline is not None:
            if _timeline <= 15:
                ready_d15 += 1
            elif _timeline <= 30:
                ready_d30 += 1
            elif _timeline <= 45:
                ready_d45 += 1
            elif _timeline <= 60:
                ready_d60 += 1
            else:
                ready_d60plus += 1
        _w = warranty_map.get(str(device.id))
        buckets[key].append({
            "barcode": device.barcode, "model": device.model or device.brand or "—",
            "lot": lot_number, "qty": qty, "dispatched": disp,
            "pending": max(0, qty - disp), "sold": sold_by.get(str(device.id), 0),
            "timeline": _timeline,
            "warranty": _w["label"] if _w else None,
            "warranty_status": _w["status"] if _w else None,
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

    # Ready-to-Sale age summary card: total + split by days since ready_to_sale
    ready_summary = {
        "total": total_ready,
        "d15": ready_d15,        # ≤15 days
        "d30": ready_d30,        # 16–30 days
        "d45": ready_d45,        # 31–45 days
        "d60": ready_d60,        # 46–60 days
        "d60plus": ready_d60plus,  # > 60 days
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
        "ready_summary": ready_summary,
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
