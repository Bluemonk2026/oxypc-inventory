"""
GRN Router — Goods Receipt Note
Records expected vs received quantity per lot and raises mismatch flags.
"""
from templates_config import templates
from datetime import datetime
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from models.user import User, UserRole
from models.lot import Lot
from models.engines import AuditLog
from auth.dependencies import get_current_user, require_roles, verify_csrf

router = APIRouter(prefix="/grn", tags=["grn"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager)


async def _next_grn_number(db: AsyncSession) -> str:
    """Auto-generate next GRN number in format GRN-YYYYMMDD-NNNN."""
    today = app_now().strftime("%Y%m%d")
    result = await db.execute(
        select(func.count(Lot.id)).where(
            Lot.grn_number_new.like(f"GRN-{today}-%")
        )
    )
    n = (result.scalar() or 0) + 1
    return f"GRN-{today}-{n:04d}"


@router.get("", response_class=HTMLResponse)
async def grn_list(request: Request, db: AsyncSession = Depends(get_db),
                   current_user: User = Depends(allowed)):
    from models.device import Device
    from sqlalchemy import func

    result = await db.execute(select(Lot).order_by(Lot.created_at.desc()))
    lots = result.scalars().all()
    lot_ids = [lot.id for lot in lots]

    dev_counts = {}
    if lot_ids:
        dev_rows = await db.execute(
            select(Device.lot_id, func.count(Device.id))
            .where(Device.lot_id.in_(lot_ids))
            .group_by(Device.lot_id)
        )
        dev_counts = dict(dev_rows.fetchall())

    lot_data = [
        {
            "lot": lot,
            "actual_devices": dev_counts.get(lot.id, 0),
            "grn_received": lot.qty or 0,
            "mismatch": dev_counts.get(lot.id, 0) != (lot.qty or 0),
        }
        for lot in lots
    ]

    return templates.TemplateResponse("grn/index.html", {
        "request": request, "lot_data": lot_data, "current_user": current_user,
    })


@router.get("/new", response_class=HTMLResponse)
async def grn_new_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    lot_id: str = Query(default=""),
):
    lots_result = await db.execute(select(Lot).order_by(Lot.lot_number))
    lots = lots_result.scalars().all()
    next_grn = await _next_grn_number(db)
    return templates.TemplateResponse("grn/form.html", {
        "request": request, "lots": lots, "current_user": current_user,
        "error": None, "next_grn": next_grn, "preselect_lot_id": lot_id,
    })


@router.post("/submit")
async def submit_grn(
    request: Request,
    lot_id: str = Form(...),
    expected_qty: int = Form(...),
    received_qty: int = Form(...),
    grn_number: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    lot_result = await db.execute(select(Lot).where(Lot.id == lot_id))
    lot = lot_result.scalar_one_or_none()
    if not lot:
        raise HTTPException(404, "Lot not found")

    mismatch = received_qty != expected_qty

    # Auto-generate GRN number if not provided
    if not grn_number:
        grn_number = await _next_grn_number(db)

    # Store GRN info on lot record
    lot.qty = received_qty   # update with actual received qty
    lot.grn_number_new = grn_number
    lot.grn_date = app_now()

    # Audit
    db.add(AuditLog(
        username=current_user.username,
        action="GRN_SUBMITTED",
        table_name="lots",
        record_id=str(lot.id),
        new_value=(
            f'{{"lot": "{lot.lot_number}", "expected": {expected_qty}, '
            f'"received": {received_qty}, "mismatch": {str(mismatch).lower()}}}'
        ),
        notes=f"Mismatch: {mismatch}" if mismatch else "OK",
    ))

    await db.commit()

    import urllib.parse
    success_msg = urllib.parse.quote(f"GRN recorded for {lot.lot_number}")
    redirect = f"/lots/{lot_id}?success={success_msg}"
    if mismatch:
        warn_msg = urllib.parse.quote(
            f"QTY MISMATCH — Expected {expected_qty}, Received {received_qty}. Check lot before proceeding."
        )
        redirect += f"&warning={warn_msg}"
    return RedirectResponse(url=redirect, status_code=302)
