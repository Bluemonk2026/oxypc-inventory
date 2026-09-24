"""All Deals — a simple deal header against a CRM Account (+ one of its
Locations) with a line-items table whose totals roll up into Amount.
Sidebar entry sits right after Manage Lots (External Partner section).
"""
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user, require_module_perm, verify_csrf
from models.user import User
from models.crm import CRMContact, CRMContactLocation
from models.deal import Deal, DealItem
from services.audit_engine import audit

router = APIRouter(prefix="/deals", tags=["deals"], dependencies=[Depends(verify_csrf)])

MODULE = "trade_partner_all_deals"


async def _next_deal_number(db: AsyncSession) -> str:
    # Derive from the highest existing suffix for this year, NOT count(*) —
    # same reasoning as CRMPurchaseOrder's _next_po_number: count-based
    # numbering collides after any row is ever deleted.
    prefix = f"DEAL-{app_now().year}-"
    mx = (await db.execute(
        select(func.max(Deal.deal_number)).where(Deal.deal_number.like(prefix + "%"))
    )).scalar()
    n = 1
    if mx:
        try:
            n = int(str(mx).rsplit("-", 1)[-1]) + 1
        except (ValueError, IndexError):
            n = 1
    return f"{prefix}{n:04d}"


def _parse_items(form) -> list[dict]:
    """Extract (item_name, quantity, unit_price) rows from the repeating
    Items section. Skips fully-blank rows. Total is always recomputed
    server-side from quantity * unit_price — never trusted from the client's
    own running-total display."""
    names = form.getlist("item_name[]")
    qtys = form.getlist("item_qty[]")
    prices = form.getlist("item_price[]")
    rows: list[dict] = []
    for i in range(max(len(names), len(qtys), len(prices))):
        name = (names[i] if i < len(names) else "").strip()
        if not name:
            continue
        try:
            qty = int(qtys[i]) if i < len(qtys) and qtys[i].strip() else 0
        except ValueError:
            qty = 0
        try:
            price = float(prices[i]) if i < len(prices) and prices[i].strip() else 0.0
        except ValueError:
            price = 0.0
        total = round(qty * price, 2)
        rows.append({"item_name": name, "quantity": qty, "unit_price": price, "total_price": total})
    return rows


@router.get("", response_class=HTMLResponse)
async def list_deals(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module_perm(MODULE, "enable")),
):
    deals = (await db.execute(
        select(Deal)
        .options(selectinload(Deal.contact), selectinload(Deal.location), selectinload(Deal.items))
        .order_by(Deal.created_at.desc())
    )).scalars().all()

    contacts = (await db.execute(
        select(CRMContact)
        .where(CRMContact.status == "active", CRMContact.is_trashed == False)
        .order_by(CRMContact.company_name)
    )).scalars().all()

    locations = (await db.execute(
        select(CRMContactLocation).order_by(CRMContactLocation.sort_order)
    )).scalars().all()
    locations_by_contact: dict[str, list[dict]] = {}
    for loc in locations:
        locations_by_contact.setdefault(str(loc.contact_id), []).append({
            "id": str(loc.id),
            "label": ", ".join(filter(None, [loc.address, loc.city, loc.state])) or "Location",
        })

    from utils.user_lookup import added_by_display_map
    added_by = await added_by_display_map(db)

    return templates.TemplateResponse("deals/list.html", {
        "request": request, "current_user": current_user,
        "deals": deals, "contacts": contacts,
        "locations_by_contact": locations_by_contact,
        "added_by": added_by,
    })


@router.post("/new")
async def create_deal(
    request: Request,
    contact_id: str = Form(...),
    location_id: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module_perm(MODULE, "add")),
):
    contact = (await db.execute(select(CRMContact).where(CRMContact.id == contact_id))).scalar_one_or_none()
    if not contact:
        return RedirectResponse(url="/deals?error=Account+not+found", status_code=302)

    item_rows = _parse_items(await request.form())
    if not item_rows:
        return RedirectResponse(url="/deals?error=Add+at+least+one+item", status_code=302)

    for _attempt in range(3):
        deal_number = await _next_deal_number(db)
        deal = Deal(
            deal_number=deal_number, contact_id=contact.id,
            location_id=location_id or None,
            amount=round(sum(r["total_price"] for r in item_rows), 2),
            created_by=current_user.username,
        )
        db.add(deal)
        try:
            await db.flush()  # assigns deal.id; raises on duplicate deal_number
        except IntegrityError:
            await db.rollback()
            continue
        for i, row in enumerate(item_rows):
            db.add(DealItem(
                deal_id=deal.id, item_name=row["item_name"], quantity=row["quantity"],
                unit_price=row["unit_price"], total_price=row["total_price"], sort_order=i,
            ))
        await audit(db, user=current_user, action="DEAL_CREATED",
                    table_name="deals", record_id=str(deal.id),
                    new_value={"deal_number": deal_number, "amount": float(deal.amount)}, request=request)
        await db.commit()
        return RedirectResponse(url="/deals?success=Deal+created", status_code=302)
    return RedirectResponse(url="/deals?error=Failed+to+generate+unique+Deal+ID,+please+retry", status_code=302)


@router.post("/{deal_id}/approve")
async def approve_deal(
    deal_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module_perm(MODULE, "edit")),
):
    deal = (await db.execute(select(Deal).where(Deal.id == deal_id))).scalar_one_or_none()
    if not deal:
        raise HTTPException(404, "Deal not found")
    if deal.status != "pending":
        return RedirectResponse(url=f"/deals?error=Deal+already+{deal.status}", status_code=302)
    deal.status = "approved"
    deal.approved_by = current_user.username
    deal.approved_at = app_now()
    await audit(db, user=current_user, action="DEAL_APPROVED",
                table_name="deals", record_id=str(deal.id),
                new_value={"approved_by": current_user.username}, request=request)
    await db.commit()
    return RedirectResponse(url="/deals?success=Deal+approved", status_code=302)


@router.post("/{deal_id}/payment")
async def mark_deal_paid(
    deal_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module_perm(MODULE, "edit")),
):
    deal = (await db.execute(select(Deal).where(Deal.id == deal_id))).scalar_one_or_none()
    if not deal:
        raise HTTPException(404, "Deal not found")
    if deal.payment_status == "paid":
        return RedirectResponse(url="/deals?error=Deal+already+paid", status_code=302)
    deal.payment_status = "paid"
    deal.paid_by = current_user.username
    deal.paid_at = app_now()
    await audit(db, user=current_user, action="DEAL_PAID",
                table_name="deals", record_id=str(deal.id),
                new_value={"paid_by": current_user.username}, request=request)
    await db.commit()
    return RedirectResponse(url="/deals?success=Deal+marked+as+paid", status_code=302)


@router.post("/{deal_id}/delete")
async def delete_deal(
    deal_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module_perm(MODULE, "edit")),
):
    deal = (await db.execute(select(Deal).where(Deal.id == deal_id))).scalar_one_or_none()
    if not deal:
        raise HTTPException(404, "Deal not found")
    await audit(db, user=current_user, action="DEAL_DELETED",
                table_name="deals", record_id=str(deal.id),
                old_value={"deal_number": deal.deal_number, "amount": float(deal.amount)}, request=request)
    await db.delete(deal)
    await db.commit()
    return RedirectResponse(url="/deals?success=Deal+deleted", status_code=302)
