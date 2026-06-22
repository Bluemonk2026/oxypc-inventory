"""
QC Router — Component scoring + grade assignment + fail counter + audit
"""
from __future__ import annotations
from templates_config import templates
from datetime import datetime
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from models.location import DeviceLocationLog, StorageLocation

from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement
from models.lot import Lot
from models.qc import QCCheck
from auth.dependencies import get_current_user, require_roles, verify_csrf, require_module_perm
from services.control_engine import validate_transition, get_allowed_next_stages, assert_device_in_stage
from services.audit_engine import audit

router = APIRouter(prefix="/qc", tags=["qc"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.qc_inspector)

QC_FAIL_SCRAP_THRESHOLD = 3   # 3rd consecutive fail → recommend scrap


def compute_grade(total_score: int) -> str:
    if total_score >= 85: return "A"
    if total_score >= 70: return "B"
    if total_score >= 50: return "C"
    if total_score > 0:   return "D"
    return "S"


@router.get("", response_class=HTMLResponse)
async def qc_list(request: Request, db: AsyncSession = Depends(get_db),
                  current_user: User = Depends(allowed),
                  page: int = Query(default=1, ge=1),
                  page_size: int = Query(default=50, ge=1, le=200)):
    total_result = await db.execute(select(func.count()).select_from(
        select(Device.id)
        .where(Device.current_stage == DeviceStage.qc_check, Device.is_active == True)
        .subquery()
    ))
    total = total_result.scalar() or 0
    total_pages = max(1, (total + page_size - 1) // page_size)

    result = await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == DeviceStage.qc_check, Device.is_active == True)
        .order_by(Device.updated_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    devices = result.all()

    uuid_ids = [d.id for d, _ in devices]  # UUID objects from SQLAlchemy
    location_map = {}
    if uuid_ids:
        sub = (
            select(DeviceLocationLog.device_id, func.max(DeviceLocationLog.logged_at).label("latest"))
            .group_by(DeviceLocationLog.device_id).subquery()
        )
        loc_rows = await db.execute(
            select(DeviceLocationLog.device_id, StorageLocation.unit_id, DeviceLocationLog.action)
            .join(sub, and_(DeviceLocationLog.device_id == sub.c.device_id,
                            DeviceLocationLog.logged_at == sub.c.latest))
            .outerjoin(StorageLocation, DeviceLocationLog.location_id == StorageLocation.id)
            .where(DeviceLocationLog.device_id.in_(uuid_ids))
        )
        for did, unit_id, action in loc_rows.all():
            location_map[str(did)] = {"unit_id": unit_id, "action": action.value if action else None}

    return templates.TemplateResponse("qc/list.html", {
        "request": request, "devices": devices, "current_user": current_user,
        "location_map": location_map,
        "page": page, "page_size": page_size,
        "total": total, "total_pages": total_pages,
    })


@router.get("/new", response_class=HTMLResponse)
async def qc_new_form(request: Request, barcode: str = None,
                      db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(allowed)):
    device = None
    qc_history = []
    fail_count = 0
    if barcode:
        result = await db.execute(select(Device).where(Device.barcode == barcode))
        device = result.scalar_one_or_none()
        if device:
            hist = await db.execute(
                select(QCCheck).where(QCCheck.device_id == device.id)
                .order_by(QCCheck.checked_at.desc())
            )
            qc_history = hist.scalars().all()
            fail_count = sum(1 for q in qc_history if q.result == "fail")
    return templates.TemplateResponse("qc/form.html", {
        "request": request, "device": device, "current_user": current_user,
        "qc_history": qc_history, "fail_count": fail_count, "error": None,
    })


@router.post("/new")
async def qc_submit(
    request: Request,
    barcode: str = Form(...),
    # Explicit pass/fail from radio — authoritative; scores are for grading only
    result: str = Form(""),
    # Component scores (0-10 each)
    battery_score: str = Form(""),
    screen_score:  str = Form(""),
    keyboard_score:str = Form(""),
    body_score:    str = Form(""),
    # Legacy / extra fields
    issues_found: str = Form(""),
    notes: str = Form(""),
    send_to_stage: str = Form("l1"),
    failure_reason: str = Form(""),
    updated_make: str = Form(""),
    updated_model: str = Form(""),
    updated_cpu: str = Form(""),
    updated_generation: str = Form(""),
    updated_ram: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    _perm: User = Depends(require_module_perm("qc_check", "add")),
):
    dev_result = await db.execute(select(Device).where(Device.barcode == barcode))
    device = dev_result.scalar_one_or_none()
    if not device:
        return templates.TemplateResponse("qc/form.html", {
            "request": request, "device": None, "current_user": current_user,
            "qc_history": [], "fail_count": 0,
            "error": f"Device {barcode} not found",
        })

    assert_device_in_stage(device, DeviceStage.qc_check)

    # Apply spec corrections
    if updated_make:       device.brand      = updated_make
    if updated_model:      device.model      = updated_model
    if updated_cpu:        device.cpu        = updated_cpu
    if updated_generation: device.generation = updated_generation
    if updated_ram:
        try:
            device.ram_gb = int(updated_ram.replace("GB", "").strip())
        except (ValueError, AttributeError):
            pass

    # Parse component scores
    def parse_score(s: str) -> int | None:
        try: return max(0, min(10, int(s.strip())))
        except: return None

    bat  = parse_score(battery_score)
    scr  = parse_score(screen_score)
    kbd  = parse_score(keyboard_score)
    bod  = parse_score(body_score)

    # Total score: sum of 4 components * 2.5 → 0-100
    scores = [s for s in [bat, scr, kbd, bod] if s is not None]
    if scores:
        raw_sum    = sum(scores)
        # Normalise: max is 40 (4 * 10), scale to 100
        total_score = int(raw_sum * 2.5)
    else:
        total_score = None

    # Determine pass/fail: explicit radio button overrides score-based auto-detection.
    # Score still drives the grade; the radio lets an inspector override a borderline result.
    if result in ("pass", "fail"):
        result_ = result
    elif total_score is not None:
        result_ = "pass" if total_score >= 70 else "fail"
    else:
        result_ = "fail"

    if total_score is not None:
        grade = compute_grade(total_score)
    else:
        grade = "D"

    # Count previous fails for this device
    fail_result = await db.execute(
        select(func.count(QCCheck.id))
        .where(QCCheck.device_id == device.id, QCCheck.result == "fail")
    )
    prev_fails  = fail_result.scalar() or 0
    attempt_no  = prev_fails + 1 if result_ == "fail" else prev_fails

    combined_notes = notes or ""
    if failure_reason:
        combined_notes = f"Failure: {failure_reason}. {combined_notes}".strip()

    qc = QCCheck(
        device_id=device.id, inspector_id=current_user.id,
        inspector_name=current_user.full_name,
        battery_score=bat, screen_score=scr, keyboard_score=kbd, body_score=bod,
        total_score=total_score,
        result=result_, grade=grade,
        attempt_number=attempt_no,
        issues_found=issues_found or None,
        notes=combined_notes or None,
        send_to_stage=send_to_stage if result_ == "fail" else None,
    )
    db.add(qc)

    prev = device.current_stage
    is_admin = current_user.role.value == "admin"

    if result_ == "pass":
        device.grade        = grade
        device.updated_at   = app_now()
        to_stage = DeviceStage.cleaning
        # Skip cosmetic for A grade already clean? Admin can always override via move
        await validate_transition(device, to_stage, db, override_admin=is_admin)
        notes_text = f"QC Passed — Score {total_score}/100 Grade {grade}"
        device.current_stage = to_stage

    else:
        # Check for 3rd consecutive fail → recommend scrap
        if attempt_no >= QC_FAIL_SCRAP_THRESHOLD:
            combined_notes = f"[3rd QC FAIL — recommend scrap] {combined_notes}"
            qc.notes = combined_notes

        to_stage_str = send_to_stage if send_to_stage else "l1"
        to_stage     = DeviceStage(to_stage_str)
        await validate_transition(device, to_stage, db, override_admin=is_admin)
        device.current_stage = to_stage
        device.updated_at    = app_now()
        notes_text = f"QC Failed (score {total_score}/100) — Sent to {to_stage_str}"

    # Close previous open StageMovement
    prev_mv = (await db.execute(
        select(StageMovement)
        .where(StageMovement.device_id == device.id,
               StageMovement.to_stage  == prev,
               StageMovement.exited_at == None)
        .order_by(StageMovement.moved_at.desc())
    )).scalars().first()
    if prev_mv:
        prev_mv.exited_at = app_now()

    db.add(StageMovement(device_id=device.id, from_stage=prev, to_stage=device.current_stage,
                         moved_by=current_user.username, notes=notes_text))

    await audit(db, user=current_user,
                action="QC_PASS" if result_ == "pass" else "QC_FAIL",
                table_name="qc_checks", record_id=str(device.id),
                new_value={"score": total_score, "grade": grade, "result": result_},
                request=request)

    await db.commit()
    return RedirectResponse(url="/qc?success=QC+submitted", status_code=302)
