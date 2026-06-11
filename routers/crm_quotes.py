"""CRM Quotes router — quote builder with line items and print view."""
from datetime import datetime, date, timedelta
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user, verify_csrf
from models.user import User, UserRole
from models.crm import (
    CRMContact, CRMQuote, CRMQuoteItem, CRMSalesOpportunity,
    MATERIAL_TYPES, GRADES,
)

router = APIRouter(prefix="/crm/quotes", tags=["crm-quotes"], dependencies=[Depends(verify_csrf)])


async def _next_quote_number(db: AsyncSession) -> str:
    result = await db.execute(select(func.count(CRMQuote.id)))
    n = (result.scalar() or 0) + 1
    year = app_now().year
    return f"QT-{year}-{n:04d}"


# ── LIST ─────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def list_quotes(
    request: Request,
    q: str = Query(default=""),
    status: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(CRMQuote)
    if status:
        query = query.where(CRMQuote.status == status)
    result = await db.execute(query.order_by(CRMQuote.created_at.desc()))
    quotes = result.scalars().all()

    contact_ids = list({qt.contact_id for qt in quotes if qt.contact_id})
    contacts_map = {}
    if contact_ids:
        cr = await db.execute(select(CRMContact).where(CRMContact.id.in_(contact_ids)))
        for c in cr.scalars().all():
            contacts_map[str(c.id)] = c

    # build opps_map keyed by quote.id (CRMSalesOpportunity.quote_id → opportunity)
    quote_ids = [qt.id for qt in quotes]
    opps_map = {}
    if quote_ids:
        or_result = await db.execute(
            select(CRMSalesOpportunity).where(CRMSalesOpportunity.quote_id.in_(quote_ids))
        )
        for opp in or_result.scalars().all():
            opps_map[str(opp.quote_id)] = opp

    if q:
        quotes = [qt for qt in quotes
                  if q.lower() in qt.quote_number.lower()
                  or (qt.contact_id and contacts_map.get(str(qt.contact_id)) and
                      q.lower() in contacts_map[str(qt.contact_id)].company_name.lower())]

    return templates.TemplateResponse("crm/quotes/list.html", {
        "request": request, "current_user": current_user,
        "quotes": quotes, "contacts_map": contacts_map, "opps_map": opps_map,
        "q": q, "status": status,
        "today": date.today(), "now": app_now(),
    })


# ── NEW ───────────────────────────────────────────────────────────────────────

@router.get("/new", response_class=HTMLResponse)
async def new_quote_form(
    request: Request,
    contact_id: str = Query(default=""),
    opp_id: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contacts_r = await db.execute(
        select(CRMContact)
        .where(CRMContact.status == "active", CRMContact.contact_type.in_(["buyer", "both"]))
        .order_by(CRMContact.company_name)
    )
    contacts = contacts_r.scalars().all()
    today = date.today()
    valid_until = today + timedelta(days=15)
    return templates.TemplateResponse("crm/quotes/form.html", {
        "request": request, "current_user": current_user,
        "quote": None, "contacts": contacts,
        "preselect": contact_id, "opp_id": opp_id,
        "material_types": MATERIAL_TYPES, "grades": GRADES,
        "today": today.isoformat(), "valid_until": valid_until.isoformat(),
    })


@router.post("/new")
async def create_quote(
    request: Request,
    contact_id:         str = Form(default=None),
    opp_id:             str = Form(default=None),
    quote_date:         str = Form(default=None),
    valid_until:        str = Form(default=None),
    payment_terms:      str = Form(default=None),
    special_conditions: str = Form(default=None),
    # line items sent as repeating fields
    device_type:        list = Form(default=[]),
    material_type:      list = Form(default=[]),
    grade:              list = Form(default=[]),
    quantity:           list = Form(default=[]),
    unit_price:         list = Form(default=[]),
    specs_note:         list = Form(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    def _d(v):
        if v and v.strip():
            try: return datetime.strptime(v.strip(), "%Y-%m-%d").date()
            except: return None
        return None

    quote_number = await _next_quote_number(db)
    quote = CRMQuote(
        quote_number=quote_number,
        contact_id=contact_id or None,
        quote_date=_d(quote_date) or date.today(),
        valid_until=_d(valid_until),
        payment_terms=payment_terms or None,
        special_conditions=special_conditions or None,
        status="draft",
        created_by=current_user.username,
    )
    db.add(quote)
    await db.flush()  # get quote.id

    grand_total = 0.0
    for i, dt in enumerate(device_type):
        if not dt or not dt.strip():
            continue
        qty  = int(quantity[i]) if i < len(quantity) and quantity[i].strip() else 1
        uprc = float(unit_price[i]) if i < len(unit_price) and unit_price[i].strip() else 0
        tot  = round(qty * uprc, 2)
        grand_total += tot
        item = CRMQuoteItem(
            quote_id=quote.id,
            line_number=i + 1,
            device_type=dt.strip(),
            material_type=material_type[i] if i < len(material_type) else None,
            grade=grade[i] if i < len(grade) else None,
            quantity=qty,
            unit_price=uprc,
            total_price=tot,
            specs_note=specs_note[i] if i < len(specs_note) and specs_note[i].strip() else None,
            sort_order=i,
        )
        db.add(item)

    quote.total_amount = round(grand_total, 2)

    # link to opportunity if provided
    if opp_id and opp_id.strip():
        opp_r = await db.execute(select(CRMSalesOpportunity).where(CRMSalesOpportunity.id == opp_id))
        opp = opp_r.scalar_one_or_none()
        if opp:
            opp.quote_id = quote.id
            if opp.stage in ("lead", "contacted", "requirement", "availability"):
                opp.stage = "quoted"

    await db.commit()
    return RedirectResponse(url=f"/crm/quotes/{quote.id}?success=Quote+created", status_code=302)


# ── DETAIL / PRINT PREVIEW ────────────────────────────────────────────────────

@router.get("/{quote_id}", response_class=HTMLResponse)
async def quote_detail(
    request: Request,
    quote_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMQuote).where(CRMQuote.id == quote_id))
    quote = result.scalar_one_or_none()
    if not quote:
        return RedirectResponse(url="/crm/quotes?error=Quote+not+found", status_code=302)

    items_r = await db.execute(
        select(CRMQuoteItem).where(CRMQuoteItem.quote_id == quote.id)
        .order_by(CRMQuoteItem.sort_order)
    )
    items = items_r.scalars().all()

    contact = None
    if quote.contact_id:
        cr = await db.execute(select(CRMContact).where(CRMContact.id == quote.contact_id))
        contact = cr.scalar_one_or_none()

    opp = None
    opp_r = await db.execute(
        select(CRMSalesOpportunity).where(CRMSalesOpportunity.quote_id == quote.id)
    )
    opp = opp_r.scalar_one_or_none()

    material_map = dict(MATERIAL_TYPES)
    today = date.today()
    is_expired = (quote.valid_until and quote.valid_until < today and
                  quote.status not in ("accepted", "rejected"))

    return templates.TemplateResponse("crm/quotes/detail.html", {
        "request": request, "current_user": current_user,
        "quote": quote, "items": items, "contact": contact, "opp": opp,
        "material_map": material_map, "is_expired": is_expired, "today": today,
    })


# ── PRINT VIEW (no sidebar — for printing) ───────────────────────────────────

@router.get("/{quote_id}/print", response_class=HTMLResponse)
async def quote_print(
    request: Request,
    quote_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMQuote).where(CRMQuote.id == quote_id))
    quote = result.scalar_one_or_none()
    if not quote:
        return RedirectResponse(url="/crm/quotes", status_code=302)

    items_r = await db.execute(
        select(CRMQuoteItem).where(CRMQuoteItem.quote_id == quote.id)
        .order_by(CRMQuoteItem.sort_order)
    )
    items = items_r.scalars().all()

    contact = None
    if quote.contact_id:
        cr = await db.execute(select(CRMContact).where(CRMContact.id == quote.contact_id))
        contact = cr.scalar_one_or_none()

    return templates.TemplateResponse("crm/quotes/print.html", {
        "request": request, "current_user": current_user,
        "quote": quote, "items": items, "contact": contact,
        "material_map": dict(MATERIAL_TYPES),
    })


# ── STATUS UPDATE ─────────────────────────────────────────────────────────────

@router.post("/{quote_id}/status")
async def update_status(
    request: Request,
    quote_id: str,
    new_status: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMQuote).where(CRMQuote.id == quote_id))
    quote = result.scalar_one_or_none()
    if not quote:
        return RedirectResponse(url="/crm/quotes?error=Not+found", status_code=302)
    quote.status = new_status
    if new_status == "sent":
        quote.sent_at = app_now()
    await db.commit()
    return RedirectResponse(url=f"/crm/quotes/{quote_id}?success=Status+updated+to+{new_status}", status_code=302)
