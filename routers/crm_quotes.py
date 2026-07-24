"""CRM Quotes router — quote builder with line items and print view."""
from datetime import datetime, date, timedelta
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user, verify_csrf
from services.po_pdf import build_po_pdf
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

    # ── Prefill from the Buyer Deal's lot ────────────────────────────────────
    # Opened via "Create Quote" on a Buyer Deal. The opportunity has no lot FK —
    # it was created by Marking Won a partner bid, so the bid is what carries
    # the lot. Fill the buyer and one line per model in that lot.
    prefill_items, preselect = [], contact_id
    if opp_id and opp_id.strip():
        opp = (await db.execute(
            select(CRMSalesOpportunity).where(CRMSalesOpportunity.id == opp_id)
        )).scalar_one_or_none()
        if opp:
            if not preselect and opp.contact_id:
                preselect = str(opp.contact_id)
            prefill_items = await _lot_prefill_for_opp(db, opp)

    today = date.today()
    valid_until = today + timedelta(days=15)
    return templates.TemplateResponse("crm/quotes/form.html", {
        "request": request, "current_user": current_user,
        "quote": None, "contacts": contacts,
        "preselect": preselect, "opp_id": opp_id,
        "prefill_items": prefill_items,
        "material_types": MATERIAL_TYPES, "grades": GRADES,
        "today": today.isoformat(), "valid_until": valid_until.isoformat(),
    })


async def _lot_prefill_for_opp(db: AsyncSession, opp) -> list[dict]:
    """One quote line per distinct model+grade in the lot this deal came from.

    Returns [] when the opportunity was created by hand rather than from a won
    bid — there is no lot to read in that case, and the form falls back to a
    single blank row.
    """
    from models.device import Device
    from utils.master_data import master_options
    from services.opportunity_lot import lot_for_opportunity

    lot = await lot_for_opportunity(db, opp.id)
    if not lot:
        return []

    rows = (await db.execute(
        select(Device.model, Device.grade, Device.sub_category,
               func.count(Device.id).label("qty"))
        .where(Device.lot_id == lot.id, Device.is_active == True)  # noqa: E712
        .group_by(Device.model, Device.grade, Device.sub_category)
        .order_by(func.count(Device.id).desc())
    )).all()
    if not rows:
        return []

    # Per-unit price comes from the lot's Target Selling Price spread over the
    # units in it — deliberately NOT device_price, which is a buying cost and
    # would quote the customer at cost if the operator didn't notice.
    total_qty = sum(r.qty for r in rows)
    unit = None
    if lot.selling_price and total_qty:
        unit = round(float(lot.selling_price) / total_qty, 2)

    # po_category is a Master Data list; only preselect when the device's
    # sub_category is actually one of its options, else leave it for the user.
    try:
        categories = set(master_options("po_category") or [])
    except Exception:
        categories = set()

    return [{
        "model": r.model or "",
        "grade": getattr(r.grade, "value", r.grade) or "",
        "po_category": r.sub_category if r.sub_category in categories else "",
        "quantity": r.qty,
        "unit_price": unit if unit else "",
    } for r in rows]


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
    grade:              list = Form(default=[]),
    po_category:        list = Form(default=[]),
    quantity:           list = Form(default=[]),
    unit_price:         list = Form(default=[]),
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
            # Column header is "Model Name" on the form — the column keeps its
            # original name so existing quotes and the print view still read.
            device_type=dt.strip(),
            grade=grade[i] if i < len(grade) else None,
            po_category=(po_category[i].strip() or None) if i < len(po_category) and po_category[i] else None,
            quantity=qty,
            unit_price=uprc,
            total_price=tot,
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


# ── DOCUMENT GENERATION ───────────────────────────────────────────────────────

class _QuoteLine:
    """Adapter so quote items can feed the shared PO/Quote PDF layout, which
    reads .item_name / .description / .quantity / .total_price."""

    def __init__(self, item):
        self.item_name   = item.device_type or ""
        bits = [b for b in (item.grade, item.po_category, item.specs_note) if b]
        self.description = " · ".join(bits)
        self.quantity    = item.quantity
        self.unit_price  = item.unit_price
        self.total_price = item.total_price


async def _quote_pdf(db: AsyncSession, quote, *, sections, term_ids=None):
    """Build the quote PDF. term_ids maps 'payment'/'delivery'/'disclaimer' to a
    single chosen TermsCondition id; absent or blank means include every active
    policy of that type (which is what the plain Download link does)."""
    import io
    from models.terms import TermsCondition
    from routers.settings import get_company_settings
    from routers.terms_conditions import get_active_terms

    items = (await db.execute(
        select(CRMQuoteItem).where(CRMQuoteItem.quote_id == quote.id)
        .order_by(CRMQuoteItem.sort_order)
    )).scalars().all()

    contact = None
    if quote.contact_id:
        contact = (await db.execute(
            select(CRMContact).where(CRMContact.id == quote.contact_id)
        )).scalar_one_or_none()

    async def _terms(kind, enabled):
        if not enabled:
            return []
        chosen = (term_ids or {}).get(kind)
        if chosen:
            row = (await db.execute(
                select(TermsCondition).where(TermsCondition.id == chosen)
            )).scalar_one_or_none()
            return [row] if row else []
        return await get_active_terms(db, kind)

    company = await get_company_settings(db)
    pdf_bytes = build_po_pdf(
        po_number=quote.quote_number,
        po_date=quote.quote_date.strftime("%d %b %Y") if quote.quote_date else "",
        company=company, contact=contact,
        line_items=[_QuoteLine(i) for i in items],
        payment_terms=await _terms("payment",    sections.get("payment")),
        delivery_terms=await _terms("delivery",  sections.get("delivery")),
        disclaimers=await _terms("disclaimer",   sections.get("conditions")),
        sections=sections, total_amount=float(quote.total_amount or 0),
        doc_title="QUOTATION", account_label="Account Details (Buyer)",
    )
    return StreamingResponse(
        io.BytesIO(pdf_bytes), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{quote.quote_number}.pdf"'},
    )


@router.post("/{quote_id}/generate")
async def generate_quote_doc(
    request: Request,
    quote_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate + download the quote document with the sections and the
    specific Terms & Conditions entries picked in the modal."""
    quote = (await db.execute(select(CRMQuote).where(CRMQuote.id == quote_id))).scalar_one_or_none()
    if not quote:
        return RedirectResponse(url="/crm/quotes?error=Quote+not+found", status_code=302)

    form = await request.form()
    term_ids = {
        "payment":    (form.get("payment_term_id")    or "").strip(),
        "delivery":   (form.get("delivery_term_id")   or "").strip(),
        "disclaimer": (form.get("disclaimer_term_id") or "").strip(),
    }
    sections = {
        "account":    bool(form.get("include_account")),
        "company":    bool(form.get("include_company")),
        "items":      bool(form.get("include_items")),
        # A terms block is included when the operator picked a policy for it.
        "payment":    bool(term_ids["payment"]),
        "delivery":   bool(term_ids["delivery"]),
        "conditions": bool(term_ids["disclaimer"]),
    }
    return await _quote_pdf(db, quote, sections=sections, term_ids=term_ids)


@router.get("/{quote_id}/download")
async def download_quote_doc(
    quote_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-download a quote with every section and all active terms."""
    quote = (await db.execute(select(CRMQuote).where(CRMQuote.id == quote_id))).scalar_one_or_none()
    if not quote:
        return RedirectResponse(url="/crm/quotes?error=Quote+not+found", status_code=302)
    return await _quote_pdf(db, quote, sections={
        "account": True, "company": True, "items": True,
        "payment": True, "delivery": True, "conditions": True,
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
