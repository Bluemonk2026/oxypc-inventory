"""CRM Analytics & Pipeline Reports."""
from datetime import datetime, timedelta
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user
from models.user import User
from models.crm import (
    CRMSourcingDeal, CRMSalesOpportunity, CRMActivity,
    SOURCING_STAGES, SALES_STAGES,
)

router = APIRouter(prefix="/crm/reports", tags=["crm-reports"])


@router.get("", response_class=HTMLResponse)
async def crm_reports_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    total_sourcing = (await db.execute(select(func.count(CRMSourcingDeal.id)))).scalar() or 0
    won_sourcing   = (await db.execute(select(func.count(CRMSourcingDeal.id)).where(CRMSourcingDeal.stage == "won"))).scalar() or 0
    total_sales    = (await db.execute(select(func.count(CRMSalesOpportunity.id)))).scalar() or 0
    won_sales      = (await db.execute(select(func.count(CRMSalesOpportunity.id)).where(CRMSalesOpportunity.stage == "won"))).scalar() or 0
    total_acts     = (await db.execute(select(func.count(CRMActivity.id)))).scalar() or 0
    return templates.TemplateResponse("crm/reports/index.html", {
        "request": request, "current_user": current_user,
        "total_sourcing": total_sourcing, "won_sourcing": won_sourcing,
        "total_sales": total_sales, "won_sales": won_sales,
        "total_activities": total_acts,
        "sourcing_win_rate": round(won_sourcing / total_sourcing * 100) if total_sourcing else 0,
        "sales_win_rate": round(won_sales / total_sales * 100) if total_sales else 0,
    })


@router.get("/funnel", response_class=HTMLResponse)
async def pipeline_funnel(
    request: Request,
    pipeline: str = Query(default="sourcing"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if pipeline == "sourcing":
        stages = SOURCING_STAGES
        Model = CRMSourcingDeal
    else:
        stages = SALES_STAGES
        Model = CRMSalesOpportunity

    funnel = []
    for val, label in stages:
        count_r = await db.execute(select(func.count(Model.id)).where(Model.stage == val))
        count = count_r.scalar() or 0
        if pipeline == "sourcing":
            val_r = await db.execute(
                select(func.coalesce(func.sum(CRMSourcingDeal.our_offer_total), 0))
                .where(CRMSourcingDeal.stage == val)
            )
        else:
            val_r = await db.execute(
                select(func.coalesce(func.sum(CRMSalesOpportunity.estimated_value), 0))
                .where(CRMSalesOpportunity.stage == val)
            )
        value = float(val_r.scalar() or 0)
        funnel.append({"stage": val, "label": label, "count": count, "value": value})

    return templates.TemplateResponse("crm/reports/funnel.html", {
        "request": request, "current_user": current_user,
        "funnel": funnel, "pipeline": pipeline,
    })


@router.get("/win-loss", response_class=HTMLResponse)
async def win_loss_analysis(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sourcing_rows = (await db.execute(
        select(CRMSourcingDeal.source_type, CRMSourcingDeal.stage, func.count().label("cnt"))
        .where(CRMSourcingDeal.stage.in_(["won", "lost"]))
        .group_by(CRMSourcingDeal.source_type, CRMSourcingDeal.stage)
    )).all()
    sales_rows = (await db.execute(
        select(CRMSalesOpportunity.buyer_type, CRMSalesOpportunity.stage, func.count().label("cnt"))
        .where(CRMSalesOpportunity.stage.in_(["won", "lost"]))
        .group_by(CRMSalesOpportunity.buyer_type, CRMSalesOpportunity.stage)
    )).all()
    by_user = (await db.execute(
        select(CRMSourcingDeal.assigned_to, CRMSourcingDeal.stage, func.count().label("cnt"))
        .where(CRMSourcingDeal.stage.in_(["won", "lost"]))
        .group_by(CRMSourcingDeal.assigned_to, CRMSourcingDeal.stage)
    )).all()
    return templates.TemplateResponse("crm/reports/win_loss.html", {
        "request": request, "current_user": current_user,
        "sourcing_rows": sourcing_rows,
        "sales_rows": sales_rows,
        "by_user": by_user,
    })


@router.get("/activity-leaderboard", response_class=HTMLResponse)
async def activity_leaderboard(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    since = app_now() - timedelta(days=days)
    rows = (await db.execute(
        select(
            CRMActivity.performed_by,
            CRMActivity.activity_type,
            func.count().label("cnt"),
        )
        .where(CRMActivity.activity_date >= since)
        .group_by(CRMActivity.performed_by, CRMActivity.activity_type)
        .order_by(CRMActivity.performed_by, func.count().desc())
    )).all()

    leaderboard = {}
    for row in rows:
        user = row.performed_by or "Unknown"
        if user not in leaderboard:
            leaderboard[user] = {"call": 0, "whatsapp": 0, "visit": 0, "email": 0, "meeting": 0, "note": 0, "total": 0}
        if row.activity_type in leaderboard[user]:
            leaderboard[user][row.activity_type] = row.cnt
        leaderboard[user]["total"] += row.cnt

    leaderboard = sorted(leaderboard.items(), key=lambda x: x[1]["total"], reverse=True)

    return templates.TemplateResponse("crm/reports/activity_leaderboard.html", {
        "request": request, "current_user": current_user,
        "leaderboard": leaderboard, "days": days,
    })
