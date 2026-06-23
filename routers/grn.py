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
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, update

from database import get_db
from models.user import User, UserRole
from models.lot import Lot
from models.device import Device, DeviceStage
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
            Lot.grn_number_new.like(f"GRN-{today}-%")
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
        .order_by(GRNImport.created_at.desc()).limit(500)
    )).scalars().all()
    return templates.TemplateResponse("grn/import.html", {
        "request": request, "grns": rows, "current_user": current_user,
        "error": error, "success": success,
    })


# ── GRN post IQC (item 14): same import/validate/edit, plus Map-to-Tag ─────────

@router.get("/post-iqc", response_class=HTMLResponse)
async def grn_post_iqc(request: Request, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(allowed),
                       error: str = "", success: str = "", highlight_tag: str = ""):
    grns = (await db.execute(
        select(GRNImport).where(GRNImport.source == "post_iqc",
                                GRNImport.is_deleted == False)
        .order_by(GRNImport.created_at.desc()).limit(500)
    )).scalars().all()
    # Pending = devices currently in IQC stage whose GRN field is still empty
    pending = (await db.execute(
        select(Device).where(
            Device.current_stage == DeviceStage.iqc,
            or_(Device.grn_number.is_(None), Device.grn_number == ""),
            Device.is_active == True, Device.is_trashed == False,
        ).order_by(Device.created_at.desc()).limit(1000)
    )).scalars().all()
    return templates.TemplateResponse("grn/post_iqc.html", {
        "request": request, "grns": grns, "pending": pending,
        "current_user": current_user, "error": error, "success": success,
        "highlight_tag": highlight_tag,
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
    await db.execute(
        update(Device).where(Device.id.in_(valid_ids)).values(grn_number=g.grn_number)
    )
    await audit(db, user=current_user, action="GRN_MAPPED",
                table_name="devices", record_id=str(gid),
                new_value={"grn_number": g.grn_number, "tags": len(valid_ids)},
                request=request)
    await db.commit()
    return RedirectResponse(
        url=f"/grn/post-iqc?success=Mapped+GRN+{g.grn_number}+to+{len(valid_ids)}+tag(s)",
        status_code=302)


# ── GRN Records (item 16): two paginated tables by source ─────────────────────

@router.get("/records", response_class=HTMLResponse)
async def grn_records(request: Request, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(allowed)):
    base = (
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id, isouter=True)
        .where(Device.is_active == True, Device.is_trashed == False)
    )
    # GRN Assigned — tag numbers that already have a GRN value
    assigned = (await db.execute(
        base.where(Device.grn_number.isnot(None), Device.grn_number != "")
        .order_by(Device.updated_at.desc()).limit(5000)
    )).all()
    # GRN Not Mapped — tag numbers whose GRN value is still empty
    not_mapped = (await db.execute(
        base.where(or_(Device.grn_number.is_(None), Device.grn_number == ""))
        .order_by(Device.updated_at.desc()).limit(5000)
    )).all()
    return templates.TemplateResponse("grn/records.html", {
        "request": request, "assigned": assigned, "not_mapped": not_mapped,
        "current_user": current_user,
    })


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
    file_hash = hashlib.sha256(data).hexdigest()
    from urllib.parse import quote

    # Duplicate by exact file (identical bytes already uploaded)
    dup_grn = (await db.execute(
        select(GRNImport.grn_number).where(GRNImport.file_hash == file_hash,
                                           GRNImport.is_deleted == False)
    )).scalar_one_or_none()
    if dup_grn:
        return RedirectResponse(
            url=f"{base}?error=" + quote(
                f"This exact invoice file was already uploaded as GRN {dup_grn}. "
                f"Open it from the table below — or upload a different file."),
            status_code=302)

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
    await db.commit()
    return RedirectResponse(url=f"/grn?success=GRN+{g.grn_number}+validated", status_code=302)


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
