"""CRM Sales Opportunities router — sales pipeline from enquiry to invoice."""
import os
import uuid as _uuid
from datetime import datetime
from utils.timezone import app_now
from config import UPLOADS_DIR
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user, verify_csrf, require_module_perm
from models.user import User, UserRole
from models.crm import (
    CRMContact, CRMSalesOpportunity, CRMActivity, CRMQuote,
    BUYER_TYPES, MATERIAL_TYPES, SALES_STAGES, PRIORITIES, GRADES,
)
from models.sales import Sale
from models.device import Device
from models.lot import Lot

router = APIRouter(prefix="/crm/sales", tags=["crm-sales"], dependencies=[Depends(verify_csrf)])


async def _next_opp_number(db: AsyncSession) -> str:
    result = await db.execute(select(func.count(CRMSalesOpportunity.id)))
    n = (result.scalar() or 0) + 1
    year = app_now().year
    return f"OPP-{year}-{n:04d}"


# ── LIST ─────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def list_opportunities(
    request: Request,
    q: str = Query(default=""),
    stage: str = Query(default=""),
    buyer_type: str = Query(default=""),
    priority: str = Query(default=""),
    assigned: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(CRMSalesOpportunity)
    if q:
        query = query.where(CRMSalesOpportunity.title.ilike(f"%{q}%"))
    if stage:
        query = query.where(CRMSalesOpportunity.stage == stage)
    if buyer_type:
        query = query.where(CRMSalesOpportunity.buyer_type == buyer_type)
    if priority:
        query = query.where(CRMSalesOpportunity.priority == priority)
    if assigned:
        query = query.where(CRMSalesOpportunity.assigned_to == assigned)
    elif current_user.role in (UserRole.sales, UserRole.telecaller):
        query = query.where(CRMSalesOpportunity.assigned_to == current_user.username)

    result = await db.execute(query.order_by(CRMSalesOpportunity.created_at.desc()))
    opps = result.scalars().all()

    open_opps = [o for o in opps if o.stage not in ("won", "lost")]
    pipeline_value = sum(float(o.estimated_value or 0) for o in open_opps)

    now = app_now()
    overdue_r = await db.execute(
        select(func.count(CRMActivity.id)).where(
            CRMActivity.deal_type == "sales",
            CRMActivity.followup_done == False,
            CRMActivity.next_followup <= now,
        )
    )
    overdue_count = overdue_r.scalar() or 0

    contact_ids = list({o.contact_id for o in opps if o.contact_id})
    contacts_map = {}
    if contact_ids:
        cr = await db.execute(select(CRMContact).where(CRMContact.id.in_(contact_ids)))
        for c in cr.scalars().all():
            contacts_map[str(c.id)] = c

    return templates.TemplateResponse("crm/sales/list.html", {
        "request": request, "current_user": current_user,
        "opps": opps, "contacts_map": contacts_map,
        "pipeline_value": pipeline_value, "overdue_count": overdue_count,
        "q": q, "stage": stage, "buyer_type": buyer_type,
        "priority": priority, "assigned": assigned,
        "sales_stages": SALES_STAGES, "buyer_types": BUYER_TYPES,
        "stage_labels": dict(SALES_STAGES), "priorities": PRIORITIES,
    })


# ── NEW ───────────────────────────────────────────────────────────────────────

@router.get("/new", response_class=HTMLResponse)
async def new_opp_form(
    request: Request,
    contact_id: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contacts_r = await db.execute(
        select(CRMContact)
        .where(CRMContact.status == "active", CRMContact.contact_type.in_(["buyer", "both"]))
        .order_by(CRMContact.company_name)
    )
    contacts = contacts_r.scalars().all()
    return templates.TemplateResponse("crm/sales/form.html", {
        "request": request, "current_user": current_user,
        "opp": None, "contacts": contacts, "preselect": contact_id,
        "buyer_types": BUYER_TYPES, "material_types": MATERIAL_TYPES,
        "grades": GRADES, "priorities": PRIORITIES,
    })


@router.post("/new")
async def create_opp(
    request: Request,
    title:               str = Form(...),
    contact_id:          str = Form(default=None),
    buyer_type:          str = Form(default=None),
    device_type:         str = Form(default=None),
    required_qty:        str = Form(default=None),
    material_type:       str = Form(default=None),
    grade_required:      str = Form(default=None),
    budget_per_unit:     str = Form(default=None),
    estimated_value:     str = Form(default=None),
    expected_close_date: str = Form(default=None),
    priority:            str = Form(default="medium"),
    assigned_to:         str = Form(default=None),
    notes:               str = Form(default=None),
    product_records:     UploadFile = File(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _perm: User = Depends(require_module_perm("crm_sales_opp", "add")),
):
    def _n(v): return float(v) if v and v.strip() else None
    def _i(v): return int(v) if v and v.strip() else None
    def _d(v):
        if v and v.strip():
            try: return datetime.strptime(v.strip(), "%Y-%m-%d").date()
            except: return None
        return None

    # Save uploaded product records file if provided
    saved_filename = None
    if product_records and product_records.filename:
        ext = os.path.splitext(product_records.filename)[1].lower()
        if ext in (".xls", ".xlsx", ".csv"):
            safe_name = f"{_uuid.uuid4().hex}{ext}"
            uploads_dir = os.path.join(UPLOADS_DIR, "crm")
            os.makedirs(uploads_dir, exist_ok=True)
            dest = os.path.join(uploads_dir, safe_name)
            content = await product_records.read()
            with open(dest, "wb") as f:
                f.write(content)
            saved_filename = safe_name

    qty = _i(required_qty)
    bpu = _n(budget_per_unit)
    est = _n(estimated_value) or (round(qty * bpu, 2) if qty and bpu else None)

    opp_number = await _next_opp_number(db)
    opp = CRMSalesOpportunity(
        opp_number=opp_number,
        contact_id=contact_id or None,
        title=title,
        buyer_type=buyer_type or None,
        device_type=device_type or None,
        required_qty=qty,
        material_type=material_type or None,
        grade_required=grade_required or None,
        budget_per_unit=bpu,
        estimated_value=est,
        expected_close_date=_d(expected_close_date),
        priority=priority,
        assigned_to=assigned_to or current_user.username,
        notes=notes or None,
        product_records_file=saved_filename,
        created_by=current_user.username,
        stage="lead",
    )
    db.add(opp)
    await db.commit()
    return RedirectResponse(url=f"/crm/sales/{opp.id}?success=Opportunity+created", status_code=302)


# ── DETAIL ────────────────────────────────────────────────────────────────────

@router.get("/{opp_id}", response_class=HTMLResponse)
async def opp_detail(
    request: Request,
    opp_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMSalesOpportunity).where(CRMSalesOpportunity.id == opp_id))
    opp = result.scalar_one_or_none()
    if not opp:
        return RedirectResponse(url="/crm/sales?error=Opportunity+not+found", status_code=302)

    contact = None
    if opp.contact_id:
        cr = await db.execute(select(CRMContact).where(CRMContact.id == opp.contact_id))
        contact = cr.scalar_one_or_none()

    quote = None
    if opp.quote_id:
        qr = await db.execute(select(CRMQuote).where(CRMQuote.id == opp.quote_id))
        quote = qr.scalar_one_or_none()

    acts_r = await db.execute(
        select(CRMActivity)
        .where(CRMActivity.deal_id == opp.id, CRMActivity.deal_type == "sales")
        .order_by(CRMActivity.activity_date.desc())
    )
    activities = acts_r.scalars().all()

    next_fu = next((a for a in activities if not a.followup_done and a.next_followup), None)

    stage_list = list(enumerate(SALES_STAGES))
    current_idx = next((i for i, (v, _) in stage_list if v == opp.stage), 0)

    return templates.TemplateResponse("crm/sales/detail.html", {
        "request": request, "current_user": current_user,
        "opp": opp, "contact": contact, "quote": quote, "activities": activities,
        "next_fu": next_fu,
        "sales_stages": SALES_STAGES, "stage_list": stage_list, "current_idx": current_idx,
        "buyer_map": dict(BUYER_TYPES), "material_map": dict(MATERIAL_TYPES),
        "now": app_now(),
    })


# ── MOVE STAGE ────────────────────────────────────────────────────────────────

@router.post("/{opp_id}/stage")
async def move_stage(
    request: Request,
    opp_id: str,
    new_stage: str = Form(...),
    win_loss_reason: str = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMSalesOpportunity).where(CRMSalesOpportunity.id == opp_id))
    opp = result.scalar_one_or_none()
    if not opp:
        return RedirectResponse(url="/crm/sales?error=Not+found", status_code=302)
    opp.stage = new_stage
    if win_loss_reason:
        opp.win_loss_reason = win_loss_reason
    activity = CRMActivity(
        contact_id=opp.contact_id, deal_id=opp.id, deal_type="sales",
        activity_type="note",
        summary=f"Stage moved to: {dict(SALES_STAGES).get(new_stage, new_stage)}",
        performed_by=current_user.username, outcome="done",
    )
    db.add(activity)
    await db.commit()
    return RedirectResponse(url=f"/crm/sales/{opp_id}?success=Stage+updated", status_code=302)


# ── EDIT ─────────────────────────────────────────────────────────────────────

@router.get("/{opp_id}/edit", response_class=HTMLResponse)
async def edit_opp_form(
    request: Request,
    opp_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMSalesOpportunity).where(CRMSalesOpportunity.id == opp_id))
    opp = result.scalar_one_or_none()
    if not opp:
        return RedirectResponse(url="/crm/sales?error=Not+found", status_code=302)
    contacts_r = await db.execute(
        select(CRMContact)
        .where(CRMContact.status == "active", CRMContact.contact_type.in_(["buyer", "both"]))
        .order_by(CRMContact.company_name)
    )
    contacts = contacts_r.scalars().all()
    return templates.TemplateResponse("crm/sales/form.html", {
        "request": request, "current_user": current_user,
        "opp": opp, "contacts": contacts,
        "preselect": str(opp.contact_id) if opp.contact_id else "",
        "buyer_types": BUYER_TYPES, "material_types": MATERIAL_TYPES,
        "grades": GRADES, "priorities": PRIORITIES,
    })


@router.post("/{opp_id}/edit")
async def update_opp(
    request: Request,
    opp_id: str,
    title:               str = Form(...),
    contact_id:          str = Form(default=None),
    buyer_type:          str = Form(default=None),
    device_type:         str = Form(default=None),
    required_qty:        str = Form(default=None),
    material_type:       str = Form(default=None),
    grade_required:      str = Form(default=None),
    budget_per_unit:     str = Form(default=None),
    estimated_value:     str = Form(default=None),
    expected_close_date: str = Form(default=None),
    priority:            str = Form(default="medium"),
    assigned_to:         str = Form(default=None),
    notes:               str = Form(default=None),
    product_records:     UploadFile = File(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMSalesOpportunity).where(CRMSalesOpportunity.id == opp_id))
    opp = result.scalar_one_or_none()
    if not opp:
        return RedirectResponse(url="/crm/sales?error=Not+found", status_code=302)

    def _n(v): return float(v) if v and v.strip() else None
    def _i(v): return int(v) if v and v.strip() else None
    def _d(v):
        if v and v.strip():
            try: return datetime.strptime(v.strip(), "%Y-%m-%d").date()
            except: return None
        return None

    # Replace file if a new one is uploaded
    if product_records and product_records.filename:
        ext = os.path.splitext(product_records.filename)[1].lower()
        if ext in (".xls", ".xlsx", ".csv"):
            safe_name = f"{_uuid.uuid4().hex}{ext}"
            uploads_dir = os.path.join(UPLOADS_DIR, "crm")
            os.makedirs(uploads_dir, exist_ok=True)
            dest = os.path.join(uploads_dir, safe_name)
            content = await product_records.read()
            with open(dest, "wb") as f:
                f.write(content)
            opp.product_records_file = safe_name

    opp.title = title
    opp.contact_id = contact_id or None
    opp.buyer_type = buyer_type or None
    opp.device_type = device_type or None
    opp.required_qty = _i(required_qty)
    opp.material_type = material_type or None
    opp.grade_required = grade_required or None
    opp.budget_per_unit = _n(budget_per_unit)
    opp.estimated_value = _n(estimated_value)
    opp.expected_close_date = _d(expected_close_date)
    opp.priority = priority
    opp.assigned_to = assigned_to
    opp.notes = notes or None
    await db.commit()
    return RedirectResponse(url=f"/crm/sales/{opp_id}?success=Opportunity+updated", status_code=302)


# ── LINK SALE RECORD ──────────────────────────────────────────────────────────

@router.get("/{opp_id}/link-sale", response_class=HTMLResponse)
async def link_sale_form(
    request: Request,
    opp_id: str,
    q: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMSalesOpportunity).where(CRMSalesOpportunity.id == opp_id))
    opp = result.scalar_one_or_none()
    if not opp:
        return RedirectResponse(url="/crm/sales?error=Not+found", status_code=302)

    # already linked sale IDs
    existing_ids = set((opp.linked_sale_ids or "").split(",")) - {""}

    # fetch recent sales (last 200), join device + lot for context
    sale_q = (
        select(Sale, Device.barcode, Device.brand, Device.model, Device.grade, Lot.lot_number)
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
        .order_by(Sale.sold_at.desc())
        .limit(200)
    )
    if q:
        like = f"%{q}%"
        sale_q = sale_q.where(
            Device.barcode.ilike(like) | Device.brand.ilike(like) |
            Device.model.ilike(like) | Sale.sale_number.ilike(like)
        )
    sales_r = await db.execute(sale_q)
    sales = sales_r.all()

    return templates.TemplateResponse("crm/sales/link_sale.html", {
        "request": request, "current_user": current_user,
        "opp": opp, "sales": sales, "existing_ids": existing_ids, "q": q,
    })


@router.post("/{opp_id}/link-sale")
async def link_sale_submit(
    request: Request,
    opp_id: str,
    sale_ids: list = Form(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMSalesOpportunity).where(CRMSalesOpportunity.id == opp_id))
    opp = result.scalar_one_or_none()
    if not opp:
        return RedirectResponse(url="/crm/sales?error=Not+found", status_code=302)

    # merge existing + newly selected (deduplicate)
    existing = set((opp.linked_sale_ids or "").split(",")) - {""}
    merged = existing | set(sale_ids)
    opp.linked_sale_ids = ",".join(merged)

    # auto-advance stage if still early
    if opp.stage in ("lead", "contacted", "requirement", "availability", "quoted", "negotiation", "confirmed"):
        opp.stage = "invoiced"

    activity = CRMActivity(
        contact_id=opp.contact_id, deal_id=opp.id, deal_type="sales",
        activity_type="note",
        summary=f"Linked {len(sale_ids)} sale record(s) to opportunity.",
        performed_by=current_user.username, outcome="done",
    )
    db.add(activity)
    await db.commit()
    return RedirectResponse(url=f"/crm/sales/{opp_id}?success=Sale+records+linked", status_code=302)
