"""CRM Assign Leads router — ad-campaign lead management with call history."""
import csv
import io
import json as _json
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user, verify_csrf
from models.user import User
from utils.timezone import app_now
from models.crm import (
    CRMLeadGroup, CRMLead, CRMLeadCall,
    ACTIVITY_OUTCOMES, LEAD_PLATFORMS, LEAD_CONTACT_MODES, LEAD_DEVICE_CATEGORIES,
)

router = APIRouter(
    prefix="/crm/assign-leads",
    tags=["crm-assign-leads"],
    dependencies=[Depends(verify_csrf)],
)

_STATUS_BADGE = {
    "interested":     "success",
    "not_interested": "danger",
    "callback":       "warning text-dark",
    "order_placed":   "primary",
    "no_answer":      "secondary",
    "followup":       "info text-dark",
    "done":           "dark",
    "rescheduled":    "light text-dark border",
}


async def _next_lead_id(db: AsyncSession) -> str:
    result = await db.execute(select(func.count(CRMLead.id)))
    n = (result.scalar() or 0) + 1
    return str(100000000000 + n)


def _cats(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        return _json.loads(raw)
    except Exception:
        return []


def _lead_dict(lead: CRMLead) -> dict:
    cats = _cats(lead.device_categories)
    return {
        "id":                    str(lead.id),
        "lead_id":               lead.lead_id,
        "group_id":              str(lead.group_id),
        "lead_date":             lead.lead_date.isoformat() if lead.lead_date else "",
        "lead_date_display":     lead.lead_date.strftime("%d-%m-%Y") if lead.lead_date else "—",
        "platform":              lead.platform or "",
        "device_categories":     cats,
        "device_categories_display": ", ".join(cats) if cats else "—",
        "units_expected":        lead.units_expected,
        "planning_to_buy":       lead.planning_to_buy or "",
        "contact_mode":          lead.contact_mode or "",
        "name":                  lead.name or "",
        "phone":                 lead.phone or "",
        "email":                 lead.email or "",
        "call_status":           lead.call_status or "",
        "status_badge":          _STATUS_BADGE.get(lead.call_status or "", "secondary"),
        "full_remark":           lead.full_remark or "",
        "assigned_to":           lead.assigned_to or "",
    }


# ── LIST ─────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def list_assign_leads(
    request: Request,
    q: str = Query(default=""),
    customer: str = Query(default=""),
    assigned: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Groups (optionally filtered by name)
    gq = select(CRMLeadGroup).order_by(CRMLeadGroup.created_at.desc())
    if q:
        gq = gq.where(CRMLeadGroup.name.ilike(f"%{q}%"))
    groups_result = await db.execute(gq)
    groups = groups_result.scalars().all()

    # Leads for these groups (with optional customer / assigned filters)
    leads_by_group: dict[str, list[dict]] = {}
    if groups:
        group_ids = [g.id for g in groups]
        lq = (
            select(CRMLead)
            .where(CRMLead.group_id.in_(group_ids))
            .order_by(CRMLead.created_at.desc())
        )
        if customer:
            like = f"%{customer}%"
            lq = lq.where(
                or_(CRMLead.name.ilike(like), CRMLead.phone.ilike(like), CRMLead.email.ilike(like))
            )
        if assigned:
            lq = lq.where(CRMLead.assigned_to == assigned)
        leads_result = await db.execute(lq)
        for lead in leads_result.scalars().all():
            leads_by_group.setdefault(str(lead.group_id), []).append(_lead_dict(lead))

    # All active users for assign dropdown
    users_result = await db.execute(
        select(User).where(User.status == True).order_by(User.full_name)
    )
    all_users = users_result.scalars().all()

    return templates.TemplateResponse("crm/assign_leads.html", {
        "request":          request,
        "current_user":     current_user,
        "groups":           groups,
        "leads_by_group":   leads_by_group,
        "all_users":        all_users,
        "q":                q,
        "customer":         customer,
        "assigned":         assigned,
        "platforms":        LEAD_PLATFORMS,
        "contact_modes":    LEAD_CONTACT_MODES,
        "device_categories": LEAD_DEVICE_CATEGORIES,
        "outcomes":         ACTIVITY_OUTCOMES,
    })


# ── GROUP CRUD ────────────────────────────────────────────────────────────────

@router.post("/group")
async def create_group(
    name: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = CRMLeadGroup(name=name.strip(), created_by=current_user.username)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return JSONResponse({"id": str(group.id), "name": group.name, "lead_count": 0})


@router.post("/group/{group_id}/edit")
async def edit_group(
    group_id: str,
    name: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMLeadGroup).where(CRMLeadGroup.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        return JSONResponse({"error": "Group not found"}, status_code=404)
    group.name = name.strip()
    group.updated_at = app_now()
    await db.commit()
    return JSONResponse({"ok": True, "name": group.name})


# ── SAMPLE CSV ────────────────────────────────────────────────────────────────

@router.get("/sample")
async def download_sample():
    headers = [
        "lead_date", "platform", "device_categories", "units_expected",
        "planning_to_buy", "contact_mode", "name", "phone", "email",
        "assigned_to", "full_remark",
    ]
    rows = [
        headers,
        [
            "2026-06-30", "Facebook", "Laptop,Desktop", "10",
            "This week", "Phone Call", "Rahul Sharma", "9876543210",
            "rahul@email.com", "", "Interested in bulk lot",
        ],
        [
            "2026-07-01", "Instagram", "Monitor", "5",
            "Next month", "WhatsApp", "Priya Singh", "9988776655",
            "", "", "",
        ],
    ]
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=assign_leads_sample.csv"},
    )


# ── IMPORT ────────────────────────────────────────────────────────────────────

@router.post("/import/{group_id}")
async def import_leads(
    group_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMLeadGroup).where(CRMLeadGroup.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        return JSONResponse({"error": "Group not found"}, status_code=404)

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except Exception:
        text = content.decode("latin-1")

    imported, errors = 0, []
    for i, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        try:
            ld = None
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
                try:
                    ld = datetime.strptime((row.get("lead_date") or "").strip(), fmt).date()
                    break
                except ValueError:
                    pass

            cats_raw = (row.get("device_categories") or "").strip()
            cats = [c.strip() for c in cats_raw.split(",") if c.strip()]
            units_s = (row.get("units_expected") or "").strip()
            units = int(units_s) if units_s.isdigit() else None

            lead = CRMLead(
                lead_id=await _next_lead_id(db),
                group_id=group.id,
                lead_date=ld,
                platform=(row.get("platform") or "").strip() or None,
                device_categories=_json.dumps(cats) if cats else None,
                units_expected=units,
                planning_to_buy=(row.get("planning_to_buy") or "").strip() or None,
                contact_mode=(row.get("contact_mode") or "").strip() or None,
                name=(row.get("name") or "").strip() or None,
                phone=(row.get("phone") or "").strip() or None,
                email=(row.get("email") or "").strip() or None,
                assigned_to=(row.get("assigned_to") or "").strip() or None,
                full_remark=(row.get("full_remark") or "").strip() or None,
                created_by=current_user.username,
            )
            db.add(lead)
            await db.flush()
            imported += 1
        except Exception as exc:
            errors.append(f"Row {i}: {exc}")

    await db.commit()
    return JSONResponse({"imported": imported, "errors": errors})


# ── LEAD CRUD ─────────────────────────────────────────────────────────────────

@router.post("/lead")
async def add_lead(
    group_id: str = Form(...),
    lead_date: str = Form(""),
    platform: str = Form(""),
    device_categories: str = Form("[]"),
    units_expected: str = Form(""),
    planning_to_buy: str = Form(""),
    contact_mode: str = Form(""),
    name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    assigned_to: str = Form(""),
    full_remark: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMLeadGroup).where(CRMLeadGroup.id == group_id))
    if not result.scalar_one_or_none():
        return JSONResponse({"error": "Group not found"}, status_code=404)

    ld = None
    if lead_date:
        try:
            ld = datetime.strptime(lead_date, "%Y-%m-%d").date()
        except ValueError:
            pass

    units = None
    if units_expected:
        try:
            units = int(units_expected)
        except ValueError:
            pass

    try:
        cats = _json.loads(device_categories) if device_categories else []
    except Exception:
        cats = []

    lead = CRMLead(
        lead_id=await _next_lead_id(db),
        group_id=group_id,
        lead_date=ld,
        platform=platform.strip() or None,
        device_categories=_json.dumps(cats) if cats else None,
        units_expected=units,
        planning_to_buy=planning_to_buy.strip() or None,
        contact_mode=contact_mode.strip() or None,
        name=name.strip() or None,
        phone=phone.strip() or None,
        email=email.strip() or None,
        assigned_to=assigned_to.strip() or None,
        full_remark=full_remark.strip() or None,
        created_by=current_user.username,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return JSONResponse({"ok": True, "lead": _lead_dict(lead)})


@router.post("/lead/{lead_id}/edit")
async def edit_lead(
    lead_id: str,
    lead_date: str = Form(""),
    platform: str = Form(""),
    device_categories: str = Form("[]"),
    units_expected: str = Form(""),
    planning_to_buy: str = Form(""),
    contact_mode: str = Form(""),
    name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    assigned_to: str = Form(""),
    full_remark: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMLead).where(CRMLead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        return JSONResponse({"error": "Lead not found"}, status_code=404)

    ld = None
    if lead_date:
        try:
            ld = datetime.strptime(lead_date, "%Y-%m-%d").date()
        except ValueError:
            pass

    units = None
    if units_expected:
        try:
            units = int(units_expected)
        except ValueError:
            pass

    try:
        cats = _json.loads(device_categories) if device_categories else []
    except Exception:
        cats = []

    lead.lead_date        = ld
    lead.platform         = platform.strip() or None
    lead.device_categories= _json.dumps(cats) if cats else None
    lead.units_expected   = units
    lead.planning_to_buy  = planning_to_buy.strip() or None
    lead.contact_mode     = contact_mode.strip() or None
    lead.name             = name.strip() or None
    lead.phone            = phone.strip() or None
    lead.email            = email.strip() or None
    lead.assigned_to      = assigned_to.strip() or None
    lead.full_remark      = full_remark.strip() or None
    lead.updated_at       = app_now()

    await db.commit()
    return JSONResponse({"ok": True})


# ── CALL LOG ──────────────────────────────────────────────────────────────────

@router.post("/lead/{lead_id}/call")
async def log_call(
    lead_id: str,
    calling_date: str = Form(...),
    followup_date: str = Form(""),
    outcome: str = Form(""),
    device_categories: str = Form("[]"),
    quantity: str = Form(""),
    full_remarks: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMLead).where(CRMLead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        return JSONResponse({"error": "Lead not found"}, status_code=404)

    try:
        cd = datetime.strptime(calling_date, "%Y-%m-%d").date()
    except ValueError:
        cd = date.today()

    fd = None
    if followup_date:
        try:
            fd = datetime.strptime(followup_date, "%Y-%m-%d").date()
        except ValueError:
            pass

    qty = None
    if quantity:
        try:
            qty = int(quantity)
        except ValueError:
            pass

    try:
        cats = _json.loads(device_categories) if device_categories else []
    except Exception:
        cats = []

    call = CRMLeadCall(
        lead_id=lead.id,
        calling_date=cd,
        followup_date=fd,
        outcome=outcome.strip() or None,
        device_categories=_json.dumps(cats) if cats else None,
        quantity=qty,
        full_remarks=full_remarks.strip() or None,
        logged_by=current_user.username,
    )
    db.add(call)

    # Update lead's latest call status
    if outcome:
        lead.call_status = outcome.strip()
        lead.updated_at = app_now()

    await db.commit()
    return JSONResponse({"ok": True})


# ── CALL HISTORY ─────────────────────────────────────────────────────────────

@router.get("/lead/{lead_id}/history")
async def get_call_history(
    lead_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(CRMLeadCall)
        .where(CRMLeadCall.lead_id == lead_id)
        .order_by(CRMLeadCall.created_at.desc())
    )
    calls = []
    for c in result.scalars().all():
        calls.append({
            "calling_date":      c.calling_date.strftime("%d-%m-%Y") if c.calling_date else "",
            "followup_date":     c.followup_date.strftime("%d-%m-%Y") if c.followup_date else "",
            "outcome":           c.outcome or "",
            "device_categories": _cats(c.device_categories),
            "quantity":          c.quantity,
            "full_remarks":      c.full_remarks or "",
            "logged_by":         c.logged_by,
        })
    return JSONResponse({"calls": calls})
