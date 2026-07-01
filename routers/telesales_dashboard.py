"""TeleSales Dashboard — Business Snapshot analysing Dealers, Device Requested
(TelecallerDispatchRequest), Sales List, and Returns. Moved out of the
Telecalling Dashboard into its own page."""
from templates_config import templates
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case as sa_case
from sqlalchemy.orm import selectinload
from database import get_db
from models.dealers import Dealer
from models.dispatch_request import TelecallerDispatchRequest
from models.sales import Sale, Return
from models.user import User, UserRole
from auth.dependencies import get_current_user, require_module_perm

router = APIRouter(prefix="/telesales-dashboard", tags=["telesales-dashboard"])


@router.get("", response_class=HTMLResponse)
async def telesales_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _perm: User = Depends(require_module_perm("telesales_dashboard", "enable")),
):
    today = app_now().date()

    # Admin + Sales Manager see the whole business; everyone else sees only
    # data tied to their own username (their dealers, their requests, their sales).
    is_manager_view = current_user.role in (UserRole.admin, UserRole.sales_manager)
    month_start = today.replace(day=1)

    # Dealers
    dealer_q = select(func.count(Dealer.id))
    active_dealer_q = select(func.count(Dealer.id)).where(Dealer.status == "active")
    if not is_manager_view:
        dealer_q = dealer_q.where(Dealer.assigned_to == current_user.username)
        active_dealer_q = active_dealer_q.where(Dealer.assigned_to == current_user.username)
    dealer_stats = {
        "total": int((await db.execute(dealer_q)).scalar() or 0),
        "active": int((await db.execute(active_dealer_q)).scalar() or 0),
    }

    # Device Requested (TelecallerDispatchRequest — raised from Ready to Sale)
    dr_stmt = select(
        func.count(TelecallerDispatchRequest.id),
        func.count(sa_case((TelecallerDispatchRequest.status == "requested", 1))),
        func.count(sa_case((TelecallerDispatchRequest.status == "approved", 1))),
    )
    if not is_manager_view:
        dr_stmt = dr_stmt.where(TelecallerDispatchRequest.telecaller_username == current_user.username)
    dr_row = (await db.execute(dr_stmt)).one()
    device_request_stats = {
        "total":    int(dr_row[0] or 0),
        "pending":  int(dr_row[1] or 0),
        "approved": int(dr_row[2] or 0),
    }
    dr_list_stmt = (
        select(TelecallerDispatchRequest)
        .options(selectinload(TelecallerDispatchRequest.device))
        .order_by(TelecallerDispatchRequest.created_at.desc())
        .limit(8)
    )
    if not is_manager_view:
        dr_list_stmt = dr_list_stmt.where(TelecallerDispatchRequest.telecaller_username == current_user.username)
    recent_device_requests = (await db.execute(dr_list_stmt)).scalars().all()

    # Sales List (today + month-to-date)
    sales_stmt = select(
        func.count(sa_case((func.date(Sale.sold_at) == today, 1))),
        func.coalesce(func.sum(sa_case((func.date(Sale.sold_at) == today, Sale.sale_price), else_=0)), 0),
        func.count(sa_case((Sale.sold_at >= month_start, 1))),
        func.coalesce(func.sum(sa_case((Sale.sold_at >= month_start, Sale.sale_price), else_=0)), 0),
    )
    if not is_manager_view:
        sales_stmt = sales_stmt.where(Sale.sold_by == current_user.username)
    sales_row = (await db.execute(sales_stmt)).one()
    sales_stats = {
        "today_count":   int(sales_row[0] or 0),
        "today_revenue": float(sales_row[1] or 0),
        "month_count":   int(sales_row[2] or 0),
        "month_revenue": float(sales_row[3] or 0),
    }
    recent_sales_stmt = select(Sale).order_by(Sale.sold_at.desc()).limit(8)
    if not is_manager_view:
        recent_sales_stmt = recent_sales_stmt.where(Sale.sold_by == current_user.username)
    recent_sales = (await db.execute(recent_sales_stmt)).scalars().all()

    # Returns (month-to-date, tied back to the agent via Sale.sold_by)
    returns_count_stmt = (
        select(func.count(Return.id))
        .join(Sale, Return.sale_id == Sale.id)
        .where(Return.return_date >= month_start)
    )
    if not is_manager_view:
        returns_count_stmt = returns_count_stmt.where(Sale.sold_by == current_user.username)
    returns_month_count = int((await db.execute(returns_count_stmt)).scalar() or 0)

    recent_returns_stmt = (
        select(Return, Sale)
        .join(Sale, Return.sale_id == Sale.id)
        .order_by(Return.return_date.desc())
        .limit(8)
    )
    if not is_manager_view:
        recent_returns_stmt = recent_returns_stmt.where(Sale.sold_by == current_user.username)
    recent_returns = (await db.execute(recent_returns_stmt)).all()

    return templates.TemplateResponse("telesales/dashboard.html", {
        "request": request,
        "current_user": current_user,
        "is_manager_view": is_manager_view,
        "dealer_stats": dealer_stats,
        "device_request_stats": device_request_stats,
        "recent_device_requests": recent_device_requests,
        "sales_stats": sales_stats,
        "recent_sales": recent_sales,
        "returns_month_count": returns_month_count,
        "recent_returns": recent_returns,
    })
