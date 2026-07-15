"""
Parts request → handover → sourcing workflow.

 - Engineer raises a request from the device Parts Consumption section.
 - Spare Parts Manager actions it on the Part Master page: Handover / Not In Stock / Procure.
 - Procure creates a sourcing request, closed by the Sales Manager in the CRM Dashboard.
"""
import uuid
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from database import get_db
from models.user import User, UserRole
from models.device import Device
from models.work_order import WorkOrder
from models.spare_parts import SparePart
from models.engines import SparePartsLedger
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
    part_category: str = Form(""),
    request_type: str = Form("new"),
    qty: int = Form(1),
    from_page: str = Form(""),
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

    # ── Resolve part_id to a real SparePart (BUG 3) ───────────────────────────
    # The spare-parts fulfilment page looks up stock by PartRequest.part_id, and
    # the repair/detail "In Stock" display shows the stock of the SparePart it
    # matched. If those diverge (or part_id arrives empty because a category→
    # name cascade came up blank), spare-parts shows 0 while repair shows stock.
    # Prefer the part_id the form sent (the exact record whose stock was shown);
    # otherwise fall back to the same fuzzy match the display uses so a real
    # SparePart id is stored rather than None.
    resolved_part_id = _as_uuid(part_id)
    if resolved_part_id:
        exists = (await db.execute(
            select(SparePart.id).where(SparePart.id == resolved_part_id)
        )).scalar_one_or_none()
        if not exists:
            resolved_part_id = None
    if not resolved_part_id:
        conds = [SparePart.name.ilike(f"%{part_name}%")]
        if part_category.strip():
            conds.append(SparePart.category == part_category.strip())
        sp_match = (await db.execute(
            select(SparePart).where(or_(*conds)).order_by(SparePart.qty_in_stock.desc())
        )).scalars().first()
        if sp_match:
            resolved_part_id = sp_match.id

    pr = PartRequest(
        work_order_id=wo.id if wo else None,
        work_id=wo.work_id if wo else None,
        device_id=device.id, barcode=device.barcode, stage=stage,
        part_id=resolved_part_id, part_name=part_name,
        part_category=part_category.strip() or None,
        request_type=request_type.strip() or "new",
        requested_by=current_user.username, engineer_name=current_user.full_name,
        qty_requested=max(1, qty), status="requested",
    )
    db.add(pr)
    await audit(db, user=current_user, action="PART_REQUESTED", table_name="part_requests",
                record_id=None, new_value={"barcode": barcode, "part": part_name, "qty": qty},
                request=request)
    await db.commit()
    suffix = f"&from={from_page}" if from_page else ""
    return RedirectResponse(url=f"/devices/{barcode}?success=Part+request+raised+for+{part_name}{suffix}",
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


@router.post("/part-requests/{req_id}/validate-receiving")
async def validate_receiving(req_id: str, request: Request,
                             db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Engineer verifies a handed-over part on the Device Profile page —
    flips status to 'received' ('Changed' pill client-side). Called via
    fetch() (no form body), so it returns JSON rather than redirecting."""
    pr = (await db.execute(select(PartRequest).where(PartRequest.id == _as_uuid(req_id)))).scalar_one_or_none()
    if not pr:
        raise HTTPException(404, "Part request not found")
    pr.status = "received"
    pr.actioned_at = app_now()
    pr.actioned_by = current_user.username
    await audit(db, user=current_user, action="PART_RECEIVED", table_name="part_requests",
                record_id=str(pr.id), request=request)
    await db.commit()
    return JSONResponse({"ok": True})


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
    was_already_closed = sr.status == "closed"
    sr.status = "closed"
    sr.source_deal_id = source_deal_id
    sr.qty_sourced = max(0, qty_sourced)
    sr.closed_at = app_now()
    sr.closed_by = current_user.username

    # If this request was already verified on the Part Master "Sourcing
    # Requests" tab (verify_sourcing() below) before the deal was closed
    # here, its qty_sourced was still 0 at verify-time so no stock was
    # credited then. Credit it now that the real quantity is known — but
    # only the first time this deal is closed, so re-submitting an
    # already-closed deal doesn't double-credit stock.
    if sr.verified and not was_already_closed and sr.part_id and sr.qty_sourced:
        part = (await db.execute(select(SparePart).where(SparePart.id == sr.part_id))).scalar_one_or_none()
        if part:
            db.add(SparePartsLedger(
                part_id=part.id, entry_type="IN", qty=sr.qty_sourced,
                cost_per_unit=float(part.unit_price), total_cost=sr.qty_sourced * float(part.unit_price),
                reference_type="sourcing_verified", reference_id=str(sr.id),
                created_by=current_user.username,
                notes=f"Sourcing request {sr.id} closed after verify — {sr.qty_sourced}x {sr.part_name}",
            ))
            part.qty_in_stock += sr.qty_sourced

    await audit(db, user=current_user, action="SOURCING_CLOSED", table_name="part_sourcing_requests",
                record_id=str(sr.id), new_value={"source_deal_id": source_deal_id, "qty_sourced": qty_sourced},
                request=request)
    await db.commit()
    return RedirectResponse(url="/crm/?success=Sourcing+deal+closed", status_code=302)


@router.post("/part-sourcing/{sr_id}/verify")
async def verify_sourcing(sr_id: str, request: Request,
                          db: AsyncSession = Depends(get_db), current_user: User = Depends(spm_allowed)):
    """Spare Parts Manager verifies the sourced documents/quantity on the Part Master
    'Sourcing Requests' tab. Independent of the Sales Manager's Close Deal step."""
    sr = (await db.execute(
        select(PartSourcingRequest).where(PartSourcingRequest.id == _as_uuid(sr_id))
    )).scalar_one_or_none()
    if not sr:
        return JSONResponse({"ok": False, "error": "Sourcing request not found"}, status_code=404)
    if sr.verified:
        return JSONResponse({"ok": False, "error": "Already verified"}, status_code=409)
    sr.verified = True
    sr.verified_at = app_now()
    sr.verified_by = current_user.username

    # Credit the sourced quantity into Part Master stock (In Stock column),
    # via a ledger entry so the computed-stock and qty_in_stock column stay
    # in sync — same pattern as every other stock-affecting action.
    if sr.part_id and sr.qty_sourced:
        part = (await db.execute(select(SparePart).where(SparePart.id == sr.part_id))).scalar_one_or_none()
        if part:
            db.add(SparePartsLedger(
                part_id=part.id, entry_type="IN", qty=sr.qty_sourced,
                cost_per_unit=float(part.unit_price), total_cost=sr.qty_sourced * float(part.unit_price),
                reference_type="sourcing_verified", reference_id=str(sr.id),
                created_by=current_user.username,
                notes=f"Sourcing request {sr.id} verified — {sr.qty_sourced}x {sr.part_name}",
            ))
            part.qty_in_stock += sr.qty_sourced

    # Revert the originating Part Request from "procure" back to "requested"
    # now that stock is available — Part Request tab's Status column then
    # shows "Available" and its Action column shows the Handover button
    # again (instead of "Sent for Sourcing").
    if sr.part_request_id:
        pr = (await db.execute(select(PartRequest).where(PartRequest.id == sr.part_request_id))).scalar_one_or_none()
        if pr and pr.status == "procure":
            pr.status = "requested"

    await audit(db, user=current_user, action="SOURCING_VERIFIED", table_name="part_sourcing_requests",
                record_id=str(sr.id), new_value={"verified_by": current_user.username, "qty_sourced": sr.qty_sourced},
                request=request)
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/part-sourcing/{sr_id}/request-reupload")
async def request_sourcing_reupload(sr_id: str, request: Request,
                                    db: AsyncSession = Depends(get_db), current_user: User = Depends(spm_allowed)):
    """Send-to-Reupload from the Verify Sourcing modal — asks the uploader to
    re-submit documents. Does not change verified/status; the Sourcing
    Requests table's Action column is intentionally unaffected by this."""
    sr = (await db.execute(
        select(PartSourcingRequest).where(PartSourcingRequest.id == _as_uuid(sr_id))
    )).scalar_one_or_none()
    if not sr:
        return JSONResponse({"ok": False, "error": "Sourcing request not found"}, status_code=404)
    sr.reupload_requested = True
    sr.reupload_requested_at = app_now()
    sr.reupload_requested_by = current_user.username
    await audit(db, user=current_user, action="SOURCING_REUPLOAD_REQUESTED", table_name="part_sourcing_requests",
                record_id=str(sr.id), new_value={"requested_by": current_user.username}, request=request)
    await db.commit()
    return JSONResponse({"ok": True})
