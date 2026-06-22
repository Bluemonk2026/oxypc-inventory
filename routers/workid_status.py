"""
WorkID Status — consolidated view of every WorkID (WorkOrder) with the device's
current status, parts required / requested counts, an IQC→Final-QC timeline, and
filters (workid, tag number, engineer, date range).
"""
from datetime import datetime
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from templates_config import templates
from database import get_db
from utils.timezone import app_now
from models.user import User
from models.device import Device, DeviceStage, StageMovement, STAGE_LABELS
from models.work_order import WorkOrder
from models.part_request import PartRequest
from models.iqc_inspection import IQCInspection
from services.parts_required import compute_required
from auth.dependencies import get_current_user

router = APIRouter(tags=["workid_status"])


def _parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except (ValueError, AttributeError):
            pass
    return None


@router.get("/workid-status", response_class=HTMLResponse)
async def workid_status(request: Request, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(get_current_user),
                        workid: str = Query(default=""),
                        tag: str = Query(default=""),
                        engineer: str = Query(default=""),
                        date_from: str = Query(default=""),
                        date_to: str = Query(default=""),
                        highlight: str = Query(default="")):
    # ── Base query: WorkOrders joined to their Device ──────────────────────────
    stmt = (select(WorkOrder, Device)
            .join(Device, WorkOrder.device_id == Device.id, isouter=True)
            .order_by(WorkOrder.assigned_at.desc()))
    if workid:
        stmt = stmt.where(WorkOrder.work_id.ilike(f"%{workid.strip()}%"))
    if tag:
        stmt = stmt.where(WorkOrder.barcode.ilike(f"%{tag.strip()}%"))
    if engineer:
        stmt = stmt.where(WorkOrder.assigned_username == engineer)
    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    if df:
        stmt = stmt.where(WorkOrder.assigned_at >= df)
    if dt:
        # include the whole end day
        dt_end = dt.replace(hour=23, minute=59, second=59)
        stmt = stmt.where(WorkOrder.assigned_at <= dt_end)

    rows = (await db.execute(stmt)).all()
    device_ids = [d.id for _, d in rows if d is not None]

    # ── Parts Required (IQC-driven) + Parts Requested (requested + handed over) ─
    parts_required_map, parts_requested_map = {}, {}
    finalqc_date_map = {}
    if device_ids:
        iqc_rows = (await db.execute(
            select(IQCInspection).where(IQCInspection.device_id.in_(device_ids))
        )).scalars().all()
        iqc_by_dev = {}
        for iqc in iqc_rows:
            iqc_by_dev.setdefault(str(iqc.device_id), iqc)
        dev_by_id = {str(d.id): d for _, d in rows if d is not None}
        for did, dev in dev_by_id.items():
            parts_required_map[did] = sum(
                1 for r in compute_required(iqc_by_dev.get(did), dev) if r["required"]
            )
        pr_rows = (await db.execute(
            select(PartRequest.device_id, func.count(PartRequest.id))
            .where(PartRequest.device_id.in_(device_ids),
                   PartRequest.status.in_(["requested", "handed_over"]))
            .group_by(PartRequest.device_id)
        )).all()
        for did, cnt in pr_rows:
            parts_requested_map[str(did)] = cnt

        # Date each device was sent to Final QC (latest movement to final_qc)
        fq_rows = (await db.execute(
            select(StageMovement.device_id, func.max(StageMovement.moved_at))
            .where(StageMovement.device_id.in_(device_ids),
                   StageMovement.to_stage == DeviceStage.final_qc)
            .group_by(StageMovement.device_id)
        )).all()
        for did, moved in fq_rows:
            finalqc_date_map[str(did)] = moved

    today = app_now()
    items = []
    for wo, dev in rows:
        did = str(wo.device_id)
        start = wo.assigned_at or wo.created_at
        finalqc_dt = finalqc_date_map.get(did)
        end = finalqc_dt or today
        days = max(0, (end.date() - start.date()).days) if start else 0
        cur_stage = dev.current_stage if dev else None
        items.append({
            "work_id": wo.work_id,
            "barcode": wo.barcode or (dev.barcode if dev else "—"),
            "model": (dev.model or dev.brand) if dev else "—",
            "stage_label": STAGE_LABELS.get(cur_stage, cur_stage.value if cur_stage else "—"),
            "stage_value": cur_stage.value if cur_stage else "",
            "wo_status": wo.status,
            "parts_required": parts_required_map.get(did, 0),
            "parts_requested": parts_requested_map.get(did, 0),
            "start": start,
            "finalqc": finalqc_dt,
            "days": days,
            "ongoing": finalqc_dt is None,
            "notes": (dev.notes if dev else None),
            "engineer": wo.assigned_name or wo.assigned_username or "—",
        })

    # Distinct engineers for the filter dropdown
    eng_rows = (await db.execute(
        select(WorkOrder.assigned_username, WorkOrder.assigned_name)
        .where(WorkOrder.assigned_username.isnot(None))
        .distinct()
    )).all()
    seen, engineers = set(), []
    for uname, name in eng_rows:
        if uname and uname not in seen:
            seen.add(uname)
            engineers.append((uname, name or uname))
    engineers.sort(key=lambda kv: kv[1].lower())

    return templates.TemplateResponse("workid_status/list.html", {
        "request": request, "current_user": current_user,
        "items": items, "engineers": engineers,
        "f_workid": workid, "f_tag": tag, "f_engineer": engineer,
        "f_date_from": date_from, "f_date_to": date_to,
        "highlight": highlight,
    })
