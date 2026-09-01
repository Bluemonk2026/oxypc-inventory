"""
WorkID Status — consolidated view of every WorkID (WorkOrder) with the tag's
Asset History (Stage/Completed Date/Assigned Engineer sourced from the
device's most recent StageMovement — From/When/By respectively), an
IQC→Final-QC timeline, and filters (workid, tag number, engineer, date range).
"""
from datetime import datetime
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from templates_config import templates
from database import get_db
from utils.timezone import app_now
from models.user import User
from models.device import Device, DeviceStage, StageMovement, STAGE_LABELS
from models.work_order import WorkOrder
from utils.attendance_groups import managed_usernames
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
                        completed_from: str = Query(default=""),
                        completed_to: str = Query(default=""),
                        cosmetic_stage: str = Query(default=""),
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
    # Completed Date and Stage are both applied AFTER items are built below,
    # not here — the displayed Completed Date column and Stage column are
    # sourced from Asset History (the device's latest StageMovement), not
    # from WorkOrder.completed_at / Device.current_stage, so filtering
    # against those columns here filtered against a value the page no longer
    # showed (the reported "Completed Date filter not applying" bug).
    cf = _parse_date(completed_from)
    ct = _parse_date(completed_to)

    is_admin = current_user.role.value == "admin"

    # ── Row visibility (item 33): admin sees everyone; a Group Config manager
    # sees every team member's WorkID records — transitively, so a manager of
    # managers sees every level down the chain (utils/attendance_groups.
    # managed_usernames), across every group they manage, not just one;
    # anyone else sees only their own. ───────────────────────────────────────
    if not is_admin:
        team = await managed_usernames(db, current_user.username)
        visible_usernames = set(team) | {current_user.username}
        stmt = stmt.where(WorkOrder.assigned_username.in_(visible_usernames))

    rows = (await db.execute(stmt)).all()
    device_ids = [d.id for _, d in rows if d is not None]

    finalqc_date_map = {}
    # ── Asset History (Device Detail's "From"/"To"/"By"/"When" table) — Stage,
    # Completed Date and Assigned Engineer below now read the device's most
    # recent StageMovement rather than the device's live current_stage /
    # WorkOrder.completed_at / WorkOrder.assigned_name, so this page always
    # matches whatever Asset History shows for that tag. ────────────────────
    latest_movement_by_device = {}
    display_name_by_username = {}
    if device_ids:
        # Date each device was sent to Final QC (latest movement to final_qc)
        fq_rows = (await db.execute(
            select(StageMovement.device_id, func.max(StageMovement.moved_at))
            .where(StageMovement.device_id.in_(device_ids),
                   StageMovement.to_stage == DeviceStage.final_qc)
            .group_by(StageMovement.device_id)
        )).all()
        for did, moved in fq_rows:
            finalqc_date_map[str(did)] = moved

        move_rows = (await db.execute(
            select(StageMovement)
            .where(StageMovement.device_id.in_(device_ids))
            .order_by(StageMovement.moved_at.desc())
        )).scalars().all()
        for mv in move_rows:
            latest_movement_by_device.setdefault(str(mv.device_id), mv)

        usernames = {mv.moved_by for mv in latest_movement_by_device.values() if mv.moved_by}
        if usernames:
            u_rows = (await db.execute(
                select(User.username, User.full_name).where(User.username.in_(usernames))
            )).all()
            display_name_by_username = {uname: full for uname, full in u_rows}

    today = app_now()
    items = []
    for wo, dev in rows:
        did = str(wo.device_id)
        start = wo.assigned_at or wo.created_at
        finalqc_dt = finalqc_date_map.get(did)
        end = finalqc_dt or today
        days = max(0, (end.date() - start.date()).days) if start else 0
        mv = latest_movement_by_device.get(did)
        if mv:
            stage_value = mv.from_stage.value if mv.from_stage else ""
            stage_label = STAGE_LABELS.get(mv.from_stage, mv.from_stage.value if mv.from_stage else "—")
            movement_completed_at = mv.moved_at
            movement_engineer = (display_name_by_username.get(mv.moved_by) or mv.moved_by) if mv.moved_by else "—"
        else:
            stage_value, stage_label, movement_completed_at, movement_engineer = "", "—", None, "—"
        items.append({
            "work_id": wo.work_id,
            "barcode": wo.barcode or (dev.barcode if dev else "—"),
            "model": (dev.model or dev.brand) if dev else "—",
            "brand": (dev.brand if dev else None),
            "stage_label": stage_label,
            "stage_value": stage_value,
            "wo_status": wo.status,
            "start": start,
            "finalqc": finalqc_dt,
            "completed_at": movement_completed_at,
            "days": days,
            "ongoing": finalqc_dt is None,
            "notes": (dev.notes if dev else None),
            "engineer": movement_engineer,
        })

    # ── Completed Date / Stage filters — applied here (not in the SQL stmt
    # above) so they narrow the SAME values the Completed Date and Stage
    # columns display (Asset History's When/From), not the WorkOrder/Device
    # columns those columns no longer read from. ─────────────────────────
    if cosmetic_stage:
        items = [it for it in items if it["stage_value"] == cosmetic_stage]
    if cf:
        items = [it for it in items if it["completed_at"] and it["completed_at"] >= cf]
    if ct:
        ct_end = ct.replace(hour=23, minute=59, second=59)
        items = [it for it in items if it["completed_at"] and it["completed_at"] <= ct_end]

    # ── Card Count tiles — computed from the SAME filtered `items` list, so
    # every filter above (including Completed From/To and Stage) narrows the
    # tiles exactly as it narrows the table. "Assigned" and "Completed" read
    # WorkOrder.status directly (its own pending/in_progress/completed
    # values) rather than the page's separate Final-QC-movement-based
    # "ongoing" concept or completed_at, since those are three genuinely
    # different signals on this page. ──────────────────────────────────────
    tag_count = len({it["barcode"] for it in items if it.get("barcode") and it["barcode"] != "—"})
    tile_counts = {
        "total_workids": len(items),
        "total_tags": tag_count,
        "total_ongoing": sum(1 for it in items if it["ongoing"]),
        "total_assigned": sum(1 for it in items if it["wo_status"] == "pending"),
        "total_completed": sum(1 for it in items if it["wo_status"] == "completed"),
    }

    # Distinct engineers for the filter dropdown.
    #
    # Previously admin-only, which left an attendance-group manager — who can
    # see every member's rows — with no way to narrow to one of them. Admin
    # still draws from every work order; everyone else draws from the rows they
    # are allowed to see, so the dropdown can never widen someone's visibility
    # beyond what the row filter above already permits.
    engineers = []
    if is_admin:
        eng_rows = (await db.execute(
            select(WorkOrder.assigned_username, WorkOrder.assigned_name)
            .where(WorkOrder.assigned_username.isnot(None))
            .distinct()
        )).all()
    else:
        eng_rows = [(wo.assigned_username, wo.assigned_name)
                    for wo, _dev in rows if wo.assigned_username]
    seen = set()
    for uname, name in eng_rows:
        if uname and uname not in seen:
            seen.add(uname)
            engineers.append((uname, name or uname))
    engineers.sort(key=lambda kv: kv[1].lower())

    # "Stage" filter (renamed from "Cosmetic Stage") now offers every
    # DeviceStage, not just the cosmetic-line subset — it filters against
    # Asset History's From value (stage_value above), which can be any stage
    # a tag has ever moved off of, not only a cosmetic one.
    cosmetic_stage_choices = [(s.value, STAGE_LABELS.get(s, s.value)) for s in DeviceStage]

    return templates.TemplateResponse("workid_status/list.html", {
        "request": request, "current_user": current_user,
        "items": items, "engineers": engineers, "is_admin": is_admin,
        "tile_counts": tile_counts, "cosmetic_stage_choices": cosmetic_stage_choices,
        "f_workid": workid, "f_tag": tag, "f_engineer": engineer,
        "f_completed_from": completed_from, "f_completed_to": completed_to,
        "f_cosmetic_stage": cosmetic_stage,
        "highlight": highlight,
    })


@router.get("/workid-status/export")
async def workid_status_export(request: Request, db: AsyncSession = Depends(get_db),
                               current_user: User = Depends(get_current_user),
                               workid: str = Query(default=""),
                               tag: str = Query(default=""),
                               engineer: str = Query(default=""),
                               completed_from: str = Query(default=""),
                               completed_to: str = Query(default=""),
                               cosmetic_stage: str = Query(default="")):
    """CSV of exactly the rows the page is showing.

    Delegates to the page handler rather than repeating its query, so the
    export cannot drift from the table — including the row-visibility rules,
    which are the part that would be damaging to get wrong: a non-admin must
    not be able to export rows the page would not show them.
    """
    import csv as _csv
    import io as _io
    from datetime import date as _date

    page = await workid_status(request=request, db=db, current_user=current_user,
                               workid=workid, tag=tag, engineer=engineer,
                               completed_from=completed_from, completed_to=completed_to,
                               cosmetic_stage=cosmetic_stage, highlight="")
    items = page.context["items"]

    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["WorkID", "Tag Number", "Tag Number Make", "Model", "Stage",
                "Assigned Engineer", "Start", "Final QC", "Completed Date",
                "Aging (days)", "Notes"])
    for it in items:
        w.writerow([
            it.get("work_id") or "",
            it.get("barcode") or "",
            it.get("brand") or "",
            it.get("model") or "",
            it.get("stage_label") or "",
            it.get("engineer") or "",
            it["start"].strftime("%d-%m-%Y %H:%M") if it.get("start") else "",
            it["finalqc"].strftime("%d-%m-%Y %H:%M") if it.get("finalqc") else "",
            it["completed_at"].strftime("%d-%m-%Y %H:%M") if it.get("completed_at") else "",
            it.get("days", ""),
            (it.get("notes") or "").replace("\n", " "),
        ])
    # utf-8-sig so Excel opens it without mangling non-ASCII names.
    data = buf.getvalue().encode("utf-8-sig")
    fname = f"workid_status_{_date.today().isoformat()}.csv"
    return StreamingResponse(
        _io.BytesIO(data), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})
