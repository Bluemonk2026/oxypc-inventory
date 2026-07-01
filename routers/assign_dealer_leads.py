"""Assign Dealer Leads — admin/manager view over the shared Dealer table with
checkbox multi-select bulk assignment to a user. Add/Bulk-upload/Sample reuse
the existing Dealers module endpoints; this module only adds the bulk-assign
workflow on top of the same Dealer records."""
from templates_config import templates
from fastapi import APIRouter, Depends, Form, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from database import get_db
from models.dealers import Dealer
from models.user import User
from auth.dependencies import get_current_user, verify_csrf, require_module_perm
from services.audit_engine import audit

router = APIRouter(prefix="/assign-dealer-leads", tags=["assign-dealer-leads"])

require_view = require_module_perm("assign_dealer_leads", "enable")


@router.get("", response_class=HTMLResponse)
async def list_assign_dealer_leads(
    request: Request,
    q: str = Query(default=""),
    status: str = Query(default=""),
    assigned: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_view),
):
    base_query = select(Dealer)
    if q:
        like = f"%{q}%"
        base_query = base_query.where(or_(
            Dealer.business_name.ilike(like),
            Dealer.contact_person.ilike(like),
            Dealer.phone.ilike(like),
            Dealer.city.ilike(like),
            Dealer.dealer_code.ilike(like),
        ))
    if status:
        base_query = base_query.where(Dealer.status == status)
    if assigned:
        if assigned == "__unassigned__":
            base_query = base_query.where(Dealer.assigned_to.is_(None))
        else:
            base_query = base_query.where(Dealer.assigned_to == assigned)

    dealers = (await db.execute(
        base_query.order_by(Dealer.created_at.desc())
    )).scalars().all()

    # Active users for the Assign User modal + filter dropdown
    users_result = await db.execute(
        select(User).where(User.status == True).order_by(User.full_name)
    )
    all_users = users_result.scalars().all()

    total_count = len(dealers)
    unassigned_count = sum(1 for d in dealers if not d.assigned_to)

    return templates.TemplateResponse("assign_dealer_leads/list.html", {
        "request": request,
        "current_user": current_user,
        "dealers": dealers,
        "all_users": all_users,
        "q": q,
        "status": status,
        "assigned": assigned,
        "total_count": total_count,
        "unassigned_count": unassigned_count,
    })


@router.post("/assign")
async def bulk_assign_dealers(
    request: Request,
    dealer_ids: list[str] = Form(...),
    assigned_to: str = Form(...),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_view),
    _perm: User = Depends(require_module_perm("assign_dealer_leads", "edit")),
):
    result = await db.execute(select(Dealer).where(Dealer.id.in_(dealer_ids)))
    dealers = result.scalars().all()
    for dealer in dealers:
        dealer.assigned_to = assigned_to

    await audit(
        db, user=current_user, action="DEALER_LEADS_BULK_ASSIGNED",
        table_name="dealers", record_id=",".join(str(d.id) for d in dealers),
        new_value={"assigned_to": assigned_to, "dealer_count": len(dealers)},
        request=request,
    )
    await db.commit()
    return RedirectResponse(
        url=f"/assign-dealer-leads?success={len(dealers)}+dealer(s)+assigned+to+{assigned_to}",
        status_code=302,
    )


@router.post("/{dealer_id}/delete")
async def delete_dealer_lead(
    request: Request,
    dealer_id: str,
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_view),
    _perm: User = Depends(require_module_perm("assign_dealer_leads", "edit")),
):
    """Soft-delete: dealer orders/calls/credit-notes reference this record, and
    business records are never hard-deleted — set status=inactive instead."""
    result = await db.execute(select(Dealer).where(Dealer.id == dealer_id))
    dealer = result.scalar_one_or_none()
    if not dealer:
        return RedirectResponse(url="/assign-dealer-leads?error=Dealer+not+found", status_code=302)

    await audit(
        db, user=current_user, action="DEALER_LEAD_DEACTIVATED",
        table_name="dealers", record_id=str(dealer.id),
        old_value={"status": dealer.status},
        new_value={"status": "inactive"},
        request=request,
    )
    dealer.status = "inactive"
    await db.commit()
    return RedirectResponse(url="/assign-dealer-leads?success=Dealer+deactivated", status_code=302)
