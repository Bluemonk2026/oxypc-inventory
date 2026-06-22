"""
Sales Router — sale block enforcement + return re-entry to IQC + audit
"""
from templates_config import templates
import uuid as _uuid
from datetime import datetime
from utils.timezone import app_now
from decimal import Decimal
from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
import csv
import io
from sqlalchemy import select, func, text, or_
from fastapi.responses import StreamingResponse

from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement
from models.lot import Lot
from models.sales import Sale, Return
from models.crm import CRMSalesOpportunity, CRMContact
from models.dispatch_request import TelecallerDispatchRequest
from auth.dependencies import get_current_user, require_roles, verify_csrf, require_module_perm
from services.control_engine import validate_sale_allowed
from services.cost_engine import check_below_cost_warning
from services.audit_engine import audit
from services.event_bus import EventType, publish

router = APIRouter(tags=["sales"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.sales)
ready_allowed = require_roles(UserRole.admin, UserRole.sales, UserRole.sales_manager, UserRole.telecaller)


async def _next_sale_number(db: AsyncSession) -> str:
    result = await db.execute(text("SELECT nextval('sale_number_seq')"))
    seq = result.scalar()
    return f"SALE-{seq:04d}"


@router.get("/sales/ready", response_class=HTMLResponse)
async def ready_list(request: Request, db: AsyncSession = Depends(get_db),
                     current_user: User = Depends(ready_allowed)):
    result = await db.execute(
        select(Device, Lot.lot_number, Lot.buying_price, Lot.qty)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == DeviceStage.ready_to_sale)
        .order_by(Device.updated_at.desc())
    )
    devices = result.all()

    # ── Dispatch-request state (#21): Sell enabled only after approval ───────
    device_ids = [d.id for d, *_ in devices]
    approved_ids, requested_ids = set(), set()
    if device_ids:
        drs = (await db.execute(
            select(TelecallerDispatchRequest.device_id, TelecallerDispatchRequest.status)
            .where(TelecallerDispatchRequest.device_id.in_(device_ids))
        )).all()
        for did, st in drs:
            if st == "approved":
                approved_ids.add(str(did))
            elif st == "requested":
                requested_ids.add(str(did))

    # ── Interested dealers banner: open CRM sales opps matching ready device types ──
    ready_device_types = {d.device_type for d, *_ in devices if d.device_type}
    interested_dealers: list = []
    if ready_device_types:
        opps = (await db.execute(
            select(CRMSalesOpportunity, CRMContact.company_name, CRMContact.phone)
            .outerjoin(CRMContact, CRMSalesOpportunity.contact_id == CRMContact.id)
            .where(
                CRMSalesOpportunity.device_type.in_(ready_device_types),
                CRMSalesOpportunity.stage.notin_(["won", "lost"]),
            )
            .order_by(CRMSalesOpportunity.priority.desc(), CRMSalesOpportunity.updated_at.desc())
            .limit(20)
        )).all()
        interested_dealers = [
            {
                "opp_number": opp.opp_number,
                "title": opp.title,
                "device_type": opp.device_type,
                "grade": opp.grade_required or "Any",
                "qty": opp.required_qty,
                "budget": opp.budget_per_unit,
                "stage": opp.stage,
                "priority": opp.priority,
                "company": company or "Unknown",
                "phone": phone or "",
            }
            for opp, company, phone in opps
        ]

    return templates.TemplateResponse("sales/ready_list.html", {
        "request": request, "devices": devices, "current_user": current_user,
        "interested_dealers": interested_dealers,
        "approved_ids": approved_ids, "requested_ids": requested_ids,
    })


@router.get("/sales/new", response_class=HTMLResponse)
async def sale_new_form(request: Request, barcode: str = None,
                        db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(allowed)):
    device = None; lot = None; stage_error = None; approved_qty = None
    if barcode:
        result = await db.execute(select(Device).where(Device.barcode == barcode))
        device = result.scalar_one_or_none()
        if device:
            lot_result = await db.execute(select(Lot).where(Lot.id == device.lot_id))
            lot = lot_result.scalar_one_or_none()
            # Show warning if not ready
            if device.current_stage != DeviceStage.ready_to_sale:
                stage_val = device.current_stage.value if device.current_stage else "unknown"
                stage_error = (f"Device is in stage '{stage_val}' — "
                               f"it must be in 'ready_to_sale' to sell.")
            # Prefill qty from the latest approved telecaller dispatch request
            appr = (await db.execute(
                select(TelecallerDispatchRequest)
                .where(TelecallerDispatchRequest.device_id == device.id,
                       TelecallerDispatchRequest.status == "approved")
                .order_by(TelecallerDispatchRequest.approved_at.desc())
            )).scalars().first()
            if appr:
                approved_qty = appr.qty_requested
    next_num = await _next_sale_number(db)
    return templates.TemplateResponse("sales/new.html", {
        "request": request, "device": device, "lot": lot,
        "next_sale_number": next_num, "current_user": current_user,
        "error": stage_error, "approved_qty": approved_qty,
    })


@router.post("/sales/new")
async def create_sale(
    request: Request,
    background_tasks: BackgroundTasks,
    barcode: str = Form(...),
    sale_price: str = Form(...),
    customer_name: str = Form(""),
    customer_phone: str = Form(""),
    customer_state: str = Form(default=None),
    invoice_no: str = Form(""),
    payment_mode: str = Form("cash"),
    notes: str = Form(""),
    qty: int = Form(1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    _perm: User = Depends(require_module_perm("sales", "add")),
):
    if qty > 1:
        notes = f"[Qty:{qty}] {notes}".strip()
    result = await db.execute(select(Device).where(Device.barcode == barcode))
    device = result.scalar_one_or_none()
    if not device:
        return templates.TemplateResponse("sales/new.html", {
            "request": request, "device": None, "lot": None,
            "next_sale_number": await _next_sale_number(db),
            "current_user": current_user,
            "error": f"Device {barcode} not found",
        })

    # ── Control Engine: sale block ────────────────────────────────────────
    try:
        await validate_sale_allowed(device)
    except HTTPException as e:
        return templates.TemplateResponse("sales/new.html", {
            "request": request, "device": device, "lot": None,
            "next_sale_number": await _next_sale_number(db),
            "current_user": current_user, "error": e.detail,
        })

    try:
        price = Decimal(sale_price)
    except Exception:
        return templates.TemplateResponse("sales/new.html", {
            "request": request, "device": device, "lot": None,
            "next_sale_number": await _next_sale_number(db),
            "current_user": current_user,
            "error": "Invalid sale price — please enter a valid number",
        })

    # ── Cost Engine: below-cost warning ──────────────────────────────────
    warn = await check_below_cost_warning(device, price, db)

    sale_num = await _next_sale_number(db)
    sale = Sale(
        sale_number=sale_num, device_id=device.id,
        sale_price=price,
        customer_name=customer_name or None, customer_phone=customer_phone or None,
        customer_state=customer_state or None,
        invoice_no=invoice_no or None, payment_mode=payment_mode,
        sold_by=current_user.username, notes=notes or None,
    )
    db.add(sale)

    prev = device.current_stage
    prev_mv = (await db.execute(
        select(StageMovement)
        .where(StageMovement.device_id == device.id,
               StageMovement.to_stage  == prev,
               StageMovement.exited_at == None)
        .order_by(StageMovement.moved_at.desc())
    )).scalars().first()
    if prev_mv:
        prev_mv.exited_at = app_now()

    device.current_stage = DeviceStage.sold
    device.updated_at    = app_now()
    db.add(StageMovement(device_id=device.id, from_stage=prev, to_stage=DeviceStage.sold,
                         moved_by=current_user.username, notes=f"Sold — {sale_num}"))

    await audit(db, user=current_user, action="SALE_CREATED",
                table_name="sales", record_id=str(device.id),
                new_value={"sale_number": sale_num, "price": str(price),
                           "below_cost": bool(warn)},
                notes=warn, request=request)

    await db.commit()
    publish(EventType.SALE_COMPLETED, {
        "sale_number": sale_num,
        "barcode": barcode,
        "price": str(price),
        "customer_name": customer_name or None,
        "sold_by": current_user.username,
        "_source": "sales_html",
    }, background_tasks)
    redirect = f"/sales?success=Sale+{sale_num}+recorded"
    if warn:
        import urllib.parse
        redirect += f"&warning={urllib.parse.quote(warn)}"
    return RedirectResponse(url=redirect, status_code=302)


@router.get("/sales/export-selected", response_class=HTMLResponse)
async def export_selected_get(request: Request, current_user: User = Depends(allowed)):
    """Redirect GET to sales list (form should POST)."""
    return RedirectResponse(url="/sales", status_code=302)


@router.post("/sales/export-selected")
async def export_selected_sales(
    sale_ids: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Export selected sales rows as CSV. Receives comma-separated Sale UUIDs."""
    ids = [sid.strip() for sid in sale_ids.split(",") if sid.strip()]
    if not ids:
        return RedirectResponse(url="/sales", status_code=302)

    result = await db.execute(
        select(Sale, Device.barcode, Device.brand, Device.model, Device.grade, Lot.lot_number)
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Sale.id.in_(ids))
        .order_by(Sale.sold_at.desc())
    )
    rows = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Sale#", "Date", "Barcode", "Brand", "Model", "Lot", "Grade",
                     "Price", "Customer", "Phone", "Payment", "Sold By"])
    for row in rows:
        s = row.Sale
        writer.writerow([
            s.sale_number,
            s.sold_at.strftime("%d-%m-%Y"),
            row.barcode, row.brand, row.model, row.lot_number,
            row.grade.value if row.grade else "",
            float(s.sale_price or 0),
            s.customer_name or "", s.customer_phone or "",
            s.payment_mode or "", s.sold_by or "",
        ])
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sales_selected.csv"},
    )


@router.get("/sales/{sale_id}", response_class=HTMLResponse)
async def sale_detail(
    sale_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    # UUID columns require proper UUID type — bare string comparison fails with asyncpg
    try:
        sale_uuid = _uuid.UUID(sale_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Sale not found")

    result = await db.execute(
        select(Sale, Device, Lot)
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Sale.id == sale_uuid)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Sale not found")
    sale, device, lot = row.Sale, row.Device, row.Lot
    return templates.TemplateResponse("sales/detail.html", {
        "request": request,
        "current_user": current_user,
        "sale": sale,
        "device": device,
        "lot": lot,
    })


@router.get("/sales", response_class=HTMLResponse)
async def sales_list(
    request: Request,
    q: str = Query(default=""),
    sale_no: str = Query(default=""),
    sold_by_filter: str = Query(default=""),
    customer: str = Query(default=""),
    grade: str = Query(default=""),
    lot_id: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    from sqlalchemy import case as sa_case

    base_q = (
        select(Sale, Device.barcode, Device.brand, Device.model, Device.grade,
               Lot.lot_number, Lot.buying_price, Lot.qty)
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
    )

    # ── Apply filters ────────────────────────────────────────────────────────
    if q:
        like = f"%{q}%"
        base_q = base_q.where(or_(
            Device.barcode.ilike(like),
            Device.brand.ilike(like),
            Device.model.ilike(like),
        ))
    if sale_no:
        base_q = base_q.where(Sale.sale_number.ilike(f"%{sale_no}%"))
    if sold_by_filter:
        base_q = base_q.where(Sale.sold_by == sold_by_filter)
    if customer:
        base_q = base_q.where(Sale.customer_name.ilike(f"%{customer}%"))
    if grade:
        base_q = base_q.where(Device.grade == grade)
    if lot_id:
        base_q = base_q.where(Device.lot_id == lot_id)

    # ── Pagination ───────────────────────────────────────────────────────────
    count_q = (
        select(func.count(Sale.id))
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
    )
    if q:
        like = f"%{q}%"
        count_q = count_q.where(or_(
            Device.barcode.ilike(like),
            Device.brand.ilike(like),
            Device.model.ilike(like),
        ))
    if sale_no:
        count_q = count_q.where(Sale.sale_number.ilike(f"%{sale_no}%"))
    if sold_by_filter:
        count_q = count_q.where(Sale.sold_by == sold_by_filter)
    if customer:
        count_q = count_q.where(Sale.customer_name.ilike(f"%{customer}%"))
    if grade:
        count_q = count_q.where(Device.grade == grade)
    if lot_id:
        count_q = count_q.where(Device.lot_id == lot_id)

    total = (await db.execute(count_q)).scalar() or 0
    total_pages = max(1, (total + page_size - 1) // page_size)

    result = await db.execute(
        base_q.order_by(Sale.sold_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    sales = result.all()

    # ── Registered device stats (single query) ───────────────────────────────
    dev_stats = (await db.execute(
        select(
            func.count(Device.id).label("total"),
            func.count(sa_case((Device.current_stage == DeviceStage.sold, 1))).label("sold"),
        ).where(Device.is_active == True)
    )).one()
    total_registered = dev_stats.total
    total_devices_sold = dev_stats.sold
    total_available = total_registered - total_devices_sold

    # ── Sales-user dropdown ──────────────────────────────────────────────────
    sellers_result = await db.execute(
        select(Sale.sold_by).distinct().where(Sale.sold_by.isnot(None)).order_by(Sale.sold_by)
    )
    sellers = [r.sold_by for r in sellers_result]

    # ── Lot dropdown ─────────────────────────────────────────────────────────
    lots_result = await db.execute(select(Lot).order_by(Lot.lot_number))
    lots = lots_result.scalars().all()

    return templates.TemplateResponse("sales/list.html", {
        "request": request,
        "sales": sales,
        "lots": lots,
        "sellers": sellers,
        "selected_lot": lot_id,
        "current_user": current_user,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        # Filters
        "q": q,
        "sale_no": sale_no,
        "sold_by_filter": sold_by_filter,
        "customer": customer,
        "grade": grade,
        # Device stats
        "total_registered": total_registered,
        "total_devices_sold": total_devices_sold,
        "total_available": total_available,
    })


@router.get("/returns", response_class=HTMLResponse)
async def returns_list(request: Request, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(allowed)):
    result = await db.execute(
        select(Return, Device.barcode, Device.brand, Device.model,
               Sale.sale_price, Sale.sale_number)
        .join(Device, Return.device_id == Device.id)
        .join(Sale, Return.sale_id == Sale.id)
        .order_by(Return.return_date.desc())
    )
    returns = result.all()
    return templates.TemplateResponse("sales/returns_list.html", {
        "request": request, "returns": returns, "current_user": current_user,
    })


@router.get("/returns/new", response_class=HTMLResponse)
async def return_form(request: Request, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(allowed)):
    return templates.TemplateResponse("sales/return_form.html", {
        "request": request, "current_user": current_user, "error": None, "sale": None,
    })


@router.post("/returns/new")
async def process_return(
    request: Request,
    barcode: str = Form(...),
    reason: str = Form(""),
    condition_on_return: str = Form(""),
    action_taken: str = Form("restock"),
    refund_amount: str = Form("0"),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    _perm: User = Depends(require_module_perm("returns", "add")),
):
    dev_result = await db.execute(select(Device).where(Device.barcode == barcode))
    device = dev_result.scalar_one_or_none()
    if not device:
        return templates.TemplateResponse("sales/return_form.html", {
            "request": request, "current_user": current_user,
            "error": f"Device {barcode} not found", "sale": None,
        })

    sale_result = await db.execute(
        select(Sale).where(Sale.device_id == device.id)
        .order_by(Sale.sold_at.desc()).limit(1)
    )
    sale = sale_result.scalars().first()
    if not sale:
        return templates.TemplateResponse("sales/return_form.html", {
            "request": request, "current_user": current_user,
            "error": "No sale found for this device", "sale": None,
        })

    # Guard: prevent duplicate return for the same sale
    existing_return = (await db.execute(
        select(Return).where(Return.sale_id == sale.id)
    )).scalars().first()
    if existing_return:
        return templates.TemplateResponse("sales/return_form.html", {
            "request": request, "current_user": current_user,
            "error": (f"A return for sale {sale.sale_number} already exists "
                      f"(processed on {existing_return.return_date.strftime('%d %b %Y')}). "
                      "Cannot create a duplicate return."),
            "sale": sale,
        })

    # Mandatory field validation
    if not reason or not reason.strip():
        return templates.TemplateResponse("sales/return_form.html", {
            "request": request, "current_user": current_user,
            "error": "Return Reason is required.", "sale": sale,
        })
    if not condition_on_return or not condition_on_return.strip():
        return templates.TemplateResponse("sales/return_form.html", {
            "request": request, "current_user": current_user,
            "error": "Condition on Return is required.", "sale": sale,
        })

    # Determine intended re-entry stage (used once approved)
    if action_taken == "scrap":
        reentered_stage = "scrapped"
    else:
        reentered_stage = "iqc"

    # Create return as PENDING — device stage unchanged until manager approves
    ret = Return(
        sale_id=sale.id, device_id=device.id,
        reason=reason or None, condition_on_return=condition_on_return or None,
        action_taken=action_taken or None,
        reentered_stage=reentered_stage,
        processed_by=current_user.username,
        refund_amount=Decimal(refund_amount) if refund_amount else None,
        notes=notes or None,
        approval_status='pending',
    )
    db.add(ret)

    await audit(db, user=current_user, action="RETURN_SUBMITTED",
                table_name="returns", record_id=str(device.id),
                new_value={"sale": sale.sale_number, "reason": reason,
                           "action": action_taken, "approval_status": "pending"},
                request=request)

    await db.commit()
    return RedirectResponse(url="/returns?success=Return+submitted+for+manager+approval",
                            status_code=302)


# ── Manager: pending returns list ─────────────────────────────────────────────

MANAGER_ROLES = (UserRole.admin, UserRole.sales_manager)


@router.get("/returns/pending", response_class=HTMLResponse)
async def pending_returns(request: Request, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    if current_user.role not in MANAGER_ROLES:
        return RedirectResponse(url="/returns?error=Access+denied", status_code=302)
    result = await db.execute(
        select(Return, Device.barcode, Device.brand, Device.model,
               Sale.sale_price, Sale.sale_number)
        .join(Device, Return.device_id == Device.id)
        .join(Sale, Return.sale_id == Sale.id)
        .where(Return.approval_status == 'pending')
        .order_by(Return.return_date.desc())
    )
    pending = result.all()
    return templates.TemplateResponse("sales/returns_pending.html", {
        "request": request, "pending": pending, "current_user": current_user,
    })


# ── Manager: approve return ───────────────────────────────────────────────────

@router.post("/returns/{return_id}/approve")
async def approve_return(
    request: Request,
    return_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in MANAGER_ROLES:
        return RedirectResponse(url="/returns/pending?error=Access+denied", status_code=302)

    ret_result = await db.execute(select(Return).where(Return.id == return_id))
    ret = ret_result.scalar_one_or_none()
    if not ret:
        return RedirectResponse(url="/returns/pending?error=Return+not+found", status_code=302)
    if ret.approval_status != 'pending':
        return RedirectResponse(
            url=f"/returns/pending?error=Return+already+{ret.approval_status}", status_code=302
        )

    # Move device to intended stage
    dev_result = await db.execute(select(Device).where(Device.id == ret.device_id))
    device = dev_result.scalar_one_or_none()
    if device:
        if ret.reentered_stage == "scrapped":
            to_stage = DeviceStage.scrapped
        else:
            to_stage = DeviceStage.iqc

        prev = device.current_stage
        prev_mv = (await db.execute(
            select(StageMovement)
            .where(StageMovement.device_id == device.id,
                   StageMovement.to_stage  == prev,
                   StageMovement.exited_at == None)
            .order_by(StageMovement.moved_at.desc())
        )).scalars().first()
        if prev_mv:
            prev_mv.exited_at = app_now()

        device.current_stage = to_stage
        device.updated_at    = app_now()
        db.add(StageMovement(device_id=device.id, from_stage=prev, to_stage=to_stage,
                             moved_by=current_user.username,
                             notes=f"Return approved ({ret.action_taken}): {ret.reason}"))

    ret.approval_status = 'approved'
    ret.approved_by     = current_user.username
    ret.approved_at     = app_now()

    await audit(db, user=current_user, action="RETURN_APPROVED",
                table_name="returns", record_id=str(ret.id),
                new_value={"approved_by": current_user.username,
                           "reentered_stage": ret.reentered_stage},
                request=request)
    await db.commit()
    return RedirectResponse(url="/returns/pending?success=Return+approved", status_code=302)


# ── Manager: reject return ────────────────────────────────────────────────────

@router.post("/returns/{return_id}/reject")
async def reject_return(
    request: Request,
    return_id: str,
    rejection_reason: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in MANAGER_ROLES:
        return RedirectResponse(url="/returns/pending?error=Access+denied", status_code=302)

    ret_result = await db.execute(select(Return).where(Return.id == return_id))
    ret = ret_result.scalar_one_or_none()
    if not ret:
        return RedirectResponse(url="/returns/pending?error=Return+not+found", status_code=302)
    if ret.approval_status != 'pending':
        return RedirectResponse(
            url=f"/returns/pending?error=Return+already+{ret.approval_status}", status_code=302
        )

    ret.approval_status  = 'rejected'
    ret.approved_by      = current_user.username
    ret.approved_at      = app_now()
    ret.rejection_reason = rejection_reason or None
    # Device stays sold — no stage change on rejection

    await audit(db, user=current_user, action="RETURN_REJECTED",
                table_name="returns", record_id=str(ret.id),
                new_value={"rejected_by": current_user.username,
                           "reason": rejection_reason},
                request=request)
    await db.commit()
    return RedirectResponse(url="/returns/pending?success=Return+rejected", status_code=302)
