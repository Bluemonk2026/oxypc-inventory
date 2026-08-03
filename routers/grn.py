"""
GRN Router — Goods Receipt Note
Records expected vs received quantity per lot and raises mismatch flags.
"""
import os
import hashlib
from decimal import Decimal
from templates_config import templates
from datetime import datetime
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, update

from database import get_db
from models.user import User, UserRole
from models.lot import Lot
from models.device import Device, DeviceStage, StageMovement
from models.engines import AuditLog
from models.grn_import import GRNImport
from services.invoice_parser import extract_invoice_fields
from services.audit_engine import audit
from config import UPLOADS_DIR
from auth.dependencies import get_current_user, require_roles, verify_csrf

router = APIRouter(prefix="/grn", tags=["grn"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager)

GRN_UPLOAD_DIR = os.path.join(UPLOADS_DIR, "grn")


async def _next_grn_number(db: AsyncSession) -> str:
    """Auto-generate next GRN number in format GRN-YYYYMMDD-NNNN (legacy per-lot)."""
    today = app_now().strftime("%Y%m%d")
    result = await db.execute(
        select(func.count(Lot.id)).where(
            Lot.grn_system_number.like(f"GRN-{today}-%")
        )
    )
    n = (result.scalar() or 0) + 1
    return f"GRN-{today}-{n:04d}"


async def _next_grn_12(db: AsyncSession) -> str:
    """Unique 12-digit GRN number for an invoice import."""
    base = (await db.execute(select(func.count(GRNImport.id)))).scalar() or 0
    n = base + 1
    for _ in range(10000):
        g = str(n).zfill(12)
        taken = (await db.execute(select(GRNImport.id).where(GRNImport.grn_number == g))).scalar_one_or_none()
        if not taken:
            return g
        n += 1
    return str(n).zfill(12)


async def _stocked_map(db: AsyncSession, grns) -> dict:
    """{grn_number: number of tag numbers wired to it}.

    Counted from Device.grn_number rather than stored on GRNImport so the figure
    can never drift out of step with the tags that were actually mapped.
    Trashed / deactivated tags are excluded — they are no longer stock.
    """
    numbers = [g.grn_number for g in grns if g.grn_number]
    if not numbers:
        return {}
    rows = (await db.execute(
        select(Device.grn_number, func.count(Device.id))
        .where(Device.grn_number.in_(numbers),
               Device.is_active == True, Device.is_trashed == False)
        .group_by(Device.grn_number)
    )).all()
    return {n: c for n, c in rows}


# ── GRN invoice import (the GRN nav page) ──────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def grn_import_list(request: Request, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(allowed),
                          error: str = "", success: str = ""):
    # GRN with Invoice page → invoice-source GRNs only (legacy NULL treated as invoice)
    rows = (await db.execute(
        select(GRNImport)
        .where(or_(GRNImport.source != "post_iqc", GRNImport.source.is_(None)),
               GRNImport.is_deleted == False)
        .order_by(GRNImport.created_at.desc())
    )).scalars().all()
    return templates.TemplateResponse("grn/import.html", {
        "request": request, "grns": rows, "current_user": current_user,
        "stocked": await _stocked_map(db, rows),
        "error": error, "success": success,
    })


# ── GRN post IQC (item 14): same import/validate/edit, plus Map-to-Tag ─────────

@router.get("/post-iqc/data")
async def grn_post_iqc_data(
    request: Request,
    draw: int = 1, start: int = 0, length: int = 25,
    device_type: str = "", pend_invoice: str = "", pend_po: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """DataTables server-side feed for the GRN in TRC pending-devices table.

    'pending' is every IQC-stage device with no GRN number yet — effectively
    the whole IQC backlog (~3,900 devices with no filter). Rendering all of
    them into the HTML on every load froze the page; rows now come a page at
    a time. Invoice/PO are still hidden via DataTables' own columnDefs
    (visible:false), not a d-none class, so header and cell hide together.
    """
    from sqlalchemy import desc as _desc, asc as _asc
    from html import escape

    base_filters = [Device.current_stage == DeviceStage.iqc,
                    or_(Device.grn_number.is_(None), Device.grn_number == ""),
                    Device.is_active == True, Device.is_trashed == False]
    if device_type:
        base_filters.append(Device.device_type == device_type)
    # Matches the old client-side rule: with either term present, a row must
    # hit invoice OR po (not both) to survive — replicated exactly rather than
    # simplified to an AND, which would change what the filter selects.
    if pend_invoice or pend_po:
        ors = []
        if pend_invoice:
            ors.append(Device.invoice_number.ilike(f"%{pend_invoice}%"))
        if pend_po:
            ors.append(Device.po_number.ilike(f"%{pend_po}%"))
        base_filters.append(or_(*ors))

    count_q = select(func.count()).select_from(Device).where(*base_filters)
    total = (await db.execute(count_q)).scalar() or 0

    search = (request.query_params.get("search[value]") or "").strip()
    search_filters = []
    if search:
        like = f"%{search}%"
        search_filters.append(or_(
            Device.barcode.ilike(like), Device.brand.ilike(like),
            Device.model.ilike(like), Device.device_type.ilike(like),
        ))
    filtered = (await db.execute(count_q.where(*search_filters))).scalar() or 0

    col_map = {1: Device.barcode, 2: Device.brand, 3: Device.model,
               4: Device.device_type, 5: Device.ram_gb, 6: Device.storage_gb,
               8: Device.invoice_number, 9: Device.po_number}
    try:
        order_col = int(request.query_params.get("order[0][column]", 0))
    except ValueError:
        order_col = 0
    order_dir = request.query_params.get("order[0][dir]", "desc")
    sort_expr = col_map.get(order_col, Device.created_at)
    order_by = _asc(sort_expr) if order_dir == "asc" else _desc(sort_expr)

    rows = (await db.execute(
        select(Device).where(*base_filters, *search_filters)
        .order_by(order_by, Device.barcode)
        .offset(max(0, start)).limit(min(max(1, length), 5000))
    )).scalars().all()

    def esc(v):
        return escape(str(v)) if v is not None else ""

    data = []
    for d in rows:
        data.append([
            f'<input type="checkbox" class="pendChk" name="device_ids" value="{d.id}" data-barcode="{esc(d.barcode)}">',
            f'<a href="/devices/{esc(d.barcode)}" class="font-monospace text-decoration-none">{esc(d.barcode)}</a>',
            esc(d.brand or "—"), esc(d.model or "—"), esc(d.device_type or "—"),
            f"{d.ram_gb} GB" if d.ram_gb else "—",
            f"{d.storage_gb} GB" if d.storage_gb else "—",
            f'<span class="badge bg-{d.stage_color}">{esc(d.stage_label)}</span>',
            esc(d.invoice_number or ""), esc(d.po_number or ""),
        ])

    return {"draw": draw, "recordsTotal": total, "recordsFiltered": filtered, "data": data}


@router.get("/post-iqc", response_class=HTMLResponse)
async def grn_post_iqc(request: Request, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(allowed),
                       error: str = "", success: str = "", highlight_tag: str = ""):
    grns = (await db.execute(
        select(GRNImport).where(GRNImport.source == "post_iqc",
                                GRNImport.is_deleted == False)
        .order_by(GRNImport.created_at.desc())
    )).scalars().all()
    # Pending = devices currently in IQC stage whose GRN field is still empty.
    # Rows for that table now come from /grn/post-iqc/data (DataTables
    # server-side) — only the count is needed here, for the header badge.
    pending_count = (await db.execute(
        select(func.count()).select_from(Device).where(
            Device.current_stage == DeviceStage.iqc,
            or_(Device.grn_number.is_(None), Device.grn_number == ""),
            Device.is_active == True, Device.is_trashed == False,
        )
    )).scalar() or 0
    return templates.TemplateResponse("grn/post_iqc.html", {
        "request": request, "grns": grns, "pending_count": pending_count,
        "stocked": await _stocked_map(db, grns),
        "current_user": current_user, "error": error, "success": success,
        "highlight_tag": highlight_tag,
        "device_type_options": ["Laptop", "Desktop", "AIO", "Workstation", "Mini PC", "Server", "Tablet"],
    })


@router.post("/map")
async def grn_map(request: Request, grn_id: str = Form(...),
                  device_ids: list[str] = Form(default=[]),
                  db: AsyncSession = Depends(get_db),
                  current_user: User = Depends(allowed)):
    import uuid as _u
    try:
        gid = _u.UUID(grn_id)
    except ValueError:
        raise HTTPException(404)
    g = (await db.execute(select(GRNImport).where(GRNImport.id == gid))).scalar_one_or_none()
    if not g:
        raise HTTPException(404, "GRN not found")
    valid_ids = []
    for d in device_ids:
        try:
            valid_ids.append(_u.UUID(d))
        except (ValueError, AttributeError):
            pass
    if not valid_ids:
        return RedirectResponse(url="/grn/post-iqc?error=No+tag+numbers+selected", status_code=302)
    devices = (await db.execute(
        select(Device).where(Device.id.in_(valid_ids))
    )).scalars().all()
    now = app_now()
    moved = 0
    for d in devices:
        d.grn_number = g.grn_number
        # Mapping a GRN here means the tag is now OxyPC Computers' own stock.
        d.entity = "OxyPC Computers"
        # After GRN mapping the tag leaves IQC and enters the Stock Inward table
        if d.current_stage == DeviceStage.iqc:
            prev = (await db.execute(
                select(StageMovement).where(
                    StageMovement.device_id == d.id,
                    StageMovement.to_stage == d.current_stage,
                    StageMovement.exited_at.is_(None),
                ).order_by(StageMovement.moved_at.desc())
            )).scalars().first()
            if prev:
                prev.exited_at = now
            db.add(StageMovement(
                device_id=d.id, from_stage=DeviceStage.iqc, to_stage=DeviceStage.stock_in,
                moved_by=current_user.username,
                notes=f"GRN {g.grn_number} mapped — moved to Stock Inward"))
            d.current_stage = DeviceStage.stock_in
            d.updated_at = now
            moved += 1
    await audit(db, user=current_user, action="GRN_MAPPED",
                table_name="devices", record_id=str(gid),
                new_value={"grn_number": g.grn_number, "tags": len(valid_ids),
                           "moved_to_stock_in": moved},
                request=request)
    await db.commit()
    return RedirectResponse(
        url=(f"/grn/post-iqc?success=Mapped+GRN+{g.grn_number}+to+{len(valid_ids)}+tag(s)"
             f"+%E2%80%94+{moved}+moved+to+Stock+Inward"),
        status_code=302)


# ── GRN Records ("GRN Board") — 3 tabs, rows served via /records/data ─────────
# Rendering every matching device straight into the HTML (as this page used to)
# froze the browser once the table reached a few thousand rows — same root
# cause already fixed on /grn/post-iqc. Only tab counts (for the nav badges)
# are computed here now; rows come a page at a time from /records/data below.

def _records_base_filters(date_from: str, date_to: str):
    from utils.date_filter import apply_date_range
    filters = [Device.is_active == True, Device.is_trashed == False]
    apply_date_range(filters, Device.created_at, date_from, date_to)
    return filters


@router.get("/records", response_class=HTMLResponse)
async def grn_records(request: Request, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(allowed),
                      date_from: str = Query(default=""),
                      date_to: str = Query(default="")):
    filters = _records_base_filters(date_from, date_to)

    async def _count(*extra):
        q = select(func.count()).select_from(Device).where(*filters, *extra)
        return (await db.execute(q)).scalar() or 0

    assigned_count = await _count(Device.grn_number.isnot(None), Device.grn_number != "")
    not_mapped_count = await _count(or_(Device.grn_number.is_(None), Device.grn_number == ""))
    # Pending for TRC — Deshwal-entity tags still sitting at Stage IQC
    pending_trc_count = await _count(Device.entity == "Deshwal", Device.current_stage == DeviceStage.iqc)

    return templates.TemplateResponse("grn/records.html", {
        "request": request,
        "assigned_count": assigned_count, "not_mapped_count": not_mapped_count,
        "pending_trc_count": pending_trc_count,
        "current_user": current_user,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.get("/records/data")
async def grn_records_data(
    request: Request,
    tab: str = Query(...),  # assigned | not_mapped | pending_trc
    draw: int = 1, start: int = 0, length: int = 25,
    date_from: str = Query(default=""), date_to: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """DataTables server-side feed for the GRN Board's 3 tabs."""
    from html import escape

    filters = _records_base_filters(date_from, date_to)
    show_grn = True
    if tab == "assigned":
        filters += [Device.grn_number.isnot(None), Device.grn_number != ""]
    elif tab == "pending_trc":
        filters += [Device.entity == "Deshwal", Device.current_stage == DeviceStage.iqc]
    else:
        tab = "not_mapped"
        filters += [or_(Device.grn_number.is_(None), Device.grn_number == "")]
        show_grn = False

    count_q = select(func.count()).select_from(Device).where(*filters)
    total = (await db.execute(count_q)).scalar() or 0

    search = (request.query_params.get("search[value]") or "").strip()
    search_filters = []
    if search:
        like = f"%{search}%"
        search_filters.append(or_(
            Device.barcode.ilike(like), Device.brand.ilike(like), Device.model.ilike(like),
        ))
    filtered = (await db.execute(count_q.where(*search_filters))).scalar() or 0

    rows = (await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id, isouter=True)
        .where(*filters, *search_filters)
        .order_by(Device.updated_at.desc())
        .offset(max(0, start)).limit(min(max(1, length), 5000))
    )).all()

    def esc(v):
        return escape(str(v)) if v is not None else ""

    def grade_class(gv):
        return ('success' if gv == 'A' else 'warning text-dark' if gv == 'B'
                else 'danger' if gv in ('C', 'D', 'scrap') else 'secondary')

    data = []
    for d, lot_number in rows:
        gv = d.grade.value if d.grade else ""
        row = []
        if tab == "pending_trc":
            row.append(f'<input type="checkbox" name="device_ids" value="{d.id}" '
                        f'class="form-check-input pending-trc-cb" data-barcode="{esc(d.barcode)}">')
        row += [
            f'<a href="/devices/{esc(d.barcode)}" class="font-monospace text-decoration-none">{esc(d.barcode)}</a>',
            f'<span class="badge bg-info text-dark">{esc(lot_number)}</span>' if lot_number else '—',
            esc(d.brand or '—'), esc(d.model or '—'),
            f'<span class="badge bg-{grade_class(gv)}">{esc(gv or "—")}</span>',
            f'<span class="badge bg-{d.stage_color}">{esc(d.stage_label)}</span>',
        ]
        if show_grn:
            row.append(esc(d.grn_number))
        row.append(d.updated_at.strftime('%d %b %Y') if d.updated_at else '—')
        data.append(row)

    return {"draw": draw, "recordsTotal": total, "recordsFiltered": filtered, "data": data}


@router.post("/records/bulk-move-to-trc")
async def grn_bulk_move_to_trc(
    request: Request,
    device_ids: list[str] = Form(default=[]),
    dest: str = Form(...),  # "selling" | "sold_oxypc"
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Pending for TRC tab — bulk-move selected tag numbers per the chosen
    destination:
      - selling: back to Stage IQC with GRN cleared (re-enters the "GRN in
        TRC" / post-IQC pending queue, awaiting a fresh GRN before sale).
      - sold_oxypc: into Stock Inward (Inventory Manager), GRN value left as-is.
    """
    import uuid as _u
    from services.control_engine import validate_transition
    if dest not in ("selling", "sold_oxypc"):
        return RedirectResponse(url="/grn/records?error=Choose+a+destination", status_code=302)

    valid_ids = []
    for d in device_ids:
        try:
            valid_ids.append(_u.UUID(d))
        except (ValueError, AttributeError):
            pass
    if not valid_ids:
        return RedirectResponse(url="/grn/records?error=No+tag+numbers+selected", status_code=302)

    target_stage = DeviceStage.iqc if dest == "selling" else DeviceStage.stock_in
    label = "Sending for Selling" if dest == "selling" else "Sold to OxyPC Computers"

    devices = (await db.execute(select(Device).where(Device.id.in_(valid_ids)))).scalars().all()
    is_admin = current_user.role.value == "admin"
    now = app_now()
    moved = 0
    skipped = []
    for d in devices:
        try:
            await validate_transition(d, target_stage, db, override_admin=is_admin)
        except HTTPException:
            skipped.append(d.barcode)
            continue
        prev = d.current_stage
        d.current_stage = target_stage
        d.updated_at = now
        if dest == "selling":
            d.grn_number = None
        db.add(StageMovement(device_id=d.id, from_stage=prev, to_stage=target_stage,
                              moved_by=current_user.username,
                              notes=f"GRN Records — Pending for TRC bulk move ({label})"))
        moved += 1

    await audit(db, user=current_user, action="GRN_BULK_MOVE_TO_TRC",
                table_name="devices", record_id=None,
                new_value={"moved": moved, "skipped": len(skipped), "dest": dest}, request=request)
    await db.commit()
    msg = f"{moved}+tag(s)+moved+%E2%80%94+{label.replace(' ', '+')}"
    if skipped:
        import urllib.parse
        msg += f"&error={urllib.parse.quote(f'{len(skipped)} tag(s) could not move (not an allowed transition): ' + ', '.join(skipped[:10]))}"
    return RedirectResponse(url=f"/grn/records?success={msg}", status_code=302)


@router.post("/upload")
async def grn_upload(
    request: Request,
    invoice: UploadFile = File(...),
    source: str = Form("invoice"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    base = "/grn/post-iqc" if source == "post_iqc" else "/grn"
    data = await invoice.read()
    if not data:
        return RedirectResponse(url=f"{base}?error=Empty+file", status_code=302)
    # file_hash is still computed and stored on GRNImport for audit/traceability,
    # but no longer used to block the upload — the same invoice file can be
    # uploaded any number of times to create separate GRNs (e.g. a multi-lot
    # invoice split across several GRN entries).
    file_hash = hashlib.sha256(data).hexdigest()
    from urllib.parse import quote

    # Persist file
    os.makedirs(GRN_UPLOAD_DIR, exist_ok=True)
    grn_number = await _next_grn_12(db)
    safe_name = (invoice.filename or "invoice.pdf").replace("/", "_").replace("\\", "_")
    stored = f"{grn_number}_{safe_name}"
    path = os.path.join(GRN_UPLOAD_DIR, stored)
    with open(path, "wb") as f:
        f.write(data)

    # Best-effort extract
    fields = extract_invoice_fields(path)

    # Duplicate by invoice number (the real business key) — only when one was
    # extracted. Anchored on a non-empty invoice number so a sparse/partial parse
    # (e.g. only a vendor name) never false-positives as a duplicate.
    inv_no = (fields.get("invoice_number") or "").strip()
    if inv_no:
        same_grn = (await db.execute(
            select(GRNImport.grn_number).where(GRNImport.invoice_number == inv_no,
                                               GRNImport.is_deleted == False)
        )).scalar_one_or_none()
        if same_grn:
            try:
                os.remove(path)
            except OSError:
                pass
            return RedirectResponse(
                url=f"{base}?error=" + quote(
                    f"Invoice number {inv_no} already exists as GRN {same_grn}."),
                status_code=302)

    db.add(GRNImport(
        grn_number=grn_number,
        lot_number=fields.get("lot_number"),
        invoice_number=fields["invoice_number"], invoice_date=fields["invoice_date"],
        sender_name=fields["sender_name"], quantity=fields["quantity"], amount=fields["amount"],
        file_name=safe_name, file_path=path, file_hash=file_hash,
        source=("post_iqc" if source == "post_iqc" else "invoice"),
        created_by=current_user.username,
    ))
    await db.commit()
    return RedirectResponse(url=f"{base}?success=GRN+{grn_number}+created", status_code=302)


@router.get("/download/{grn_id}")
async def grn_download(grn_id: str, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(allowed)):
    try:
        import uuid as _u
        gid = _u.UUID(grn_id)
    except ValueError:
        raise HTTPException(404)
    g = (await db.execute(select(GRNImport).where(GRNImport.id == gid))).scalar_one_or_none()
    if not g or not g.file_path or not os.path.exists(g.file_path):
        raise HTTPException(404, "File not found")
    return FileResponse(g.file_path, filename=g.file_name or "invoice.pdf",
                        media_type="application/pdf")


@router.post("/{grn_id}/validate")
async def grn_validate(
    grn_id: str, request: Request,
    received_qty: str = Form(""), grn_number: str = Form(""), notes: str = Form(""),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(allowed),
):
    """Validate GRN (from the GRN Import page) — marks the GRN as validated."""
    try:
        import uuid as _u
        gid = _u.UUID(grn_id)
    except ValueError:
        raise HTTPException(404)
    g = (await db.execute(select(GRNImport).where(GRNImport.id == gid))).scalar_one_or_none()
    if not g:
        raise HTTPException(404, "GRN not found")
    g.validated = True
    # Persist what the operator entered — previously accepted then discarded,
    # which meant discrepancy notes at the Plant GRN stage were silently lost.
    try:
        g.received_qty = int(received_qty) if str(received_qty).strip() else None
    except (ValueError, TypeError):
        g.received_qty = None
    g.validation_ref = (grn_number or "").strip()[:100] or None
    g.validation_notes = (notes or "").strip()[:500] or None

    # Auto-map: validating a Plant GRN now maps the linked lot's IQC-stage
    # devices to Stock Inward automatically — previously the operator had to
    # go to GRN post IQC and run "Map this GRN" by hand for every lot.
    auto_mapped = 0
    if g.lot_number:
        lot = (await db.execute(
            select(Lot).where(Lot.lot_number == g.lot_number)
        )).scalar_one_or_none()
        if lot:
            devices = (await db.execute(
                select(Device).where(Device.lot_id == lot.id,
                                     Device.current_stage == DeviceStage.iqc,
                                     Device.is_active == True)
            )).scalars().all()
            now = app_now()
            for d in devices:
                d.grn_number = g.grn_number
                prev = (await db.execute(
                    select(StageMovement).where(
                        StageMovement.device_id == d.id,
                        StageMovement.to_stage == d.current_stage,
                        StageMovement.exited_at.is_(None),
                    ).order_by(StageMovement.moved_at.desc())
                )).scalars().first()
                if prev:
                    prev.exited_at = now
                db.add(StageMovement(
                    device_id=d.id, from_stage=DeviceStage.iqc,
                    to_stage=DeviceStage.stock_in, moved_by=current_user.username,
                    notes=f"GRN {g.grn_number} validated — auto-mapped to Stock Inward"))
                d.current_stage = DeviceStage.stock_in
                d.updated_at = now
                auto_mapped += 1
    await db.commit()
    return JSONResponse({"ok": True, "grn_number": g.grn_number, "auto_mapped": auto_mapped})


@router.post("/{grn_id}/delete")
async def grn_delete(
    grn_id: str, request: Request,
    source: str = Form("invoice"),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(allowed),
):
    """Soft-delete a GRN (hidden from tables, file + row kept for audit/compliance)."""
    base = "/grn/post-iqc" if source == "post_iqc" else "/grn"
    try:
        import uuid as _u
        gid = _u.UUID(grn_id)
    except ValueError:
        raise HTTPException(404)
    g = (await db.execute(select(GRNImport).where(GRNImport.id == gid))).scalar_one_or_none()
    if not g:
        raise HTTPException(404, "GRN not found")
    g.is_deleted = True
    g.deleted_at = app_now()
    await audit(db, user=current_user, action="GRN_DELETED",
                table_name="grn_imports", record_id=str(gid),
                old_value={"grn_number": g.grn_number, "invoice_number": g.invoice_number},
                request=request)
    await db.commit()
    return RedirectResponse(url=f"{base}?success=GRN+{g.grn_number}+deleted", status_code=302)


@router.post("/{grn_id}/edit")
async def grn_edit(
    grn_id: str, request: Request,
    invoice_number: str = Form(""), invoice_date: str = Form(""),
    sender_name: str = Form(""), quantity: str = Form(""), amount: str = Form(""),
    lot_number: str = Form(""),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(allowed),
):
    try:
        import uuid as _u
        gid = _u.UUID(grn_id)
    except ValueError:
        raise HTTPException(404)
    g = (await db.execute(select(GRNImport).where(GRNImport.id == gid))).scalar_one_or_none()
    if not g:
        raise HTTPException(404, "GRN not found")
    g.invoice_number = invoice_number or None
    g.invoice_date = invoice_date or None
    g.lot_number = lot_number or None
    g.sender_name = sender_name or None
    try:
        g.quantity = int(quantity) if quantity else None
    except ValueError:
        pass
    try:
        g.amount = Decimal(amount.replace(",", "")) if amount else None
    except Exception:
        pass
    await db.commit()
    return RedirectResponse(url=f"/grn?success=GRN+{g.grn_number}+updated", status_code=302)


# ── Legacy per-lot GRN status view (kept; not in nav) ─────────────────────────

@router.get("/lots-status", response_class=HTMLResponse)
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
    lot.grn_system_number = grn_number
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
