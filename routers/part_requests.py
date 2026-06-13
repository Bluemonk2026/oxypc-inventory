"""
Parts request → handover → sourcing workflow.

 - Engineer raises a request from the device Parts Consumption section.
 - Spare Parts Manager actions it on the Part Master page: Handover / Not In Stock / Procure.
 - Procure creates a sourcing request, closed by the Sales Manager in the CRM Dashboard.
"""
import uuid
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models.user import User, UserRole
from models.device import Device
from models.work_order import WorkOrder
from models.spare_parts import SparePart
from models.part_request import PartRequest, PartSourcingRequest
from auth.dependencies import get_current_user, require_roles, verify_csrf
from services.audit_engine import audit

router = APIRouter(tags=["part_requests"], dependencies=[Depends(verify_csrf)])

eng_allowed = require_roles(UserRole.admin, UserRole.inventory_manager,
                            UserRole.l1_engineer, UserRole.l2_engineer, UserRole.l3_engineer)
spm_allowed = require_roles(UserRole.admin, UserRole.spare_parts_manager)
sm_allowed = require_roles(UserRole.admin, UserRole.sales_manager)


def _as_uuid(val):
    try:
        return uuid.UUID(val)
    except Exception:
        return None


@router.post("/part-requests/create")
async def create_part_request(
    request: Request,
    barcode: str = Form(...),
    part_name: str = Form(...),
    part_id: str = Form(""),
    qty: int = Form(1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(eng_allowed),
):
    device = (await db.execute(select(Device).where(Device.barcode == barcode))).scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    wo = (await db.execute(
        select(WorkOrder).where(WorkOrder.device_id == device.id, WorkOrder.status != "completed")
        .order_by(WorkOrder.assigned_at.desc())
    )).scalars().first()
    stage = device.current_stage.value if device.current_stage else None
    if stage not in ("l1", "l2", "l3"):
        stage = wo.stage if wo else None
    pr = PartRequest(
        work_order_id=wo.id if wo else None,
        work_id=wo.work_id if wo else None,
        device_id=device.id, barcode=device.barcode, stage=stage,
        part_id=_as_uuid(part_id), part_name=part_name,
        requested_by=current_user.username, engineer_name=current_user.full_name,
        qty_requested=max(1, qty), status="requested",
    )
    db.add(pr)
    await audit(db, user=current_user, action="PART_REQUESTED", table_name="part_requests",
                record_id=None, new_value={"barcode": barcode, "part": part_name, "qty": qty},
                request=request)
    await db.commit()
    return RedirectResponse(url=f"/devices/{barcode}?success=Part+request+raised+for+{part_name}",
                            status_code=302)


@router.post("/part-requests/{req_id}/handover")
async def handover_part(req_id: str, request: Request, qty: int = Form(...),
                        db: AsyncSession = Depends(get_db), current_user: User = Depends(spm_allowed)):
    pr = (await db.execute(select(PartRequest).where(PartRequest.id == _as_uuid(req_id)))).scalar_one_or_none()
    if not pr:
        raise HTTPException(404, "Part request not found")
    pr.qty_handed_over = max(0, qty)
    pr.status = "handed_over"
    pr.actioned_at = app_now()
    pr.actioned_by = current_user.username
    await audit(db, user=current_user, action="PART_HANDOVER", table_name="part_requests",
                record_id=str(pr.id), new_value={"qty_handed_over": qty}, request=request)
    await db.commit()
    return RedirectResponse(url="/spare-parts?success=Part+handed+over", status_code=302)


@router.post("/part-requests/{req_id}/not-in-stock")
async def not_in_stock(req_id: str, request: Request,
                       db: AsyncSession = Depends(get_db), current_user: User = Depends(spm_allowed)):
    pr = (await db.execute(select(PartRequest).where(PartRequest.id == _as_uuid(req_id)))).scalar_one_or_none()
    if not pr:
        raise HTTPException(404, "Part request not found")
    pr.status = "not_in_stock"
    pr.actioned_at = app_now()
    pr.actioned_by = current_user.username
    await audit(db, user=current_user, action="PART_NOT_IN_STOCK", table_name="part_requests",
                record_id=str(pr.id), request=request)
    await db.commit()
    return RedirectResponse(url="/spare-parts?success=Marked+not+in+stock", status_code=302)


@router.post("/part-requests/{req_id}/procure")
async def procure_part(req_id: str, request: Request,
                       db: AsyncSession = Depends(get_db), current_user: User = Depends(spm_allowed)):
    pr = (await db.execute(select(PartRequest).where(PartRequest.id == _as_uuid(req_id)))).scalar_one_or_none()
    if not pr:
        raise HTTPException(404, "Part request not found")
    part = None
    if pr.part_id:
        part = (await db.execute(select(SparePart).where(SparePart.id == pr.part_id))).scalar_one_or_none()
    pr.status = "procure"
    pr.actioned_at = app_now()
    pr.actioned_by = current_user.username
    db.add(PartSourcingRequest(
        part_request_id=pr.id, part_id=pr.part_id,
        part_code=part.part_code if part else None, part_name=pr.part_name,
        qty_requested=pr.qty_requested, raised_by=current_user.username, status="open",
    ))
    await audit(db, user=current_user, action="PART_PROCURE", table_name="part_sourcing_requests",
                record_id=str(pr.id), new_value={"part": pr.part_name, "qty": pr.qty_requested},
                request=request)
    await db.commit()
    return RedirectResponse(url="/spare-parts?success=Sent+to+sourcing", status_code=302)


@router.post("/part-sourcing/{sr_id}/close")
async def close_sourcing(sr_id: str, request: Request,
                         source_deal_id: str = Form(...), qty_sourced: int = Form(...),
                         db: AsyncSession = Depends(get_db), current_user: User = Depends(sm_allowed)):
    sr = (await db.execute(
        select(PartSourcingRequest).where(PartSourcingRequest.id == _as_uuid(sr_id))
    )).scalar_one_or_none()
    if not sr:
        raise HTTPException(404, "Sourcing request not found")
    sr.status = "closed"
    sr.source_deal_id = source_deal_id
    sr.qty_sourced = max(0, qty_sourced)
    sr.closed_at = app_now()
    sr.closed_by = current_user.username
    await audit(db, user=current_user, action="SOURCING_CLOSED", table_name="part_sourcing_requests",
                record_id=str(sr.id), new_value={"source_deal_id": source_deal_id, "qty_sourced": qty_sourced},
                request=request)
    await db.commit()
    return RedirectResponse(url="/crm/?success=Sourcing+deal+closed", status_code=302)
