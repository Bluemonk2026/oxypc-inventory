"""
Block Tags
==========
Hold specific tags off the sellable market for a pending deal or customer,
without actually selling them. A blocked tag stays visible on Ready to Sale
(stock levels still read correctly) but its Sell action is refused by
services/control_engine.validate_sale_allowed() until released.

One "New Block Tags" submission creates one BlockRecord (the shared header —
Block ID, Date, Container, Location, Block For, Customer) plus one
BlockRecordItem per tag selected. The "Tags Blocked" table lists one row per
still-blocked BlockRecordItem (so Edit/Release/Bulk Release can act on
individual tags within the same block), with the parent BlockRecord's shared
fields repeated on every sibling row. Releasing a tag cancels the hold and
removes its row from the table (it stays in the DB, status=released, for the
CSV export history — never hard-deleted).
"""
import io
import uuid as _uuid
from datetime import datetime, date as _date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_

from database import get_db
from templates_config import templates
from auth.dependencies import get_current_user, require_module_perm, verify_csrf
from models.user import User
from models.device import Device, DeviceStage
from models.location import UnitType, ZoneType, UNIT_TYPE_LABELS, ZONE_LABELS
from models.block_tags import BlockRecord, BlockRecordItem, BlockItemStatus, BLOCK_ITEM_STATUS_LABELS
from routers.inventory_location import _zone_dropdown_options

router = APIRouter(prefix="/block-tags", tags=["block-tags"], dependencies=[Depends(verify_csrf)])


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _next_block_id(db: AsyncSession, block_date: _date, container: UnitType) -> str:
    """<DDMMYYYY>-<CONTAINER>-<4-digit incremental>, e.g. 01102026-SHELF-0001.
    The incremental counter resets per (block_date, container) pair — each
    container type gets its own daily sequence rather than sharing one."""
    prefix = f"{block_date.strftime('%d%m%Y')}-{container.value.upper()}-"
    count = (await db.execute(
        select(func.count()).select_from(BlockRecord)
        .where(BlockRecord.block_date == block_date, BlockRecord.container == container)
    )).scalar() or 0
    return f"{prefix}{count + 1:04d}"


def _block_container_options():
    return [(u.value, UNIT_TYPE_LABELS.get(u, u.value)) for u in UnitType]


async def _block_for_options(db: AsyncSession):
    rows = (await db.execute(
        select(User.id, User.full_name, User.username).where(User.status == True)  # noqa: E712
        .order_by(User.full_name)
    )).all()
    return [{"id": str(r.id), "label": r.full_name or r.username} for r in rows]


async def _block_location_options(db: AsyncSession):
    zones = await _zone_dropdown_options(db)
    return [(z.value, ZONE_LABELS.get(z, z.value)) for z in zones]


def _block_filters(q, block_date, container, block_for, location_zone):
    w = []
    if q:
        like = f"%{q}%"
        w.append(or_(
            BlockRecord.block_id.ilike(like), BlockRecordItem.barcode.ilike(like),
            BlockRecordItem.lot_number.ilike(like), BlockRecord.customer_name.ilike(like),
        ))
    if block_date:
        try:
            w.append(BlockRecord.block_date == datetime.strptime(block_date.strip(), "%Y-%m-%d").date())
        except ValueError:
            pass
    if container:
        try:
            w.append(BlockRecord.container == UnitType(container))
        except ValueError:
            pass
    if block_for:
        w.append(BlockRecord.block_for_user_id == block_for)
    if location_zone:
        try:
            w.append(BlockRecord.location_zone == ZoneType(location_zone))
        except ValueError:
            pass
    return w


async def _release_items(db: AsyncSession, item_ids: list, current_user: User):
    """Shared by the single-row and bulk Release actions. Cancels the hold:
    flips Device.is_blocked back to False (tag is sellable again) and marks
    the item Released, which drops it out of the Tags Blocked table — see the
    BlockRecordItem.status == blocked filter in block_tags_data()/_ids below.
    Released rows are kept (not hard-deleted) for the CSV export history;
    re-releasing an already-released row is a no-op, not an error, so a bulk
    action over a mixed selection never fails partway through."""
    items = (await db.execute(
        select(BlockRecordItem).where(BlockRecordItem.id.in_(item_ids))
    )).scalars().all()
    if not items:
        return 0
    device_ids = [it.device_id for it in items if it.status == BlockItemStatus.blocked]
    for it in items:
        if it.status != BlockItemStatus.blocked:
            continue
        it.status = BlockItemStatus.released
        it.status_changed_by_user_id = current_user.id
        it.status_changed_at = datetime.utcnow()
    if device_ids:
        devices = (await db.execute(select(Device).where(Device.id.in_(device_ids)))).scalars().all()
        for d in devices:
            d.is_blocked = False
    await db.commit()
    return len(device_ids)


# ── Page ─────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def block_tags_home(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module_perm("block_tags")),
):
    return templates.TemplateResponse("block_tags/list.html", {
        "request": request,
        "current_user": current_user,
        "today": _date.today().isoformat(),
        "container_options": _block_container_options(),
        "block_for_options": await _block_for_options(db),
        "location_options": await _block_location_options(db),
    })


# ── Table data (DataTables server-side) ──────────────────────────────────────

@router.get("/data")
async def block_tags_data(
    request: Request,
    draw: int = Query(default=1), start: int = Query(default=0), length: int = Query(default=25),
    q: str = Query(default=""), block_date: str = Query(default=""), container: str = Query(default=""),
    block_for: str = Query(default=""), location_zone: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module_perm("block_tags")),
):
    from html import escape

    def esc(v):
        return escape(str(v)) if v is not None else ""

    # Released tags drop out of this table entirely (per product decision —
    # Release = cancel the hold and remove it from view); they're still kept
    # in the DB and still show up in the CSV exports for history.
    still_blocked = BlockRecordItem.status == BlockItemStatus.blocked
    base = (
        select(BlockRecordItem, BlockRecord)
        .join(BlockRecord, BlockRecordItem.block_record_id == BlockRecord.id)
        .where(still_blocked)
    )
    count_base = select(func.count()).select_from(BlockRecordItem).join(
        BlockRecord, BlockRecordItem.block_record_id == BlockRecord.id).where(still_blocked)

    filters = _block_filters(q, block_date, container, block_for, location_zone)
    total = (await db.execute(count_base)).scalar() or 0
    filtered = (await db.execute(count_base.where(*filters))).scalar() or 0

    rows = (await db.execute(
        base.where(*filters)
        .order_by(BlockRecord.created_at.desc(), BlockRecordItem.created_at.asc())
        .offset(max(0, start)).limit(min(max(1, length), 500))
    )).all()

    block_for_ids = {r.block_for_user_id for _, r in rows if r.block_for_user_id}
    user_map = {}
    if block_for_ids:
        users = (await db.execute(select(User).where(User.id.in_(block_for_ids)))).scalars().all()
        user_map = {u.id: (u.full_name or u.username) for u in users}

    data = []
    for item, rec in rows:
        actions = (
            f'<a href="#" class="btn btn-outline-secondary btn-sm py-0 px-1 block-edit-btn" data-id="{rec.id}" title="Edit"><i class="bi bi-pencil"></i></a>'
            f' <a href="#" class="btn btn-outline-primary btn-sm py-0 px-1 block-release-btn" data-id="{item.id}" title="Release"><i class="bi bi-unlock"></i></a>'
        )
        data.append([
            f'<input type="checkbox" class="row-check" value="{item.id}">',
            esc(rec.block_id),
            rec.block_date.isoformat() if rec.block_date else "",
            esc(UNIT_TYPE_LABELS.get(rec.container, rec.container)),
            esc(user_map.get(rec.block_for_user_id, "—")),
            esc(ZONE_LABELS.get(rec.location_zone, rec.location_zone) if rec.location_zone else "—"),
            esc(rec.customer_name or "—"),
            f'<a href="/devices/{esc(item.barcode)}" class="text-decoration-none"><code>{esc(item.barcode)}</code></a>',
            esc(item.lot_number or "—"),
            esc(item.model or "—"),
            esc(item.cpu or "—"),
            f"{item.ram_gb} GB" if item.ram_gb else "—",
            f"{item.storage_gb} GB" if item.storage_gb else "—",
            (f'<a href="#" class="btn btn-outline-secondary btn-sm py-0 px-1 block-barcode-btn" '
             f'data-id="{rec.id}" data-blockid="{esc(rec.block_id)}" title="Preview Barcode">'
             f'<i class="bi bi-upc-scan"></i> barcode</a>'),
            actions,
        ])

    return JSONResponse({"draw": draw, "recordsTotal": total, "recordsFiltered": filtered, "data": data})


@router.get("/ids")
async def block_tags_ids(
    q: str = Query(default=""), block_date: str = Query(default=""), container: str = Query(default=""),
    block_for: str = Query(default=""), location_zone: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module_perm("block_tags")),
):
    """Every (still-blocked) BlockRecordItem id matching the current filters,
    for Select All on the Tags Blocked table — same cross-page fix pattern as
    /sales/ids. Released items never appear in this table, so they're never
    selectable here either."""
    MAX_SELECT_ALL = 5000
    filters = _block_filters(q, block_date, container, block_for, location_zone)
    ids = (await db.execute(
        select(BlockRecordItem.id)
        .join(BlockRecord, BlockRecordItem.block_record_id == BlockRecord.id)
        .where(BlockRecordItem.status == BlockItemStatus.blocked, *filters)
        .order_by(BlockRecord.created_at.desc())
        .limit(MAX_SELECT_ALL)
    )).scalars().all()
    return JSONResponse({"ids": [str(i) for i in ids], "truncated": len(ids) == MAX_SELECT_ALL})


# ── New Block Tags modal: tag search + create ────────────────────────────────

@router.get("/search-tags")
async def search_tags(
    q: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module_perm("block_tags")),
):
    """Candidates for the New Block Tags modal's search+select box — Ready to
    Sale devices that are not already blocked."""
    if not q.strip():
        return JSONResponse({"data": []})
    like = f"%{q.strip()}%"
    rows = (await db.execute(
        select(Device).where(
            Device.current_stage == DeviceStage.ready_to_sale,
            Device.is_trashed == False,
            Device.is_blocked == False,
            or_(Device.barcode.ilike(like), Device.model.ilike(like), Device.brand.ilike(like)),
        ).limit(50)
    )).scalars().all()
    return JSONResponse({"data": [{
        "id": str(d.id), "barcode": d.barcode, "model": f"{d.brand or ''} {d.model or ''}".strip(),
        "lot_number": None,
    } for d in rows]})


@router.post("/create")
async def create_block(
    block_date: str = Form(...),
    container: str = Form(...),
    location_zone: str = Form(""),
    block_for_user_id: str = Form(""),
    customer_name: str = Form(""),
    device_ids: str = Form(...),  # comma-separated Device UUIDs
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module_perm("block_tags", "add")),
):
    ids = [i.strip() for i in device_ids.split(",") if i.strip()]
    if not ids:
        return JSONResponse({"ok": False, "error": "Select at least one tag."})
    try:
        b_date = datetime.strptime(block_date.strip(), "%Y-%m-%d").date()
        container_val = UnitType(container)
    except ValueError:
        return JSONResponse({"ok": False, "error": "Invalid date or container."})

    devices = (await db.execute(select(Device).where(Device.id.in_(ids)))).scalars().all()
    already_blocked = [d.barcode for d in devices if d.is_blocked]
    if already_blocked:
        return JSONResponse({"ok": False, "error": f"Already blocked: {', '.join(already_blocked)}"})
    if len(devices) != len(ids):
        return JSONResponse({"ok": False, "error": "One or more tags could not be found."})

    zone_val = None
    if location_zone.strip():
        try:
            zone_val = ZoneType(location_zone.strip())
        except ValueError:
            pass

    record = BlockRecord(
        block_id=await _next_block_id(db, b_date, container_val),
        block_date=b_date,
        container=container_val,
        location_zone=zone_val,
        block_for_user_id=block_for_user_id.strip() or None,
        customer_name=customer_name.strip() or None,
        created_by_user_id=current_user.id,
    )
    db.add(record)
    await db.flush()

    block_for_id = block_for_user_id.strip() or None
    for d in devices:
        db.add(BlockRecordItem(
            block_record_id=record.id, device_id=d.id,
            barcode=d.barcode, lot_number=d.sub_lot_number or None, model=f"{d.brand or ''} {d.model or ''}".strip(),
            cpu=d.cpu, ram_gb=d.ram_gb, storage_gb=d.storage_gb,
        ))
        d.is_blocked = True
        # Ready to Sale's Assigned column reads Device.assigned_to_user_id —
        # Block Tags sets it to the Block For user so that column shows who
        # the tag is held for, with the Open/Blocked badge driven separately
        # by is_blocked above.
        if block_for_id:
            d.assigned_to_user_id = block_for_id

    await db.commit()
    return JSONResponse({"ok": True, "block_id": record.block_id, "count": len(devices)})


@router.get("/{record_id}")
async def get_block(record_id: str, db: AsyncSession = Depends(get_db),
                     current_user: User = Depends(require_module_perm("block_tags"))):
    """Current values for the Edit Block modal — without this, the modal
    would open blank and silently overwrite Container/Location/etc. with
    whatever the form's own defaults happen to be the moment you hit Save
    without touching every field."""
    record = (await db.execute(select(BlockRecord).where(BlockRecord.id == record_id))).scalar_one_or_none()
    if not record:
        return JSONResponse({"ok": False, "error": "Block record not found."}, status_code=404)
    return JSONResponse({"ok": True, "record": {
        "block_date": record.block_date.isoformat() if record.block_date else "",
        "container": record.container.value if record.container else "",
        "location_zone": record.location_zone.value if record.location_zone else "",
        "block_for_user_id": str(record.block_for_user_id) if record.block_for_user_id else "",
        "customer_name": record.customer_name or "",
    }})


@router.post("/{record_id}/edit")
async def edit_block(
    record_id: str,
    block_date: str = Form(...),
    container: str = Form(...),
    location_zone: str = Form(""),
    block_for_user_id: str = Form(""),
    customer_name: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module_perm("block_tags", "edit")),
):
    record = (await db.execute(select(BlockRecord).where(BlockRecord.id == record_id))).scalar_one_or_none()
    if not record:
        return JSONResponse({"ok": False, "error": "Block record not found."})
    try:
        record.block_date = datetime.strptime(block_date.strip(), "%Y-%m-%d").date()
        record.container = UnitType(container)
    except ValueError:
        return JSONResponse({"ok": False, "error": "Invalid date or container."})
    record.location_zone = ZoneType(location_zone.strip()) if location_zone.strip() else None
    block_for_id = block_for_user_id.strip() or None
    record.block_for_user_id = block_for_id
    record.customer_name = customer_name.strip() or None

    if block_for_id:
        items = (await db.execute(
            select(BlockRecordItem).where(BlockRecordItem.block_record_id == record.id)
        )).scalars().all()
        device_ids = [it.device_id for it in items]
        if device_ids:
            devices = (await db.execute(select(Device).where(Device.id.in_(device_ids)))).scalars().all()
            for d in devices:
                d.assigned_to_user_id = block_for_id

    await db.commit()
    return JSONResponse({"ok": True})


# ── Release (cancel the hold) ────────────────────────────────────────────────

@router.post("/{item_id}/release")
async def release_item(item_id: str, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(require_module_perm("block_tags", "edit"))):
    await _release_items(db, [item_id], current_user)
    return JSONResponse({"ok": True})


@router.post("/bulk-release")
async def bulk_release(item_ids: str = Form(...), db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(require_module_perm("block_tags", "edit"))):
    ids = [i.strip() for i in item_ids.split(",") if i.strip()]
    n = await _release_items(db, ids, current_user)
    return JSONResponse({"ok": True, "count": n})


# ── Barcode label (2x4" Code128 of the Block ID) ─────────────────────────────

@router.get("/{record_id}/barcode")
async def download_barcode(record_id: str, inline: bool = Query(default=False),
                            db: AsyncSession = Depends(get_db),
                            current_user: User = Depends(require_module_perm("block_tags"))):
    """Same PDF either way — inline=1 (used by the preview modal's <iframe>)
    asks the browser to render it in place instead of triggering a save
    dialog; the Download button in that modal links here without the param
    for the normal forced-download behaviour."""
    from utils.block_barcode import render_block_id_barcode_pdf

    record = (await db.execute(select(BlockRecord).where(BlockRecord.id == record_id))).scalar_one_or_none()
    if not record:
        return JSONResponse({"ok": False, "error": "Block record not found."}, status_code=404)
    pdf_bytes = render_block_id_barcode_pdf(record.block_id)
    disposition = "inline" if inline else "attachment"
    return StreamingResponse(
        io.BytesIO(pdf_bytes), media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="block_{record.block_id}.pdf"'},
    )


# ── Exports ────────────────────────────────────────────────────────────────

def _export_header():
    return ["Block ID", "Block Date", "Container", "Block For", "Location", "Customer Name",
            "Tag Number", "Lot Number", "Model", "CPU", "RAM (GB)", "Storage (GB)", "Status"]


def _export_row(item: BlockRecordItem, rec: BlockRecord, user_map: dict):
    return [
        rec.block_id, rec.block_date.isoformat() if rec.block_date else "",
        UNIT_TYPE_LABELS.get(rec.container, rec.container),
        user_map.get(rec.block_for_user_id, ""),
        ZONE_LABELS.get(rec.location_zone, rec.location_zone) if rec.location_zone else "",
        rec.customer_name or "",
        item.barcode, item.lot_number or "", item.model or "", item.cpu or "",
        item.ram_gb or "", item.storage_gb or "", BLOCK_ITEM_STATUS_LABELS.get(item.status, item.status),
    ]


@router.get("/export/all")
async def export_all(db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(require_module_perm("block_tags"))):
    import csv
    rows = (await db.execute(
        select(BlockRecordItem, BlockRecord).join(BlockRecord, BlockRecordItem.block_record_id == BlockRecord.id)
        .order_by(BlockRecord.created_at.desc())
    )).all()
    user_ids = {r.block_for_user_id for _, r in rows if r.block_for_user_id}
    user_map = {}
    if user_ids:
        users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        user_map = {u.id: (u.full_name or u.username) for u in users}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(_export_header())
    for item, rec in rows:
        writer.writerow(_export_row(item, rec, user_map))
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=block_tags_all.csv"},
    )


@router.post("/export/selected")
async def export_selected(item_ids: str = Form(""), db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(require_module_perm("block_tags"))):
    import csv
    ids = [i.strip() for i in item_ids.split(",") if i.strip()]
    if not ids:
        return JSONResponse({"ok": False, "error": "No rows selected."})
    rows = (await db.execute(
        select(BlockRecordItem, BlockRecord).join(BlockRecord, BlockRecordItem.block_record_id == BlockRecord.id)
        .where(BlockRecordItem.id.in_(ids)).order_by(BlockRecord.created_at.desc())
    )).all()
    user_ids = {r.block_for_user_id for _, r in rows if r.block_for_user_id}
    user_map = {}
    if user_ids:
        users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        user_map = {u.id: (u.full_name or u.username) for u in users}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(_export_header())
    for item, rec in rows:
        writer.writerow(_export_row(item, rec, user_map))
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=block_tags_selected.csv"},
    )
