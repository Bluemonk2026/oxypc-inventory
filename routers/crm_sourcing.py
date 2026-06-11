"""CRM Sourcing Deals router — purchase pipeline from lead to lot creation."""
import os
import uuid as _uuid
from datetime import datetime
from utils.timezone import app_now
from config import UPLOADS_DIR
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user, verify_csrf, require_module_perm
from models.user import User, UserRole
from services.audit_engine import audit
from models.crm import (
    CRMContact, CRMSourcingDeal, CRMActivity,
    SOURCE_TYPES, MATERIAL_TYPES, SOURCING_STAGES, PRIORITIES,
)
from models.lot import Lot
from models.device import Device, DeviceStage

router = APIRouter(prefix="/crm/sourcing", tags=["crm-sourcing"], dependencies=[Depends(verify_csrf)])

PURCHASE_ROLES = (UserRole.admin, UserRole.inventory_manager, UserRole.sales_manager)


async def _next_deal_number(db: AsyncSession) -> str:
    result = await db.execute(select(func.count(CRMSourcingDeal.id)))
    n = (result.scalar() or 0) + 1
    year = app_now().year
    return f"SD-{year}-{n:04d}"


# ── LIST ─────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def list_sourcing_deals(
    request: Request,
    q: str = Query(default=""),
    stage: str = Query(default=""),
    source_type: str = Query(default=""),
    priority: str = Query(default=""),
    assigned: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(CRMSourcingDeal)
    if q:
        like = f"%{q}%"
        query = query.where(CRMSourcingDeal.title.ilike(like))
    if stage:
        query = query.where(CRMSourcingDeal.stage == stage)
    if source_type:
        query = query.where(CRMSourcingDeal.source_type == source_type)
    if priority:
        query = query.where(CRMSourcingDeal.priority == priority)
    if assigned:
        query = query.where(CRMSourcingDeal.assigned_to == assigned)
    elif current_user.role in (UserRole.sales,):
        query = query.where(CRMSourcingDeal.assigned_to == current_user.username)

    result = await db.execute(query.order_by(CRMSourcingDeal.created_at.desc()))
    deals = result.scalars().all()

    # pipeline value (open deals only)
    open_deals = [d for d in deals if d.stage not in ("won", "lost")]
    pipeline_value = sum(
        float(d.our_offer_total or d.asking_price_total or 0) for d in open_deals
    )

    # overdue follow-ups
    now = app_now()
    overdue_r = await db.execute(
        select(func.count(CRMActivity.id)).where(
            CRMActivity.deal_type == "sourcing",
            CRMActivity.followup_done == False,
            CRMActivity.next_followup <= now,
        )
    )
    overdue_count = overdue_r.scalar() or 0

    # fetch contacts for display
    contact_ids = list({d.contact_id for d in deals if d.contact_id})
    contacts_map = {}
    if contact_ids:
        cr = await db.execute(select(CRMContact).where(CRMContact.id.in_(contact_ids)))
        for c in cr.scalars().all():
            contacts_map[str(c.id)] = c

    return templates.TemplateResponse("crm/sourcing/list.html", {
        "request": request, "current_user": current_user,
        "deals": deals, "contacts_map": contacts_map,
        "pipeline_value": pipeline_value, "overdue_count": overdue_count,
        "q": q, "stage": stage, "source_type": source_type,
        "priority": priority, "assigned": assigned,
        "sourcing_stages": SOURCING_STAGES,
        "source_types": SOURCE_TYPES,
        "priorities": PRIORITIES,
        "stage_labels": dict(SOURCING_STAGES),
    })


# ── NEW ───────────────────────────────────────────────────────────────────────

@router.get("/new", response_class=HTMLResponse)
async def new_deal_form(
    request: Request,
    contact_id: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contacts_r = await db.execute(
        select(CRMContact)
        .where(CRMContact.status == "active", CRMContact.contact_type.in_(["supplier", "both"]))
        .order_by(CRMContact.company_name)
    )
    contacts = contacts_r.scalars().all()
    preselect = contact_id or ""
    return templates.TemplateResponse("crm/sourcing/form.html", {
        "request": request, "current_user": current_user,
        "deal": None, "contacts": contacts, "preselect": preselect,
        "source_types": SOURCE_TYPES,
        "material_types": MATERIAL_TYPES,
        "priorities": PRIORITIES,
    })


@router.post("/new")
async def create_deal(
    request: Request,
    title:               str = Form(...),
    contact_id:          str = Form(default=None),
    source_type:         str = Form(default=None),
    device_type:         str = Form(default=None),
    est_quantity:        str = Form(default=None),
    material_type:       str = Form(default=None),
    asking_price_unit:   str = Form(default=None),
    asking_price_total:  str = Form(default=None),
    our_offer_unit:      str = Form(default=None),
    payment_advance_pct: str = Form(default="0"),
    payment_terms:       str = Form(default=None),
    priority:            str = Form(default="medium"),
    assigned_to:         str = Form(default=None),
    notes:               str = Form(default=None),
    product_records:     UploadFile = File(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _perm: User = Depends(require_module_perm("crm_sourcing", "add")),
):
    def _n(v): return float(v) if v and v.strip() else None
    def _i(v): return int(v) if v and v.strip() else None

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

    deal_number = await _next_deal_number(db)
    aq_unit  = _n(asking_price_unit)
    aq_total = _n(asking_price_total)
    qty      = _i(est_quantity)
    # auto-calc total if not provided
    if aq_unit and qty and not aq_total:
        aq_total = round(aq_unit * qty, 2)
    our_unit = _n(our_offer_unit)
    our_total = round(our_unit * qty, 2) if our_unit and qty else None

    deal = CRMSourcingDeal(
        deal_number=deal_number,
        contact_id=contact_id or None,
        title=title,
        source_type=source_type or None,
        device_type=device_type or None,
        est_quantity=qty,
        material_type=material_type or None,
        asking_price_unit=aq_unit,
        asking_price_total=aq_total,
        our_offer_unit=our_unit,
        our_offer_total=our_total,
        payment_advance_pct=_i(payment_advance_pct) or 0,
        payment_terms=payment_terms or None,
        priority=priority,
        assigned_to=assigned_to or current_user.username,
        notes=notes or None,
        product_records_file=saved_filename,
        created_by=current_user.username,
        stage="lead",
    )
    db.add(deal)
    await db.flush()   # get deal.id
    await audit(db, action="CRM_DEAL_CREATED", user=current_user,
                table_name="crm_sourcing_deals", record_id=str(deal.id),
                new_value={"deal_number": deal_number, "title": title,
                           "device_type": device_type, "est_quantity": qty,
                           "asking_price_unit": aq_unit, "assigned_to": assigned_to},
                request=request)
    await db.commit()
    return RedirectResponse(url=f"/crm/sourcing/{deal.id}?success=Deal+created", status_code=302)


# ── DETAIL ────────────────────────────────────────────────────────────────────

@router.get("/{deal_id}", response_class=HTMLResponse)
async def deal_detail(
    request: Request,
    deal_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMSourcingDeal).where(CRMSourcingDeal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        return RedirectResponse(url="/crm/sourcing?error=Deal+not+found", status_code=302)

    contact = None
    if deal.contact_id:
        cr = await db.execute(select(CRMContact).where(CRMContact.id == deal.contact_id))
        contact = cr.scalar_one_or_none()

    acts_r = await db.execute(
        select(CRMActivity)
        .where(CRMActivity.deal_id == deal.id, CRMActivity.deal_type == "sourcing")
        .order_by(CRMActivity.activity_date.desc())
    )
    activities = acts_r.scalars().all()

    # next follow-up
    next_fu = next(
        (a for a in activities if not a.followup_done and a.next_followup), None
    )

    lot = None
    lot_registered = 0
    lot_sold = 0
    if deal.linked_lot_id:
        lr = await db.execute(select(Lot).where(Lot.id == deal.linked_lot_id))
        lot = lr.scalar_one_or_none()
        if lot:
            reg_r = await db.execute(
                select(func.count(Device.id))
                .where(Device.lot_id == lot.id, Device.is_active == True)
            )
            lot_registered = int(reg_r.scalar() or 0)

            sold_r = await db.execute(
                select(func.count(Device.id))
                .where(Device.lot_id == lot.id, Device.current_stage == DeviceStage.sold)
            )
            lot_sold = int(sold_r.scalar() or 0)

    stage_list = list(enumerate(SOURCING_STAGES))
    current_idx = next((i for i, (v, _) in stage_list if v == deal.stage), 0)

    return templates.TemplateResponse("crm/sourcing/detail.html", {
        "request": request, "current_user": current_user,
        "deal": deal, "contact": contact, "activities": activities,
        "next_fu": next_fu, "lot": lot,
        "lot_registered": lot_registered,
        "lot_sold": lot_sold,
        "sourcing_stages": SOURCING_STAGES,
        "stage_list": stage_list, "current_idx": current_idx,
        "stage_labels": dict(SOURCING_STAGES),
        "source_map": dict(SOURCE_TYPES),
        "material_map": dict(MATERIAL_TYPES),
        "now": app_now(),
    })


# ── MOVE STAGE ────────────────────────────────────────────────────────────────

@router.post("/{deal_id}/stage")
async def move_stage(
    request: Request,
    deal_id: str,
    new_stage: str = Form(...),
    win_loss_reason: str = Form(default=None),
    final_price_unit: str = Form(default=None),
    final_price_total: str = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMSourcingDeal).where(CRMSourcingDeal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        return RedirectResponse(url="/crm/sourcing?error=Deal+not+found", status_code=302)

    deal.stage = new_stage
    if win_loss_reason:
        deal.win_loss_reason = win_loss_reason
    if final_price_unit and final_price_unit.strip():
        try:
            deal.final_price_unit = float(final_price_unit)
        except (ValueError, TypeError):
            pass
    if final_price_total and final_price_total.strip():
        try:
            deal.final_price_total = float(final_price_total)
        except (ValueError, TypeError):
            pass

    # log automatic activity
    activity = CRMActivity(
        contact_id=deal.contact_id,
        deal_id=deal.id,
        deal_type="sourcing",
        activity_type="note",
        summary=f"Stage moved to: {dict(SOURCING_STAGES).get(new_stage, new_stage)}",
        performed_by=current_user.username,
        outcome="done",
    )
    db.add(activity)
    await db.commit()
    return RedirectResponse(url=f"/crm/sourcing/{deal_id}?success=Stage+updated", status_code=302)


# ── EDIT ─────────────────────────────────────────────────────────────────────

@router.get("/{deal_id}/edit", response_class=HTMLResponse)
async def edit_deal_form(
    request: Request,
    deal_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMSourcingDeal).where(CRMSourcingDeal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        return RedirectResponse(url="/crm/sourcing?error=Not+found", status_code=302)
    contacts_r = await db.execute(
        select(CRMContact)
        .where(CRMContact.status == "active", CRMContact.contact_type.in_(["supplier", "both"]))
        .order_by(CRMContact.company_name)
    )
    contacts = contacts_r.scalars().all()
    return templates.TemplateResponse("crm/sourcing/form.html", {
        "request": request, "current_user": current_user,
        "deal": deal, "contacts": contacts, "preselect": str(deal.contact_id) if deal.contact_id else "",
        "source_types": SOURCE_TYPES,
        "material_types": MATERIAL_TYPES,
        "priorities": PRIORITIES,
    })


@router.post("/{deal_id}/edit")
async def update_deal(
    request: Request,
    deal_id: str,
    title:               str = Form(...),
    contact_id:          str = Form(default=None),
    source_type:         str = Form(default=None),
    device_type:         str = Form(default=None),
    est_quantity:        str = Form(default=None),
    material_type:       str = Form(default=None),
    asking_price_unit:   str = Form(default=None),
    asking_price_total:  str = Form(default=None),
    our_offer_unit:      str = Form(default=None),
    our_offer_total:     str = Form(default=None),
    payment_advance_pct: str = Form(default="0"),
    payment_terms:       str = Form(default=None),
    priority:            str = Form(default="medium"),
    assigned_to:         str = Form(default=None),
    notes:               str = Form(default=None),
    product_records:     UploadFile = File(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMSourcingDeal).where(CRMSourcingDeal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        return RedirectResponse(url="/crm/sourcing?error=Not+found", status_code=302)

    def _n(v): return float(v) if v and v.strip() else None
    def _i(v): return int(v) if v and v.strip() else None

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
            deal.product_records_file = safe_name

    deal.title = title
    deal.contact_id = contact_id or None
    deal.source_type = source_type or None
    deal.device_type = device_type or None
    deal.est_quantity = _i(est_quantity)
    deal.material_type = material_type or None
    deal.asking_price_unit = _n(asking_price_unit)
    deal.asking_price_total = _n(asking_price_total)
    deal.our_offer_unit = _n(our_offer_unit)
    deal.our_offer_total = _n(our_offer_total)
    deal.payment_advance_pct = _i(payment_advance_pct) or 0
    deal.payment_terms = payment_terms or None
    deal.priority = priority
    deal.assigned_to = assigned_to
    deal.notes = notes or None
    await db.commit()
    return RedirectResponse(url=f"/crm/sourcing/{deal_id}?success=Deal+updated", status_code=302)


# ── LINK LOT ─────────────────────────────────────────────────────────────────

@router.post("/{deal_id}/link-lot")
async def link_lot(
    request: Request,
    deal_id: str,
    lot_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMSourcingDeal).where(CRMSourcingDeal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        return RedirectResponse(url="/crm/sourcing?error=Deal+not+found", status_code=302)
    deal.linked_lot_id = lot_id
    deal.stage = "received"   # Stock Received — operator closes to Won after IQC is done
    activity = CRMActivity(
        contact_id=deal.contact_id, deal_id=deal.id, deal_type="sourcing",
        activity_type="note",
        summary="Lot linked — stage auto-advanced to Stock Received.",
        performed_by=current_user.username, outcome="done",
    )
    db.add(activity)
    await db.commit()
    return RedirectResponse(url=f"/crm/sourcing/{deal_id}?success=Linked+to+Lot+%26+marked+Received", status_code=302)
