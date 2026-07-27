"""Procure Dashboard — a single "Pending Requests" view for procurement,
combining the two request queues that used to live on separate pages:
Part Sourcing (already on CRM Dashboard) and Device Sourcing (previously
only actionable from the Telecaller Model Request queue as a stock
fulfillment). This page's Device Sourcing tab is procurement-only: it lets
Sales Manager/admin close a model request against an actual CRM Sourcing
Deal, distinct from TRC's "Update" (fulfil from existing stock)."""
import uuid
from templates_config import templates
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models.user import User, UserRole
from models.crm import CRMSourcingDeal
from models.part_request import PartSourcingRequest
from models.model_requests import ModelRequest
from auth.dependencies import get_current_user, require_roles, verify_csrf
from services.audit_engine import audit

router = APIRouter(prefix="/procure-dashboard", tags=["procure-dashboard"],
                   dependencies=[Depends(verify_csrf)])
sm_allowed = require_roles(UserRole.admin, UserRole.sales_manager)

STATUS_BADGE = {
    "open": "warning text-dark",
    "partially_fulfilled": "info text-dark",
    "fulfilled": "success",
    "closed": "success",
    "cancelled": "secondary",
}


@router.get("", response_class=HTMLResponse)
async def procure_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    is_sm = current_user.role in (UserRole.admin, UserRole.sales_manager)

    # ── Part Sourcing tab (same data as CRM Dashboard's table) ──────────────
    ps_r = await db.execute(
        select(PartSourcingRequest).order_by(PartSourcingRequest.created_at.desc()).limit(200)
    )
    part_sourcing = ps_r.scalars().all()

    open_deals_r = await db.execute(
        select(CRMSourcingDeal)
        .where(CRMSourcingDeal.stage.notin_(["won", "lost"]))
        .order_by(CRMSourcingDeal.created_at.desc())
    )
    sourcing_deals_for_close = open_deals_r.scalars().all()

    deal_map = {}
    linked_ids = [s.source_deal_id for s in part_sourcing if s.source_deal_id]
    if linked_ids:
        valid_ids = []
        for lid in linked_ids:
            try:
                valid_ids.append(str(uuid.UUID(lid)))
            except (ValueError, AttributeError, TypeError):
                continue
        if valid_ids:
            dm_r = await db.execute(select(CRMSourcingDeal).where(CRMSourcingDeal.id.in_(valid_ids)))
            for d in dm_r.scalars().all():
                deal_map[str(d.id)] = d

    # ── Device Sourcing tab (Telecaller Model Request queue, without
    #    Matching Stock, with a procurement-only Close Deal action) ─────────
    dr_r = await db.execute(
        select(ModelRequest)
        .where(ModelRequest.status.notin_(["cancelled", "closed"]))
        .order_by(ModelRequest.created_at.desc())
        .limit(200)
    )
    device_sourcing = dr_r.scalars().all()

    return templates.TemplateResponse("procure/dashboard.html", {
        "request": request, "current_user": current_user, "is_sm": is_sm,
        "part_sourcing": part_sourcing,
        "sourcing_deals_for_close": sourcing_deals_for_close,
        "deal_map": deal_map,
        "device_sourcing": device_sourcing,
        "status_badge": STATUS_BADGE,
        "success": request.query_params.get("success"),
    })


@router.post("/device-sourcing/{request_id}/close")
async def close_device_sourcing(
    request_id: str,
    request: Request,
    source_deal_id: str = Form(...),
    qty_sourced: int = Form(...),
    sourcing_notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(sm_allowed),
):
    try:
        rid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(404, "Request not found")
    mr = (await db.execute(select(ModelRequest).where(ModelRequest.id == rid))).scalar_one_or_none()
    if not mr:
        raise HTTPException(404, "Request not found")

    mr.source_deal_id = source_deal_id.strip()
    mr.qty_fulfilled = max(0, qty_sourced)
    mr.sourcing_notes = sourcing_notes.strip() or None
    mr.status = "closed"
    mr.closed_by = current_user.username
    mr.closed_at = app_now()

    await audit(db, action="MODEL_REQUEST_SOURCING_CLOSED", user=current_user,
                table_name="model_requests", record_id=str(mr.id),
                new_value={"source_deal_id": source_deal_id, "qty_sourced": qty_sourced}, request=request)
    await db.commit()
    return RedirectResponse(url="/procure-dashboard?success=Sourcing+deal+closed", status_code=302)
