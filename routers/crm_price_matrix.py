"""CRM Grade Price Matrix — buy/sell price benchmarks by device type, grade, material."""
import csv
import io
from datetime import datetime
from utils.timezone import app_now
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user, verify_csrf
from models.user import User, UserRole
from models.crm import GradePriceMatrix, GRADES, MATERIAL_TYPES

router = APIRouter(prefix="/crm/price-matrix", tags=["crm-price-matrix"], dependencies=[Depends(verify_csrf)])

DEVICE_TYPES = [
    "Laptop", "Desktop", "Monitor", "TFT / LCD Screen", "UPS",
    "Printer", "Server", "Tablet", "Mobile", "Projector", "Others",
]

ADMIN_ROLES = (UserRole.admin, UserRole.sales_manager, UserRole.inventory_manager)


# ── LIST ─────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def price_matrix_list(
    request: Request,
    device_type: str = Query(default=""),
    grade: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(GradePriceMatrix).order_by(
        GradePriceMatrix.device_type, GradePriceMatrix.grade
    )
    if device_type:
        query = query.where(GradePriceMatrix.device_type == device_type)
    if grade:
        query = query.where(GradePriceMatrix.grade == grade)

    result = await db.execute(query)
    matrix = result.scalars().all()
    material_map = dict(MATERIAL_TYPES)

    return templates.TemplateResponse("crm/price_matrix/list.html", {
        "request": request, "current_user": current_user,
        "matrix": matrix, "material_map": material_map,
        "device_types": DEVICE_TYPES, "grades": GRADES,
        "sel_device": device_type, "sel_grade": grade,
        "can_edit": current_user.role in ADMIN_ROLES,
    })


# ── NEW ───────────────────────────────────────────────────────────────────────

@router.get("/new", response_class=HTMLResponse)
async def new_matrix_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ADMIN_ROLES:
        return RedirectResponse(url="/crm/price-matrix?error=Permission+denied", status_code=302)
    return templates.TemplateResponse("crm/price_matrix/form.html", {
        "request": request, "current_user": current_user,
        "row": None, "device_types": DEVICE_TYPES,
        "grades": GRADES, "material_types": MATERIAL_TYPES,
    })


@router.post("/new")
async def create_matrix_row(
    request: Request,
    device_type:    str = Form(...),
    grade:          str = Form(...),
    material_type:  str = Form(default=None),
    brand:          str = Form(default=None),
    min_buy_price:  str = Form(default=None),
    max_buy_price:  str = Form(default=None),
    target_sell:    str = Form(default=None),
    min_margin_pct: str = Form(default="15"),
    notes:          str = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ADMIN_ROLES:
        return RedirectResponse(url="/crm/price-matrix?error=Permission+denied", status_code=302)

    def _n(v): return float(v) if v and v.strip() else None

    row = GradePriceMatrix(
        device_type=device_type,
        grade=grade,
        material_type=material_type or None,
        brand=brand or None,
        min_buy_price=_n(min_buy_price),
        max_buy_price=_n(max_buy_price),
        target_sell=_n(target_sell),
        min_margin_pct=_n(min_margin_pct) or 15.0,
        notes=notes or None,
        updated_by=current_user.username,
    )
    db.add(row)
    await db.commit()
    return RedirectResponse(url="/crm/price-matrix?success=Row+added", status_code=302)


# ── EDIT ─────────────────────────────────────────────────────────────────────

@router.get("/{row_id}/edit", response_class=HTMLResponse)
async def edit_matrix_form(
    request: Request,
    row_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ADMIN_ROLES:
        return RedirectResponse(url="/crm/price-matrix?error=Permission+denied", status_code=302)
    result = await db.execute(select(GradePriceMatrix).where(GradePriceMatrix.id == row_id))
    row = result.scalar_one_or_none()
    if not row:
        return RedirectResponse(url="/crm/price-matrix?error=Not+found", status_code=302)
    return templates.TemplateResponse("crm/price_matrix/form.html", {
        "request": request, "current_user": current_user,
        "row": row, "device_types": DEVICE_TYPES,
        "grades": GRADES, "material_types": MATERIAL_TYPES,
    })


@router.post("/{row_id}/edit")
async def update_matrix_row(
    request: Request,
    row_id:         str,
    device_type:    str = Form(...),
    grade:          str = Form(...),
    material_type:  str = Form(default=None),
    brand:          str = Form(default=None),
    min_buy_price:  str = Form(default=None),
    max_buy_price:  str = Form(default=None),
    target_sell:    str = Form(default=None),
    min_margin_pct: str = Form(default="15"),
    notes:          str = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ADMIN_ROLES:
        return RedirectResponse(url="/crm/price-matrix?error=Permission+denied", status_code=302)

    def _n(v): return float(v) if v and v.strip() else None

    result = await db.execute(select(GradePriceMatrix).where(GradePriceMatrix.id == row_id))
    row = result.scalar_one_or_none()
    if not row:
        return RedirectResponse(url="/crm/price-matrix?error=Not+found", status_code=302)

    row.device_type    = device_type
    row.grade          = grade
    row.material_type  = material_type or None
    row.brand          = brand or None
    row.min_buy_price  = _n(min_buy_price)
    row.max_buy_price  = _n(max_buy_price)
    row.target_sell    = _n(target_sell)
    row.min_margin_pct = _n(min_margin_pct) or 15.0
    row.notes          = notes or None
    row.updated_by     = current_user.username
    row.updated_at     = app_now()
    await db.commit()
    return RedirectResponse(url="/crm/price-matrix?success=Row+updated", status_code=302)


# ── DELETE ────────────────────────────────────────────────────────────────────

@router.post("/{row_id}/delete")
async def delete_matrix_row(
    row_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ADMIN_ROLES:
        return RedirectResponse(url="/crm/price-matrix?error=Permission+denied", status_code=302)
    result = await db.execute(select(GradePriceMatrix).where(GradePriceMatrix.id == row_id))
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
    return RedirectResponse(url="/crm/price-matrix?success=Row+deleted", status_code=302)


# ── BULK UPLOAD ───────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_matrix(
    request: Request,
    matrix_file:    UploadFile = File(...),
    skip_duplicates: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ADMIN_ROLES:
        return RedirectResponse(url="/crm/price-matrix?error=Permission+denied", status_code=302)

    filename = (matrix_file.filename or "").lower()
    content = await matrix_file.read()

    # ── Column-name normaliser (safe against None keys) ───────────────────────
    def _norm(s) -> str:
        if not s or not isinstance(s, str):
            return ""
        return s.lower().strip().replace(" ", "_").replace("-", "_")

    _COL_ALIASES = {
        "device": "device_type", "devicetype": "device_type", "type": "device_type",
        "device_types": "device_type",
        "material": "material_type", "materialtype": "material_type",
        "min_buy": "min_buy_price", "min_price": "min_buy_price", "buy_min": "min_buy_price",
        "min_buy_price": "min_buy_price",
        "max_buy": "max_buy_price", "max_price": "max_buy_price", "buy_max": "max_buy_price",
        "max_buy_price": "max_buy_price",
        "sell": "target_sell", "sell_price": "target_sell", "target": "target_sell",
        "target_sell_price": "target_sell",
        "margin": "min_margin_pct", "min_margin": "min_margin_pct",
        "min_margin_pct": "min_margin_pct", "margin_pct": "min_margin_pct",
        "note": "notes", "remarks": "notes", "comment": "notes",
    }

    def _normalise_row(row: dict) -> dict:
        out = {}
        for k, v in row.items():
            nk = _norm(k)
            if not nk:          # skip None / empty DictReader restkey entries
                continue
            canonical = _COL_ALIASES.get(nk, nk)
            out[canonical] = str(v).strip() if v is not None else ""
        return out

    # ── Parse rows from CSV or XLSX ────────────────────────────────────────────
    rows_data    = []
    detected_cols: list = []
    try:
        if filename.endswith(".xlsx"):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            ws = wb.active
            headers = None
            for r in ws.iter_rows(values_only=True):
                if all(c is None for c in r):          # skip completely blank rows
                    continue
                if headers is None:
                    raw_hdrs = [_norm(str(c)) if c is not None else "" for c in r]
                    headers  = [_COL_ALIASES.get(h, h) if h else "" for h in raw_hdrs]
                    detected_cols = [h for h in headers if h]
                    continue
                rows_data.append(dict(zip(
                    headers,
                    [str(v).strip() if v is not None else "" for v in r]
                )))
        elif filename.endswith(".csv"):
            # ── Encoding fallback chain ────────────────────────────────────────
            text = None
            for enc in ("utf-8-sig", "utf-16", "latin-1"):
                try:
                    text = content.decode(enc)
                    break
                except (UnicodeDecodeError, Exception):
                    continue
            if text is None:
                return RedirectResponse(
                    url="/crm/price-matrix?error=Could+not+decode+CSV+file+%28try+saving+as+UTF-8%29",
                    status_code=302,
                )
            text = text.replace("\r\n", "\n").replace("\r", "\n")

            # ── Auto-detect delimiter (comma, semicolon, tab, pipe) ────────────
            sample = text[:4096]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = None

            if dialect:
                reader = csv.DictReader(io.StringIO(text), dialect=dialect)
            else:
                reader = csv.DictReader(io.StringIO(text))

            # Normalise header names before reading rows
            if reader.fieldnames:
                reader.fieldnames = [
                    _COL_ALIASES.get(_norm(f), _norm(f)) if _norm(f) else ""
                    for f in reader.fieldnames
                ]
                detected_cols = [f for f in reader.fieldnames if f]

            for row in reader:
                rows_data.append(_normalise_row(row))
        else:
            return RedirectResponse(url="/crm/price-matrix?error=Only+CSV+and+XLSX+files+are+supported", status_code=302)
    except Exception as e:
        return RedirectResponse(url=f"/crm/price-matrix?error=Parse+error:+{str(e)[:80]}", status_code=302)

    # If required columns absent, redirect with diagnostic
    if detected_cols and "device_type" not in detected_cols:
        cols_str = "+".join(detected_cols[:8])
        return RedirectResponse(
            url=f"/crm/price-matrix?error=Column+%27device_type%27+not+found.+Detected:+{cols_str}",
            status_code=302,
        )
    if detected_cols and "grade" not in detected_cols:
        cols_str = "+".join(detected_cols[:8])
        return RedirectResponse(
            url=f"/crm/price-matrix?error=Column+%27grade%27+not+found.+Detected:+{cols_str}",
            status_code=302,
        )

    def _n(v): return float(v) if v and v.strip() else None

    imported = skipped = errors = 0
    do_skip = bool(skip_duplicates)

    for rd in rows_data:
        device_type = rd.get("device_type", "").strip()
        grade       = rd.get("grade", "").strip()
        if not device_type or not grade:
            errors += 1
            continue

        if do_skip:
            brand_val = rd.get("brand", "").strip() or None
            existing_q = select(GradePriceMatrix).where(
                GradePriceMatrix.device_type == device_type,
                GradePriceMatrix.grade == grade,
            )
            if brand_val:
                existing_q = existing_q.where(GradePriceMatrix.brand == brand_val)
            existing_r = await db.execute(existing_q)
            if existing_r.scalar_one_or_none():
                skipped += 1
                continue

        row = GradePriceMatrix(
            device_type    = device_type,
            grade          = grade,
            material_type  = rd.get("material_type", "").strip() or None,
            brand          = rd.get("brand", "").strip() or None,
            min_buy_price  = _n(rd.get("min_buy_price", "")),
            max_buy_price  = _n(rd.get("max_buy_price", "")),
            target_sell    = _n(rd.get("target_sell", "")),
            min_margin_pct = _n(rd.get("min_margin_pct", "")) or 15.0,
            notes          = rd.get("notes", "").strip() or None,
            updated_by     = current_user.username,
        )
        db.add(row)
        imported += 1

    await db.commit()
    msg = f"Imported+{imported}+row(s)"
    if skipped:
        msg += f",+skipped+{skipped}+duplicate(s)"
    if errors:
        msg += f",+{errors}+row(s)+missing+required+fields"
    return RedirectResponse(url=f"/crm/price-matrix?success={msg}", status_code=302)
