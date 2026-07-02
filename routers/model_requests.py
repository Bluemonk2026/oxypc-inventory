"""Model/config demand requests — Sales & Telecalling ask TRC (Inventory
Manager) for a configuration + quantity + grade, independent of any specific
existing device. TRC actions the queue: mark fulfilled/partial, optionally
noting which devices were allocated.
"""
from templates_config import templates
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

from database import get_db
from models.model_requests import ModelRequest
from models.device import Device, DeviceStage
from models.user import User, UserRole
from auth.dependencies import get_current_user, require_roles, verify_csrf
from services.audit_engine import audit

router = APIRouter(prefix="/model-requests", tags=["model-requests"], dependencies=[Depends(verify_csrf)])

# Sales + Telecalling raise requests; TRC (Inventory Manager) + admin fulfil them.
REQUEST_ROLES = (UserRole.admin, UserRole.sales, UserRole.sales_manager, UserRole.telecaller)
FULFIL_ROLES  = (UserRole.admin, UserRole.inventory_manager)

request_allowed = require_roles(*REQUEST_ROLES)
fulfil_allowed  = require_roles(*FULFIL_ROLES)

STATUS_BADGE = {
    "open": "warning text-dark",
    "partially_fulfilled": "info text-dark",
    "fulfilled": "success",
    "cancelled": "secondary",
}


async def _matching_ready_count(db: AsyncSession, req: ModelRequest) -> int:
    """Best-effort count of Ready-to-Sale devices matching this request's spec —
    shown to TRC as a hint, not an automatic allocation."""
    q = select(func.count(Device.id)).where(Device.current_stage == DeviceStage.ready_to_sale)
    if req.sub_category:
        q = q.where(Device.sub_category == req.sub_category)
    if req.brand:
        q = q.where(Device.brand.ilike(f"%{req.brand}%"))
    if req.model:
        q = q.where(Device.model.ilike(f"%{req.model}%"))
    if req.grade and req.grade != "Any":
        q = q.where(Device.grade == req.grade)
    return (await db.execute(q)).scalar() or 0


@router.get("", response_class=HTMLResponse)
async def list_requests(
    request: Request,
    status: str = Query(default=""),
    mine_only: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """TRC/admin see the full queue; Sales/Telecalling see their own requests
    by default (mine_only defaults on for non-fulfil roles)."""
    is_fulfiller = current_user.role in FULFIL_ROLES or current_user.role.value == "admin"

    q = select(ModelRequest).order_by(ModelRequest.created_at.desc())
    if status:
        q = q.where(ModelRequest.status == status)
    if not is_fulfiller or mine_only == "1":
        q = q.where(ModelRequest.requested_by == current_user.username)

    rows = (await db.execute(q)).scalars().all()

    match_counts = {}
    if is_fulfiller:
        for r in rows:
            if r.status in ("open", "partially_fulfilled"):
                match_counts[str(r.id)] = await _matching_ready_count(db, r)

    total = len(rows)
    open_count = sum(1 for r in rows if r.status == "open")
    partial_count = sum(1 for r in rows if r.status == "partially_fulfilled")
    fulfilled_count = sum(1 for r in rows if r.status == "fulfilled")

    return templates.TemplateResponse("model_requests/list.html", {
        "request": request,
        "current_user": current_user,
        "rows": rows,
        "match_counts": match_counts,
        "is_fulfiller": is_fulfiller,
        "status": status,
        "mine_only": mine_only,
        "total": total,
        "open_count": open_count,
        "partial_count": partial_count,
        "fulfilled_count": fulfilled_count,
        "status_badge": STATUS_BADGE,
    })


@router.get("/new", response_class=HTMLResponse)
async def new_request_form(
    request: Request,
    current_user: User = Depends(request_allowed),
):
    return templates.TemplateResponse("model_requests/form.html", {
        "request": request, "current_user": current_user,
    })


@router.post("/new")
async def create_request(
    request: Request,
    sub_category: str = Form(default=""),
    brand: str = Form(default=""),
    model: str = Form(default=""),
    cpu: str = Form(default=""),
    ram_gb: str = Form(default=""),
    storage_gb: str = Form(default=""),
    storage_type: str = Form(default=""),
    screen_size: str = Form(default=""),
    grade: str = Form(default="Any"),
    qty_requested: str = Form(default="1"),
    notes: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(request_allowed),
):
    try:
        qty = max(1, int(qty_requested))
    except ValueError:
        qty = 1
    ram_val = int(ram_gb) if ram_gb.strip().isdigit() else None
    storage_val = int(storage_gb) if storage_gb.strip().isdigit() else None

    req = ModelRequest(
        requested_by=current_user.username,
        requested_by_name=current_user.full_name,
        requested_by_role=current_user.role.value,
        sub_category=sub_category or None,
        brand=brand.strip() or None,
        model=model.strip() or None,
        cpu=cpu.strip() or None,
        ram_gb=ram_val,
        storage_gb=storage_val,
        storage_type=storage_type or None,
        screen_size=screen_size.strip() or None,
        grade=grade or "Any",
        qty_requested=qty,
        notes=notes.strip() or None,
    )
    db.add(req)
    await db.commit()
    return RedirectResponse(url="/model-requests?success=Request+submitted", status_code=302)


@router.post("/{req_id}/fulfil")
async def fulfil_request(
    request: Request,
    req_id: str,
    qty_fulfilled: str = Form(...),
    fulfillment_notes: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(fulfil_allowed),
):
    req = (await db.execute(select(ModelRequest).where(ModelRequest.id == req_id))).scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/model-requests?error=Request+not+found", status_code=302)

    try:
        qty = max(0, int(qty_fulfilled))
    except ValueError:
        qty = req.qty_fulfilled

    req.qty_fulfilled = min(qty, req.qty_requested)
    req.fulfillment_notes = fulfillment_notes.strip() or None
    req.fulfilled_by = current_user.username
    req.fulfilled_at = app_now()
    req.status = "fulfilled" if req.qty_fulfilled >= req.qty_requested else (
        "partially_fulfilled" if req.qty_fulfilled > 0 else "open"
    )

    await audit(
        db, user=current_user, action="MODEL_REQUEST_FULFILLED",
        table_name="model_requests", record_id=str(req.id),
        new_value={"qty_fulfilled": req.qty_fulfilled, "status": req.status},
        request=request,
    )
    await db.commit()
    return RedirectResponse(url="/model-requests?success=Request+updated", status_code=302)


@router.post("/{req_id}/cancel")
async def cancel_request(
    request: Request,
    req_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The original requester or an admin/TRC user can cancel an open request."""
    req = (await db.execute(select(ModelRequest).where(ModelRequest.id == req_id))).scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/model-requests?error=Request+not+found", status_code=302)
    if req.requested_by != current_user.username and current_user.role not in FULFIL_ROLES:
        return RedirectResponse(url="/model-requests?error=Not+authorized", status_code=302)

    req.status = "cancelled"
    await db.commit()
    return RedirectResponse(url="/model-requests?success=Request+cancelled", status_code=302)
