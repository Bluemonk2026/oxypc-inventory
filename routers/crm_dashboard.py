"""CRM Dashboard router — main /crm/ landing page with pipeline KPIs."""
from datetime import datetime
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user
from models.user import User
from models.crm import (
    CRMContact, CRMSourcingDeal, CRMSalesOpportunity, CRMActivity,
    SOURCING_STAGES, SALES_STAGES,
)

router = APIRouter(prefix="/crm", tags=["crm-dashboard"])


@router.get("/", response_class=HTMLResponse)
async def crm_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = app_now()

    # ── Contact counts ────────────────────────────────────────────────────────
    contact_total_r = await db.execute(select(func.count(CRMContact.id)))
    contact_total   = contact_total_r.scalar() or 0

    buyer_count_r = await db.execute(
        select(func.count(CRMContact.id))
        .where(CRMContact.contact_type.in_(["buyer", "both"]))
    )
    buyer_count = buyer_count_r.scalar() or 0

    supplier_count_r = await db.execute(
        select(func.count(CRMContact.id))
        .where(CRMContact.contact_type.in_(["supplier", "both"]))
    )
    supplier_count = supplier_count_r.scalar() or 0

    # ── Sourcing pipeline ─────────────────────────────────────────────────────
    sd_r = await db.execute(
        select(CRMSourcingDeal)
        .where(CRMSourcingDeal.stage.notin_(["won", "lost"]))
        .order_by(CRMSourcingDeal.created_at.desc())
    )
    open_sourcing = sd_r.scalars().all()
    sourcing_pipeline_value = sum(
        float(d.our_offer_total or d.asking_price_total or 0) for d in open_sourcing
    )
    # funnel by stage
    sourcing_funnel = {}
    for stage_key, _ in SOURCING_STAGES:
        if stage_key in ("won", "lost"):
            continue
        sourcing_funnel[stage_key] = sum(1 for d in open_sourcing if d.stage == stage_key)

    # ── Sales pipeline ────────────────────────────────────────────────────────
    so_r = await db.execute(
        select(CRMSalesOpportunity)
        .where(CRMSalesOpportunity.stage.notin_(["won", "lost"]))
        .order_by(CRMSalesOpportunity.created_at.desc())
    )
    open_sales = so_r.scalars().all()
    sales_pipeline_value = sum(float(o.estimated_value or 0) for o in open_sales)
    sales_funnel = {}
    for stage_key, _ in SALES_STAGES:
        if stage_key in ("won", "lost"):
            continue
        sales_funnel[stage_key] = sum(1 for o in open_sales if o.stage == stage_key)

    # ── Follow-ups ────────────────────────────────────────────────────────────
    overdue_r = await db.execute(
        select(CRMActivity).where(
            CRMActivity.followup_done == False,
            CRMActivity.next_followup != None,
            CRMActivity.next_followup <= now,
        ).order_by(CRMActivity.next_followup).limit(10)
    )
    overdue_activities = overdue_r.scalars().all()

    today_r = await db.execute(
        select(CRMActivity).where(
            CRMActivity.followup_done == False,
            CRMActivity.next_followup != None,
            CRMActivity.next_followup > now,
            func.date(CRMActivity.next_followup) == now.date(),
        ).order_by(CRMActivity.next_followup)
    )
    today_activities = today_r.scalars().all()

    overdue_count = len(overdue_activities)
    today_count   = len(today_activities)

    # combine for display (overdue first)
    all_due = overdue_activities + today_activities

    # fetch deal titles for follow-ups
    deal_ids = [str(a.deal_id) for a in all_due if a.deal_id]
    sourcing_map, sales_map = {}, {}
    if deal_ids:
        sr = await db.execute(select(CRMSourcingDeal).where(CRMSourcingDeal.id.in_(deal_ids)))
        for d in sr.scalars().all():
            sourcing_map[str(d.id)] = d
        or2 = await db.execute(select(CRMSalesOpportunity).where(CRMSalesOpportunity.id.in_(deal_ids)))
        for o in or2.scalars().all():
            sales_map[str(o.id)] = o

    return templates.TemplateResponse("crm/dashboard.html", {
        "request": request, "current_user": current_user,
        # contacts
        "contact_total": contact_total,
        "buyer_count": buyer_count,
        "supplier_count": supplier_count,
        # sourcing
        "open_sourcing_count": len(open_sourcing),
        "sourcing_pipeline_value": sourcing_pipeline_value,
        "sourcing_funnel": sourcing_funnel,
        # sales
        "open_sales_count": len(open_sales),
        "sales_pipeline_value": sales_pipeline_value,
        "sales_funnel": sales_funnel,
        # follow-ups
        "overdue_count": overdue_count,
        "today_count": today_count,
        "all_due": all_due,
        "sourcing_map": sourcing_map,
        "sales_map": sales_map,
        "now": now,
        "stage_labels_sourcing": dict(SOURCING_STAGES),
        "stage_labels_sales":    dict(SALES_STAGES),
    })
