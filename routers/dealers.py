from templates_config import templates
from datetime import datetime, date
from utils.timezone import app_now
import csv
import io
import math
from decimal import Decimal
from fastapi import APIRouter, Depends, Form, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, Integer
from sqlalchemy.orm import selectinload
from database import get_db
from models.dealers import Dealer, DealerCall, DealerAssignment, DealerOrder, DealerCreditNote
from models.user import User, UserRole
from auth.dependencies import get_current_user, require_roles, verify_csrf, require_module_perm
from models.crm import CustomerReceipt
from services.audit_engine import audit

router = APIRouter(prefix="/dealers", tags=["dealers"])

SALES_ROLES = (UserRole.admin, UserRole.sales, UserRole.sales_manager, UserRole.telecaller)

# FastAPI dependency — use in route signatures instead of manual role checks
require_sales = require_roles(*SALES_ROLES)
require_sales_mgr = require_roles(UserRole.admin, UserRole.sales_manager)
OUTSTANDING_STATUSES = ("pending", "confirmed", "delivered")
PER_PAGE = 50


def _ranked_calls_subq(ids_subq):
    """Latest call (rn == 1) per dealer_id, restricted to the given dealer-id subquery."""
    rn_col = func.row_number().over(
        partition_by=DealerCall.dealer_id,
        order_by=DealerCall.call_date.desc()
    ).label("rn")
    return select(
        DealerCall.dealer_id,
        DealerCall.call_outcome,
        DealerCall.next_followup_date,
        rn_col,
    ).where(DealerCall.dealer_id.in_(ids_subq)).subquery()


def _combine_date_time(date_str: str | None, time_str: str | None) -> datetime | None:
    """Combine a 'YYYY-MM-DD' date field and an 'HH:MM' time field into a
    datetime. Defaults to 00:00 if no time given, or midnight if only a
    date string was submitted (also handles a plain ISO datetime string)."""
    if not date_str or not date_str.strip():
        return None
    date_str = date_str.strip()
    time_str = (time_str or "").strip() or "00:00"
    try:
        return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        try:
            return datetime.fromisoformat(date_str)
        except ValueError:
            return None


def _upsell_suggestions(dealer: Dealer, outstanding_live: float = 0.0) -> list:
    suggestions = []
    days_since_sale = None
    if dealer.last_sale_date:
        days_since_sale = (app_now() - dealer.last_sale_date).days
    if days_since_sale and days_since_sale > 30:
        suggestions.append(f"No purchase in {days_since_sale} days — good time to reconnect with new stock offers")
    if outstanding_live > 0:
        suggestions.append(f"Outstanding ₹{int(outstanding_live):,} — can offer credit extension for new order")
    if dealer.preferred_categories:
        suggestions.append(f"Prefers: {dealer.preferred_categories} — share availability updates")
    if not dealer.last_sale_date:
        suggestions.append("New dealer — introduce full product catalog")
    return suggestions


@router.get("", response_class=HTMLResponse)
async def list_dealers(
    request: Request,
    q: str = Query(default=""),
    status: str = Query(default=""),
    assigned: str = Query(default=""),
    city: str = Query(default=""),
    last_order_from: str = Query(default=""),
    last_order_to: str = Query(default=""),
    followup_from: str = Query(default=""),
    followup_to: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    from sqlalchemy import or_
    base_query = select(Dealer)
    if q:
        like = f"%{q}%"
        base_query = base_query.where(or_(
            Dealer.business_name.ilike(like),
            Dealer.city.ilike(like),
            Dealer.phone.ilike(like),
            Dealer.contact_person.ilike(like),
        ))
    if status:
        base_query = base_query.where(Dealer.status == status)
    if assigned:
        base_query = base_query.where(Dealer.assigned_to == assigned)
    elif current_user.role in (UserRole.sales, UserRole.telecaller):
        base_query = base_query.where(Dealer.assigned_to == current_user.username)
    if city:
        base_query = base_query.where(Dealer.city.ilike(f"%{city}%"))
    if last_order_from:
        try:
            base_query = base_query.where(
                Dealer.last_sale_date >= datetime.strptime(last_order_from, "%Y-%m-%d")
            )
        except ValueError:
            pass
    if last_order_to:
        try:
            base_query = base_query.where(
                Dealer.last_sale_date <= datetime.strptime(last_order_to, "%Y-%m-%d")
            )
        except ValueError:
            pass

    # Followup date filter — filter dealers who have a DealerCall with
    # next_followup_date in the given range
    if followup_from or followup_to:
        fu_subq = select(DealerCall.dealer_id).distinct()
        if followup_from:
            try:
                fu_subq = fu_subq.where(
                    DealerCall.next_followup_date >= datetime.strptime(followup_from, "%Y-%m-%d")
                )
            except ValueError:
                pass
        if followup_to:
            try:
                fu_subq = fu_subq.where(
                    DealerCall.next_followup_date <= datetime.strptime(followup_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
                )
            except ValueError:
                pass
        base_query = base_query.where(Dealer.id.in_(fu_subq))

    # Total count
    count_result = await db.execute(select(func.count()).select_from(base_query.subquery()))
    total_count = count_result.scalar() or 0
    total_pages = max(1, math.ceil(total_count / PER_PAGE))
    page = min(page, total_pages)

    # Active count
    active_q = base_query.where(Dealer.status == "active")
    active_result = await db.execute(select(func.count()).select_from(active_q.subquery()))
    active_count = active_result.scalar() or 0

    # Subquery of filtered dealer IDs — shared by followup_count, outstanding, outcome_stats
    filtered_ids_subq = select(Dealer.id).select_from(base_query.subquery())

    today = app_now().date()

    # Paginated dealer rows
    offset = (page - 1) * PER_PAGE
    dealers = (await db.execute(
        base_query.order_by(Dealer.business_name).offset(offset).limit(PER_PAGE)
    )).scalars().all()

    dealer_ids = [d.id for d in dealers]

    # Most recent call outcome + items per dealer (for pills) using window function
    recent_call_map: dict = {}
    if dealer_ids:
        rn_col = func.row_number().over(
            partition_by=DealerCall.dealer_id,
            order_by=DealerCall.call_date.desc()
        ).label("rn")
        inner = select(
            DealerCall.dealer_id,
            DealerCall.call_outcome,
            DealerCall.items_discussed,
            DealerCall.next_followup_date,
            rn_col,
        ).where(DealerCall.dealer_id.in_(dealer_ids)).subquery()
        rc_rows = (await db.execute(
            select(inner.c.dealer_id, inner.c.call_outcome, inner.c.items_discussed, inner.c.next_followup_date)
            .where(inner.c.rn == 1)
        )).all()
        recent_call_map = {
            str(r.dealer_id): {
                "outcome": r.call_outcome,
                "items_text": r.items_discussed or "",
                "next_followup_date": r.next_followup_date,
            }
            for r in rc_rows
        }

    # ── Outcome distribution (respects the list's own filters, all roles) ────
    ranked_calls_inner = _ranked_calls_subq(filtered_ids_subq)
    outcome_rows = (await db.execute(
        select(ranked_calls_inner.c.call_outcome, func.count().label("cnt"))
        .where(ranked_calls_inner.c.rn == 1)
        .group_by(ranked_calls_inner.c.call_outcome)
    )).all()
    outcome_stats: dict = {(row.call_outcome or ""): row.cnt for row in outcome_rows}

    # ── Follow-up counts — scoped to the logged-in user's own dealers unless
    # admin (admin sees the count across all dealers, ignoring assignment) ───
    if current_user.role == UserRole.admin:
        followup_scope_ids = select(Dealer.id)
    else:
        followup_scope_ids = select(Dealer.id).where(Dealer.assigned_to == current_user.username)
    followup_ranked = _ranked_calls_subq(followup_scope_ids)

    # followup_count: dealers whose LATEST call outcome is 'followup'
    # AND whose next_followup_date is today or already past (i.e. due / overdue)
    fu_result = await db.execute(
        select(func.count())
        .select_from(followup_ranked)
        .where(
            followup_ranked.c.rn == 1,
            followup_ranked.c.call_outcome == 'followup',
            func.date(followup_ranked.c.next_followup_date) <= today,
        )
    )
    followup_count = int(fu_result.scalar() or 0)

    # today_followup_count: dealers whose LATEST call has a next_followup_date
    # scheduled for exactly today (regardless of outcome)
    today_fu_result = await db.execute(
        select(func.count())
        .select_from(followup_ranked)
        .where(
            followup_ranked.c.rn == 1,
            func.date(followup_ranked.c.next_followup_date) == today,
        )
    )
    today_followup_count = int(today_fu_result.scalar() or 0)
    # ──────────────────────────────────────────────────────────────────────────

    # Sales users list for admin user-filter dropdown
    sales_users: list = []
    if current_user.role == UserRole.admin:
        su_result = await db.execute(
            select(User).where(
                User.role.in_([UserRole.sales, UserRole.sales_manager, UserRole.telecaller]),
                User.status == True,
            ).order_by(User.full_name)
        )
        sales_users = su_result.scalars().all()

    # Outstanding total — scoped to filtered dealers
    out_total_result = await db.execute(
        select(func.coalesce(func.sum(DealerOrder.due_amount), 0))
        .where(
            DealerOrder.dealer_id.in_(filtered_ids_subq),
            DealerOrder.status.in_(OUTSTANDING_STATUSES),
        )
    )
    outstanding = round(float(out_total_result.scalar() or 0))

    return templates.TemplateResponse("dealers/list.html", {
        "request": request,
        "current_user": current_user,
        "dealers": dealers,
        "q": q,
        "status": status,
        "assigned": assigned,
        "city": city,
        "last_order_from": last_order_from,
        "last_order_to": last_order_to,
        "followup_from": followup_from,
        "followup_to": followup_to,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
        "active_count": active_count,
        "followup_count": followup_count,
        "today_followup_count": today_followup_count,
        "outstanding": f"{outstanding:,}",
        "recent_call_map": recent_call_map,
        "outcome_stats": outcome_stats,
        "sales_users": sales_users,
        "per_page": PER_PAGE,
        "today": today,
    })


@router.get("/followups-due", response_class=HTMLResponse)
async def followups_due(
    request: Request,
    today_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    """All dealers whose LATEST call log has a next_followup_date set —
    not just calls due today. Ranked-latest-call subquery (rn == 1 per
    dealer), same pattern used for the followup_count badge on the list page.
    Pass ?today_only=1 to restrict to follow-ups scheduled for today."""
    today = app_now().date()

    rn_col = func.row_number().over(
        partition_by=DealerCall.dealer_id,
        order_by=DealerCall.call_date.desc()
    ).label("rn")
    ranked = select(
        DealerCall.id,
        DealerCall.dealer_id,
        DealerCall.next_followup_date,
        rn_col,
    ).where(DealerCall.next_followup_date.isnot(None)).subquery()

    stmt = (
        select(DealerCall, Dealer.business_name, Dealer.id.label("dealer_id_col"), Dealer.phone)
        .join(ranked, DealerCall.id == ranked.c.id)
        .join(Dealer, DealerCall.dealer_id == Dealer.id)
        .where(ranked.c.rn == 1)
        .order_by(DealerCall.next_followup_date)
    )
    if today_only:
        stmt = stmt.where(func.date(DealerCall.next_followup_date) == today)
    if current_user.role not in (UserRole.admin,):
        stmt = stmt.where(Dealer.assigned_to == current_user.username)
    rows = (await db.execute(stmt)).all()
    return templates.TemplateResponse("dealers/followups.html", {
        "request": request, "current_user": current_user, "rows": rows, "today": today,
        "today_only": today_only,
    })


@router.get("/overdue", response_class=HTMLResponse)
async def overdue_orders(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):

    now = app_now()  # naive UTC — must match DB column (DateTime, no tz)
    rows = (await db.execute(
        select(DealerOrder, Dealer)
        .join(Dealer, DealerOrder.dealer_id == Dealer.id)
        .where(
            DealerOrder.due_amount > 0,
            DealerOrder.payment_due_date.isnot(None),
            DealerOrder.payment_due_date < now,
        )
        .order_by(DealerOrder.payment_due_date)
    )).all()

    overdue = []
    for order, dealer in rows:
        days_overdue = (now - order.payment_due_date).days
        overdue.append({
            "order": order,
            "dealer": dealer,
            "days_overdue": days_overdue,
        })

    return templates.TemplateResponse("dealers/overdue.html", {
        "request": request,
        "current_user": current_user,
        "overdue": overdue,
        "total_due": sum(float(item["order"].due_amount) for item in overdue),
    })


@router.get("/ageing", response_class=HTMLResponse)
async def dealer_ageing(
    request: Request,
    export: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    """Dealer ageing analysis — buckets outstanding amounts by overdue days."""

    rows = (await db.execute(
        select(DealerOrder, Dealer)
        .join(Dealer, DealerOrder.dealer_id == Dealer.id)
        .where(
            DealerOrder.due_amount > 0,
            DealerOrder.status.in_(OUTSTANDING_STATUSES),
        )
        .order_by(Dealer.business_name)
    )).all()

    now = app_now()  # naive UTC — matches DB column (DateTime, no tz)
    dealer_map: dict = {}
    for order, dealer in rows:
        key = str(dealer.id)
        if key not in dealer_map:
            dealer_map[key] = {
                "dealer": dealer,
                "current": 0.0,
                "d30": 0.0,
                "d60": 0.0,
                "d90": 0.0,
                "d90plus": 0.0,
                "total": 0.0,
            }
        amt = float(order.due_amount or 0)
        dealer_map[key]["total"] += amt
        if order.payment_due_date is None or order.payment_due_date >= now:
            dealer_map[key]["current"] += amt
        else:
            days = (now - order.payment_due_date).days
            if days <= 30:
                dealer_map[key]["d30"] += amt
            elif days <= 60:
                dealer_map[key]["d60"] += amt
            elif days <= 90:
                dealer_map[key]["d90"] += amt
            else:
                dealer_map[key]["d90plus"] += amt

    ageing_rows = list(dealer_map.values())
    totals = {
        k: sum(r[k] for r in ageing_rows)
        for k in ("current", "d30", "d60", "d90", "d90plus", "total")
    }

    if export == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Dealer", "Current", "1-30 Days", "31-60 Days", "61-90 Days", "90+ Days", "Total"])
        for r in ageing_rows:
            writer.writerow([
                r["dealer"].business_name,
                f"{r['current']:.2f}",
                f"{r['d30']:.2f}",
                f"{r['d60']:.2f}",
                f"{r['d90']:.2f}",
                f"{r['d90plus']:.2f}",
                f"{r['total']:.2f}",
            ])
        writer.writerow([
            "TOTAL",
            f"{totals['current']:.2f}",
            f"{totals['d30']:.2f}",
            f"{totals['d60']:.2f}",
            f"{totals['d90']:.2f}",
            f"{totals['d90plus']:.2f}",
            f"{totals['total']:.2f}",
        ])
        filename = f"dealer-ageing-{now.strftime('%Y%m%d')}.csv"
        return StreamingResponse(
            iter([output.getvalue().encode("utf-8-sig")]),
            media_type="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    return templates.TemplateResponse("dealers/ageing.html", {
        "request": request,
        "current_user": current_user,
        "ageing_rows": ageing_rows,
        "totals": totals,
        "as_of": now,
    })


@router.get("/bulk-upload-template")
async def dealers_bulk_upload_template():
    """Return a sample CSV template for dealer bulk upload."""
    header = "business_name,contact_person,phone,email,city,dealer_type,gst_number,address,assigned_to\n"
    sample = (
        "Example Traders,Rajesh Kumar,9876543210,rajesh@example.com,Delhi,wholesale,07ABCDE1234F1Z5,"
        "123 Main Street Karol Bagh,sales_user\n"
        "ABC Electronics,Priya Sharma,9123456789,priya@abc.com,Mumbai,retail,,456 MG Road Andheri,\n"
    )
    content = header + sample
    return StreamingResponse(
        iter([content.encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=dealers_bulk_upload_template.csv"},
    )


@router.get("/bulk-upload", response_class=HTMLResponse)
async def dealers_bulk_upload_form(
    request: Request,
    current_user: User = Depends(require_sales),
):
    return templates.TemplateResponse("dealers/bulk_upload.html", {
        "request": request, "current_user": current_user,
        "results": None, "error": None, "detected_cols": [],
    })


@router.post("/bulk-upload", response_class=HTMLResponse)
async def dealers_bulk_upload_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    from fastapi import UploadFile, File
    form = await request.form()
    upload = form.get("file")
    if not upload or not hasattr(upload, "read"):
        return templates.TemplateResponse("dealers/bulk_upload.html", {
            "request": request, "current_user": current_user,
            "results": None, "error": "No file uploaded.",
        })

    raw = await upload.read()
    filename = (getattr(upload, "filename", "") or "").lower()

    # ── Column-name normaliser ─────────────────────────────────────────────────
    def _norm(s) -> str:
        """Safely lowercase + strip + collapse spaces/hyphens → underscores."""
        if not s or not isinstance(s, str):
            return ""
        return s.lower().strip().replace(" ", "_").replace("-", "_")

    _COL_ALIASES = {
        "businessname":   "business_name", "company_name":  "business_name",
        "company":        "business_name", "name":          "business_name",
        "dealer_name":    "business_name", "dealername":    "business_name",
        "firm_name":      "business_name", "firmname":      "business_name",
        "shop_name":      "business_name", "shopname":      "business_name",
        "contact":        "contact_person","contactperson": "contact_person",
        "contact_name":   "contact_person","person":        "contact_person",
        "mobile":         "phone",         "phone_number":  "phone",
        "mobile_number":  "phone",         "contact_no":    "phone",
        "gst":            "gst_number",    "gstin":         "gst_number",
        "gst_no":         "gst_number",    "gstno":         "gst_number",
        "gst_in":         "gst_number",
        "type":           "dealer_type",   "dealertype":    "dealer_type",
        "category":       "dealer_type",
        "assigned":       "assigned_to",   "assignedto":    "assigned_to",
        "sales_person":   "assigned_to",   "salesperson":   "assigned_to",
    }

    def _map_headers(raw_headers: list) -> list:
        """Normalise a list of raw header strings to canonical column names."""
        mapped = []
        for h in raw_headers:
            n = _norm(h)
            mapped.append(_COL_ALIASES.get(n, n) if n else "")
        return mapped

    def _normalise_row(raw_row: dict) -> dict:
        out = {}
        for k, v in raw_row.items():
            n = _norm(k)
            if not n:           # skip None / empty keys (DictReader restkey)
                continue
            canonical = _COL_ALIASES.get(n, n)
            out[canonical] = str(v).strip() if v is not None else ""
        return out

    # ── Parse CSV or XLSX ──────────────────────────────────────────────────────
    rows_data: list  = []
    detected_cols: list = []
    parse_error:  str  = ""

    try:
        if filename.endswith(".xlsx"):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
            ws = wb.active
            headers = None
            for r in ws.iter_rows(values_only=True):
                if all(c is None for c in r):
                    continue
                if headers is None:
                    headers = _map_headers([str(c) if c is not None else "" for c in r])
                    detected_cols = [h for h in headers if h]
                    continue
                row_dict = dict(zip(headers, [str(v).strip() if v is not None else "" for v in r]))
                rows_data.append(row_dict)
        else:
            # CSV — auto-detect encoding then delimiter
            try:
                text_content = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                try:
                    text_content = raw.decode("utf-16")
                except UnicodeDecodeError:
                    text_content = raw.decode("latin-1")
            text_content = text_content.replace('\r\n', '\n').replace('\r', '\n').strip()

            # Auto-detect delimiter (comma, semicolon, tab, pipe)
            sample = text_content[:4096]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
            except csv.Error:
                dialect = csv.excel          # fallback: standard comma CSV

            reader = csv.DictReader(io.StringIO(text_content), dialect=dialect)
            # Force reading fieldnames so we can remap them before iterating
            raw_fields = reader.fieldnames or []
            reader.fieldnames = _map_headers(raw_fields)
            detected_cols = [h for h in reader.fieldnames if h]

            for row in reader:
                rows_data.append(_normalise_row(row))

    except Exception as exc:
        parse_error = f"Could not parse file: {exc}"

    if parse_error:
        return templates.TemplateResponse("dealers/bulk_upload.html", {
            "request": request, "current_user": current_user,
            "results": None, "error": parse_error,
        })

    if not rows_data:
        return templates.TemplateResponse("dealers/bulk_upload.html", {
            "request": request, "current_user": current_user,
            "results": None,
            "error": (
                "No data rows found in the file. "
                f"Columns detected: {detected_cols or 'none'}. "
                "Make sure the file has a header row and at least one data row."
            ),
        })

    # Warn early if business_name column was not detected at all
    col_warning = ""
    if "business_name" not in detected_cols:
        col_warning = (
            f"Column 'business_name' not found. "
            f"Columns detected in your file: {detected_cols}. "
            "Rename your header to 'business_name' and re-upload."
        )

    # ── Import rows ────────────────────────────────────────────────────────────
    # Get current dealer count for code generation
    count_result = await db.execute(select(func.count(Dealer.id)))
    base_count = count_result.scalar() or 0

    # Get existing phones to skip duplicates
    phones_result = await db.execute(select(Dealer.phone).where(Dealer.phone.isnot(None)))
    existing_phones = {r for r in phones_result.scalars().all()}

    added = []
    skipped = []
    errors = []

    seq = 0
    valid_types = {"retail", "wholesale", "online", "corporate"}

    for i, row in enumerate(rows_data, start=2):  # row 1 = header
        business_name = row.get("business_name", "").strip()
        if not business_name:
            skipped.append({"row": i, "reason": "business_name is empty"})
            continue

        phone = row.get("phone", "").strip() or None
        if phone and phone in existing_phones:
            skipped.append({"row": i, "business_name": business_name, "reason": f"Phone {phone} already exists"})
            continue

        dealer_type = row.get("dealer_type", "retail").strip().lower() or "retail"
        if dealer_type not in valid_types:
            dealer_type = "retail"

        dealer_code = f"DLR-{base_count + seq + 1:04d}"
        seq += 1

        try:
            dealer = Dealer(
                dealer_code=dealer_code,
                business_name=business_name,
                contact_person=row.get("contact_person", "").strip() or None,
                phone=phone,
                email=row.get("email", "").strip() or None,
                city=row.get("city", "").strip() or None,
                dealer_type=dealer_type,
                gstin=row.get("gst_number", "").strip() or None,
                address=row.get("address", "").strip() or None,
                assigned_to=row.get("assigned_to", "").strip() or current_user.username,
                status="active",
                created_by=current_user.username,
            )
            db.add(dealer)
            if phone:
                existing_phones.add(phone)
            added.append({"row": i, "business_name": business_name, "dealer_code": dealer_code})
        except Exception as exc:
            errors.append({"row": i, "business_name": business_name, "reason": str(exc)})

    if added:
        await db.commit()

    results = {"added": added, "skipped": skipped, "errors": errors}
    return templates.TemplateResponse("dealers/bulk_upload.html", {
        "request": request, "current_user": current_user,
        "results": results,
        "error": col_warning or None,
        "detected_cols": detected_cols,
    })


@router.get("/new", response_class=HTMLResponse)
async def new_dealer_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    sales_result = await db.execute(
        select(User).where(User.role.in_([UserRole.sales, UserRole.sales_manager, UserRole.telecaller]), User.status == True)
    )
    sales_users = sales_result.scalars().all()
    return templates.TemplateResponse("dealers/form.html", {
        "request": request, "current_user": current_user,
        "dealer": None, "sales_users": sales_users,
    })


@router.post("/new")
async def create_dealer(
    request: Request,
    business_name: str = Form(...),
    first_name: str = Form(default=None),
    last_name: str = Form(default=None),
    contact_person: str = Form(default=None),
    dealer_type: str = Form(default="retail"),
    phone: str = Form(default=None),
    whatsapp_number: str = Form(default=None),
    email: str = Form(default=None),
    gstin: str = Form(default=None),
    address: str = Form(default=None),
    city: str = Form(default=None),
    state: str = Form(default=None),
    pincode: str = Form(default=None),
    preferred_categories: str = Form(default=None),
    credit_limit: float = Form(default=0),
    assigned_to: str = Form(default=None),
    status: str = Form(default="active"),
    notes: str = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
    _perm: User = Depends(require_module_perm("dealers", "add")),
):
    # Auto-generate dealer code
    count_result = await db.execute(select(func.count(Dealer.id)))
    count = count_result.scalar() or 0
    dealer_code = f"DLR{count+1:04d}"

    dealer = Dealer(
        dealer_code=dealer_code,
        business_name=business_name,
        first_name=first_name or None,
        last_name=last_name or None,
        contact_person=contact_person,
        dealer_type=dealer_type,
        phone=phone,
        whatsapp_number=whatsapp_number,
        email=email,
        gstin=gstin,
        address=address,
        city=city,
        state=state,
        pincode=pincode,
        preferred_categories=preferred_categories,
        credit_limit=credit_limit,
        assigned_to=assigned_to or current_user.username,
        status=status,
        notes=notes,
        created_by=current_user.username,
    )
    db.add(dealer)
    await db.commit()
    return RedirectResponse(url=f"/dealers/{dealer.id}?success=Dealer+created", status_code=302)


@router.post("/{dealer_id}/credit-notes/{cn_id}/apply")
async def apply_credit_note(
    request: Request,
    dealer_id: str,
    cn_id: str,
    _csrf: None = Depends(verify_csrf),
    order_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    """Apply a credit note balance against an open dealer order (reduces due_amount)."""

    import uuid as _uuid
    try:
        _uuid.UUID(str(cn_id))
        _uuid.UUID(str(dealer_id))
    except ValueError:
        return RedirectResponse(url="/dealers?error=Invalid+ID", status_code=302)

    # Fetch CN and verify it belongs to this dealer and is not yet applied
    cn_result = await db.execute(
        select(DealerCreditNote)
        .where(DealerCreditNote.id == cn_id, DealerCreditNote.dealer_id == dealer_id)
    )
    cn = cn_result.scalar_one_or_none()
    if not cn:
        return RedirectResponse(url=f"/dealers/{dealer_id}?error=Credit+note+not+found", status_code=302)
    if cn.is_applied:
        return RedirectResponse(url=f"/dealers/{dealer_id}?error=Credit+note+already+applied", status_code=302)

    # Validate order_id UUID before fetching
    try:
        _uuid.UUID(str(order_id))
    except ValueError:
        return RedirectResponse(url=f"/dealers/{dealer_id}?error=Invalid+order+ID", status_code=302)

    # Fetch target order and verify it belongs to this dealer and has outstanding balance
    order_result = await db.execute(
        select(DealerOrder)
        .where(DealerOrder.id == order_id, DealerOrder.dealer_id == dealer_id)
    )
    order = order_result.scalar_one_or_none()
    if not order:
        return RedirectResponse(url=f"/dealers/{dealer_id}?error=Order+not+found", status_code=302)
    if float(order.due_amount or 0) <= 0:
        return RedirectResponse(url=f"/dealers/{dealer_id}?error=Order+has+no+outstanding+balance", status_code=302)

    # Apply: reduce due_amount by min(cn.amount, order.due_amount)
    from decimal import Decimal
    applied_amount = min(cn.amount, order.due_amount)
    order.due_amount = order.due_amount - applied_amount
    if order.due_amount < Decimal("0"):
        order.due_amount = Decimal("0")
    # Mark order as paid if fully settled
    if order.due_amount == Decimal("0") and order.status not in ("cancelled", "paid"):
        order.status = "paid"

    # Mark CN as applied
    cn.is_applied = True
    cn.applied_at = app_now()
    cn.applied_to_order_id = order.id

    # Audit before commit
    await audit(
        db,
        user=current_user,
        action="CREDIT_NOTE_APPLIED",
        table_name="dealer_credit_notes",
        record_id=cn.credit_number,
        notes=f"Applied ₹{applied_amount:,.0f} from CN {cn.credit_number} to order {order.order_number}; new due_amount=₹{float(order.due_amount):,.0f}",
        request=request,
    )

    await db.commit()
    return RedirectResponse(
        url=f"/dealers/{dealer_id}?success=Credit+note+applied+successfully",
        status_code=302,
    )


@router.get("/{dealer_id}/orders/{order_id}/invoice", response_class=HTMLResponse)
async def dealer_order_invoice(
    request: Request,
    dealer_id: str,
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    """Printable GST invoice for a dealer order."""

    import uuid as _uuid
    try:
        _uuid.UUID(str(dealer_id)); _uuid.UUID(str(order_id))
    except ValueError:
        return RedirectResponse(url="/dealers?error=Invalid+ID", status_code=302)

    dealer_result = await db.execute(select(Dealer).where(Dealer.id == dealer_id))
    dealer = dealer_result.scalar_one_or_none()
    if not dealer:
        return RedirectResponse(url="/dealers?error=Dealer+not+found", status_code=302)

    order_result = await db.execute(
        select(DealerOrder).where(DealerOrder.id == order_id, DealerOrder.dealer_id == dealer_id)
    )
    order = order_result.scalar_one_or_none()
    if not order:
        return RedirectResponse(url=f"/dealers/{dealer_id}?error=Order+not+found", status_code=302)

    if not order.invoice_number:
        order.invoice_number = f"INV-{order.order_number}"
        await db.commit()

    return templates.TemplateResponse("dealers/order_invoice.html", {
        "request": request,
        "current_user": current_user,
        "dealer": dealer,
        "order": order,
        "as_of": app_now(),
    })


@router.get("/{dealer_id}", response_class=HTMLResponse)
async def dealer_profile(
    request: Request,
    dealer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    result = await db.execute(select(Dealer).where(Dealer.id == dealer_id))
    dealer = result.scalar_one_or_none()
    if not dealer:
        return RedirectResponse(url="/dealers?error=Dealer+not+found", status_code=302)

    calls_result = await db.execute(
        select(DealerCall).where(DealerCall.dealer_id == dealer.id)
        .order_by(DealerCall.call_date.desc()).limit(20)
    )
    calls = calls_result.scalars().all()

    orders_result = await db.execute(
        select(DealerOrder).where(DealerOrder.dealer_id == dealer.id)
        .order_by(DealerOrder.order_date.desc())
    )
    orders = orders_result.scalars().all()

    # Live outstanding: SUM of due_amount on non-cancelled orders
    outstanding_live = float((await db.execute(
        select(func.coalesce(func.sum(DealerOrder.due_amount), 0))
        .where(DealerOrder.dealer_id == dealer.id, DealerOrder.status.in_(OUTSTANDING_STATUSES))
    )).scalar() or 0)

    credit_notes = (await db.execute(
        select(DealerCreditNote)
        .options(
            selectinload(DealerCreditNote.order),
            selectinload(DealerCreditNote.applied_to_order),
        )
        .where(DealerCreditNote.dealer_id == dealer.id)
        .order_by(DealerCreditNote.created_at.desc())
    )).scalars().all()

    # Open orders eligible for credit-note application (due_amount > 0, non-cancelled)
    open_orders = [o for o in orders if float(o.due_amount or 0) > 0 and o.status in OUTSTANDING_STATUSES]

    today = app_now().date()
    return templates.TemplateResponse("dealers/profile.html", {
        "request": request,
        "current_user": current_user,
        "dealer": dealer,
        "calls": calls,
        "orders": orders,
        "today": today,
        "outstanding_live": outstanding_live,
        "upsell_suggestions": _upsell_suggestions(dealer, outstanding_live),
        "credit_notes": credit_notes,
        "open_orders": open_orders,
    })


@router.get("/{dealer_id}/statement.csv")
async def dealer_statement_csv(
    dealer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    """Download a complete account statement for a dealer as CSV."""
    result = await db.execute(select(Dealer).where(Dealer.id == dealer_id))
    dealer = result.scalar_one_or_none()
    if not dealer:
        return RedirectResponse(url="/dealers?error=Dealer+not+found", status_code=302)

    orders_result = await db.execute(
        select(DealerOrder)
        .where(DealerOrder.dealer_id == dealer.id)
        .order_by(DealerOrder.order_date)
    )
    orders = orders_result.scalars().all()

    cn_result = await db.execute(
        select(DealerCreditNote)
        .where(DealerCreditNote.dealer_id == dealer.id)
        .order_by(DealerCreditNote.credit_date)
    )
    credit_notes = cn_result.scalars().all()

    receipts_result = await db.execute(
        select(CustomerReceipt)
        .where(CustomerReceipt.dealer_id == dealer.id)
        .order_by(CustomerReceipt.receipt_date)
    )
    receipts = receipts_result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header block
    writer.writerow(["ACCOUNT STATEMENT"])
    writer.writerow(["Dealer", dealer.business_name])
    writer.writerow(["Code", dealer.dealer_code])
    writer.writerow(["Generated", app_now().strftime("%d-%m-%Y %H:%M UTC")])
    writer.writerow([])

    # Orders section
    writer.writerow(["ORDERS"])
    writer.writerow(["Order#", "Date", "Total (Rs)", "Paid (Rs)", "Due (Rs)", "Status"])
    total_orders = 0.0
    total_paid_orders = 0.0
    total_due_orders = 0.0
    for o in orders:
        total_val = float(o.total_amount or 0)
        paid_val  = float(o.paid_amount or 0)
        due_val   = float(o.due_amount or 0)
        total_orders      += total_val
        total_paid_orders += paid_val
        total_due_orders  += due_val
        writer.writerow([
            o.order_number,
            o.order_date.strftime("%d-%m-%Y"),
            f"{total_val:.2f}",
            f"{paid_val:.2f}",
            f"{due_val:.2f}",
            o.status,
        ])
    writer.writerow(["TOTAL", "", f"{total_orders:.2f}", f"{total_paid_orders:.2f}", f"{total_due_orders:.2f}", ""])
    writer.writerow([])

    # Credit notes section
    writer.writerow(["CREDIT NOTES"])
    writer.writerow(["Credit#", "Date", "Amount (Rs)", "Reason", "Items"])
    total_credits = 0.0
    for cn in credit_notes:
        cn_val = float(cn.amount or 0)
        total_credits += cn_val
        writer.writerow([
            cn.credit_number,
            cn.credit_date.strftime("%d-%m-%Y"),
            f"{cn_val:.2f}",
            (cn.reason or "").replace("_", " ").title(),
            cn.items_description or "",
        ])
    writer.writerow(["TOTAL CREDITS", "", f"{total_credits:.2f}", "", ""])
    writer.writerow([])

    # Receipts section
    writer.writerow(["RECEIPTS"])
    writer.writerow(["Date", "Amount (Rs)", "Mode", "Reference"])
    total_receipts = 0.0
    for r in receipts:
        r_val = float(r.amount or 0)
        total_receipts += r_val
        writer.writerow([
            r.receipt_date.strftime("%d-%m-%Y"),
            f"{r_val:.2f}",
            r.payment_mode or "",
            r.reference_no or "",
        ])
    writer.writerow(["TOTAL RECEIPTS", f"{total_receipts:.2f}", "", ""])
    writer.writerow([])

    # Summary
    writer.writerow(["SUMMARY"])
    writer.writerow(["Total Order Value", f"{total_orders:.2f}"])
    writer.writerow(["Total Credit Notes", f"{total_credits:.2f}"])
    writer.writerow(["Net Order Value", f"{total_orders - total_credits:.2f}"])
    writer.writerow(["Total Receipts", f"{total_receipts:.2f}"])
    writer.writerow(["Net Outstanding", f"{total_due_orders:.2f}"])

    content = output.getvalue()
    filename = f"statement_{dealer.dealer_code}_{date.today().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{dealer_id}/edit", response_class=HTMLResponse)
async def edit_dealer_form(
    request: Request,
    dealer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    result = await db.execute(select(Dealer).where(Dealer.id == dealer_id))
    dealer = result.scalar_one_or_none()
    if not dealer:
        return RedirectResponse(url="/dealers?error=Not+found", status_code=302)
    sales_result = await db.execute(
        select(User).where(User.role.in_([UserRole.sales, UserRole.sales_manager, UserRole.telecaller]))
    )
    sales_users = sales_result.scalars().all()
    return templates.TemplateResponse("dealers/form.html", {
        "request": request, "current_user": current_user,
        "dealer": dealer, "sales_users": sales_users,
    })


@router.post("/{dealer_id}/edit")
async def update_dealer(
    request: Request,
    dealer_id: str,
    business_name: str = Form(...),
    first_name: str = Form(default=None),
    last_name: str = Form(default=None),
    contact_person: str = Form(default=None),
    dealer_type: str = Form(default="retail"),
    phone: str = Form(default=None),
    whatsapp_number: str = Form(default=None),
    email: str = Form(default=None),
    gstin: str = Form(default=None),
    address: str = Form(default=None),
    city: str = Form(default=None),
    state: str = Form(default=None),
    pincode: str = Form(default=None),
    preferred_categories: str = Form(default=None),
    credit_limit: float = Form(default=0),
    assigned_to: str = Form(default=None),
    status: str = Form(default="active"),
    notes: str = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    result = await db.execute(select(Dealer).where(Dealer.id == dealer_id))
    dealer = result.scalar_one_or_none()
    if not dealer:
        return RedirectResponse(url="/dealers?error=Not+found", status_code=302)
    dealer.business_name = business_name
    dealer.first_name = first_name or None
    dealer.last_name = last_name or None
    dealer.contact_person = contact_person
    dealer.dealer_type = dealer_type
    dealer.phone = phone
    dealer.whatsapp_number = whatsapp_number
    dealer.email = email
    dealer.gstin = gstin
    dealer.address = address
    dealer.city = city
    dealer.state = state
    dealer.pincode = pincode
    dealer.preferred_categories = preferred_categories
    dealer.credit_limit = credit_limit
    dealer.assigned_to = assigned_to
    dealer.status = status
    dealer.notes = notes
    await db.commit()
    return RedirectResponse(url=f"/dealers/{dealer_id}?success=Dealer+updated", status_code=302)


@router.get("/{dealer_id}/call", response_class=HTMLResponse)
async def call_form(
    request: Request,
    dealer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    result = await db.execute(select(Dealer).where(Dealer.id == dealer_id))
    dealer = result.scalar_one_or_none()
    if not dealer:
        return RedirectResponse(url="/dealers", status_code=302)
    return templates.TemplateResponse("dealers/call_form.html", {
        "request": request, "current_user": current_user, "dealer": dealer,
    })


@router.post("/{dealer_id}/call")
async def log_call(
    request: Request,
    dealer_id: str,
    call_mode: str = Form(default="phone"),
    call_type: str = Form(default="outbound"),
    duration_mins: str = Form(default=None),
    call_outcome: str = Form(default=None),
    next_followup_date: str = Form(default=None),
    next_followup_time: str = Form(default=None),
    items_discussed: str = Form(default=None),
    quote_given: str = Form(default=None),
    whatsapp_sent: str = Form(default=None),
    notes: str = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    next_dt = _combine_date_time(next_followup_date, next_followup_time)

    _duration = int(duration_mins) if duration_mins and duration_mins.strip() else None
    _quote = float(quote_given) if quote_given and quote_given.strip() else None

    call = DealerCall(
        dealer_id=dealer_id,
        called_by=current_user.username,
        call_mode=call_mode,
        call_type=call_type,
        duration_mins=_duration,
        call_outcome=call_outcome,
        next_followup_date=next_dt,
        items_discussed=items_discussed,
        quote_given=_quote,
        whatsapp_sent=bool(whatsapp_sent),
        notes=notes,
    )
    db.add(call)

    # Update dealer last_sale_date if order placed
    if call_outcome == 'order_placed':
        result = await db.execute(select(Dealer).where(Dealer.id == dealer_id))
        dealer = result.scalar_one_or_none()
        if dealer:
            dealer.last_sale_date = app_now()

    await db.commit()
    return RedirectResponse(url=f"/dealers/{dealer_id}?success=Call+logged", status_code=302)


# ── EDIT CALL LOG ─────────────────────────────────────────────────────────────

@router.get("/{dealer_id}/calls/{call_id}/edit", response_class=HTMLResponse)
async def edit_call_form(
    request: Request,
    dealer_id: str,
    call_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    dealer = (await db.execute(select(Dealer).where(Dealer.id == dealer_id))).scalar_one_or_none()
    if not dealer:
        return RedirectResponse(url="/dealers", status_code=302)
    call = (await db.execute(
        select(DealerCall).where(DealerCall.id == call_id, DealerCall.dealer_id == dealer.id)
    )).scalar_one_or_none()
    if not call:
        return RedirectResponse(url=f"/dealers/{dealer_id}?error=Call+not+found", status_code=302)
    return templates.TemplateResponse("dealers/call_form.html", {
        "request": request, "current_user": current_user,
        "dealer": dealer, "edit_call": call,
    })


@router.post("/{dealer_id}/calls/{call_id}/edit")
async def update_call(
    request: Request,
    dealer_id: str,
    call_id: str,
    call_mode: str = Form(default="phone"),
    call_type: str = Form(default="outbound"),
    call_date: str = Form(default=None),
    duration_mins: str = Form(default=None),
    call_outcome: str = Form(default=None),
    next_followup_date: str = Form(default=None),
    next_followup_time: str = Form(default=None),
    items_discussed: str = Form(default=None),
    quote_given: str = Form(default=None),
    whatsapp_sent: str = Form(default=None),
    notes: str = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    call = (await db.execute(
        select(DealerCall).where(DealerCall.id == call_id, DealerCall.dealer_id == dealer_id)
    )).scalar_one_or_none()
    if not call:
        return RedirectResponse(url=f"/dealers/{dealer_id}?error=Call+not+found", status_code=302)

    # Parse dates
    next_dt = _combine_date_time(next_followup_date, next_followup_time)

    call_dt = call.call_date
    if call_date and call_date.strip():
        try:
            call_dt = datetime.fromisoformat(call_date)
        except ValueError:
            pass

    call.call_mode = call_mode
    call.call_type = call_type
    call.call_date = call_dt
    call.duration_mins = int(duration_mins) if duration_mins and duration_mins.strip().isdigit() else None
    call.call_outcome = call_outcome or None
    call.next_followup_date = next_dt
    call.items_discussed = (items_discussed or "").strip() or None
    call.quote_given = float(quote_given) if quote_given and quote_given.strip() else None
    call.whatsapp_sent = bool(whatsapp_sent)
    call.notes = (notes or "").strip() or None

    await db.commit()
    return RedirectResponse(url=f"/dealers/{dealer_id}?success=Call+updated", status_code=302)


@router.get("/{dealer_id}/orders/new", response_class=HTMLResponse)
async def new_order_form(
    request: Request,
    dealer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    result = await db.execute(select(Dealer).where(Dealer.id == dealer_id))
    dealer = result.scalar_one_or_none()
    if not dealer:
        return RedirectResponse(url="/dealers?error=Dealer+not+found", status_code=302)
    count_r = await db.execute(select(func.count(DealerOrder.id)))
    n = (count_r.scalar() or 0) + 1
    order_number = f"DO-{app_now().year}-{n:04d}"
    return templates.TemplateResponse("dealers/order_form.html", {
        "request": request, "current_user": current_user,
        "dealer": dealer, "order_number": order_number,
        "today": date.today().isoformat(),
    })


@router.post("/{dealer_id}/orders/new")
async def create_order(
    request: Request,
    dealer_id: str,
    order_number: str = Form(...),
    order_date: str = Form(...),
    items_description: str = Form(default=""),
    total_amount: str = Form(default="0"),
    paid_amount: str = Form(default="0"),
    payment_due_date: str = Form(default=""),
    payment_mode: str = Form(default=""),
    invoice_number: str = Form(default=""),
    notes: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    try:
        total = float(total_amount) if total_amount.strip() else 0.0
        paid  = float(paid_amount)  if paid_amount.strip()  else 0.0
    except ValueError:
        return RedirectResponse(url=f"/dealers/{dealer_id}/orders/new?error=Invalid+amount", status_code=302)
    due = max(0.0, round(total - paid, 2))
    due_dt = None
    if payment_due_date.strip():
        try:
            due_dt = datetime.fromisoformat(payment_due_date)
        except ValueError:
            pass
    order = DealerOrder(
        dealer_id=dealer_id,
        order_number=order_number,
        order_date=datetime.fromisoformat(order_date) if order_date else app_now(),
        items_description=items_description or None,
        total_amount=total,
        paid_amount=paid,
        due_amount=due,
        payment_due_date=due_dt,
        payment_mode=payment_mode or None,
        invoice_number=invoice_number or None,
        status="paid" if due == 0 else "pending",
        notes=notes or None,
        created_by=current_user.username,
    )
    db.add(order)
    dr = await db.execute(select(Dealer).where(Dealer.id == dealer_id))
    dealer = dr.scalar_one_or_none()
    if dealer:
        dealer.total_purchases    = float(dealer.total_purchases    or 0) + total
        dealer.last_sale_date     = app_now()
        dealer.last_sale_amount   = total
    await audit(db, user=current_user, action="ORDER_CREATED",
                table_name="dealer_orders", record_id=str(order.id),
                new_value={"order_number": order_number, "dealer_id": dealer_id,
                           "total_amount": total, "paid_amount": paid,
                           "due_amount": due,
                           "status": "paid" if due == 0 else "pending"},
                request=request)
    await db.commit()
    return RedirectResponse(url=f"/dealers/{dealer_id}?success=Order+created", status_code=302)


@router.post("/{dealer_id}/orders/{order_id}/pay")
async def record_order_payment(
    request: Request,
    dealer_id: str,
    order_id: str,
    amount: str = Form(...),
    payment_mode: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    try:
        amt = float(amount)
        if amt <= 0:
            raise ValueError
    except ValueError:
        return RedirectResponse(url=f"/dealers/{dealer_id}?error=Invalid+amount", status_code=302)
    or_r = await db.execute(select(DealerOrder).where(DealerOrder.id == order_id))
    order = or_r.scalar_one_or_none()
    if not order:
        return RedirectResponse(url=f"/dealers/{dealer_id}?error=Order+not+found", status_code=302)
    order.paid_amount = round(float(order.paid_amount or 0) + amt, 2)
    order.due_amount  = max(0.0, round(float(order.total_amount or 0) - float(order.paid_amount), 2))
    if order.due_amount == 0:
        order.status = "paid"
    if payment_mode:
        order.payment_mode = payment_mode
    await audit(db, user=current_user, action="PAYMENT_RECORDED",
                table_name="dealer_orders", record_id=str(order.id),
                new_value={"payment_amount": amt,
                           "payment_mode": payment_mode or None,
                           "order_id": str(order.id),
                           "dealer_id": dealer_id,
                           "new_paid_amount": float(order.paid_amount),
                           "new_due_amount": float(order.due_amount),
                           "new_status": order.status},
                request=request)
    await db.commit()
    return RedirectResponse(url=f"/dealers/{dealer_id}?success=Payment+recorded", status_code=302)


@router.post("/{dealer_id}/orders/{order_id}/credit-note")
async def create_credit_note(
    request: Request,
    dealer_id: str,
    order_id: str,
    _csrf: None = Depends(verify_csrf),
    amount: str = Form(...),
    reason: str = Form(default=""),
    items_description: str = Form(default=""),
    notes: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    """Issue a credit note against a dealer order (goods return / adjustment)."""
    # Load order and verify ownership
    order_result = await db.execute(
        select(DealerOrder)
        .where(DealerOrder.id == order_id, DealerOrder.dealer_id == dealer_id)
    )
    order = order_result.scalar_one_or_none()
    if not order:
        return RedirectResponse(
            url=f"/dealers/{dealer_id}?error=Order+not+found", status_code=302
        )

    # Validate amount
    try:
        credit_amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        if credit_amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return RedirectResponse(
            url=f"/dealers/{dealer_id}?error=Invalid+credit+amount", status_code=302
        )
    if credit_amount > order.total_amount:
        return RedirectResponse(
            url=f"/dealers/{dealer_id}?error=Credit+exceeds+order+total", status_code=302
        )

    # Generate credit number: CN-YYYY-NNNN
    # Use MAX to find the last issued sequence — more resilient than COUNT under concurrent inserts
    year = app_now().year
    max_result = await db.execute(
        select(func.max(
            func.cast(
                func.split_part(DealerCreditNote.credit_number, "-", 3),
                Integer
            )
        ))
        .where(func.extract("year", DealerCreditNote.created_at) == year)
    )
    last_seq = max_result.scalar() or 0
    credit_number = f"CN-{year}-{last_seq + 1:04d}"

    # Create credit note record
    cn = DealerCreditNote(
        credit_number=credit_number,
        dealer_id=order.dealer_id,
        order_id=order.id,
        amount=credit_amount,
        reason=reason or None,
        items_description=items_description or None,
        notes=notes or None,
        created_by=current_user.username,
    )
    db.add(cn)

    # Adjust order totals
    new_total = max(Decimal("0"), Decimal(str(order.total_amount)) - credit_amount)
    new_due = max(Decimal("0"), new_total - Decimal(str(order.paid_amount)))
    order.total_amount = new_total
    order.due_amount = new_due
    if new_total <= 0:
        order.status = "cancelled"
    elif new_due == 0:
        order.status = "paid"
    # else: keep current status (pending / confirmed / delivered)

    # Audit
    await audit(
        db, user=current_user, action="CREDIT_NOTE_ISSUED",
        table_name="dealer_credit_notes", record_id=credit_number,
        new_value={
            "credit_number": credit_number,
            "order_id": str(order.id),
            "dealer_id": str(order.dealer_id),
            "credit_amount": float(credit_amount),
            "new_order_total": float(new_total),
            "new_order_due": float(new_due),
            "new_order_status": order.status,
            "reason": reason or None,
        },
        request=request,
    )
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        # Most likely a duplicate credit_number under concurrent requests — retry with next seq
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return RedirectResponse(
                url=f"/dealers/{dealer_id}?error=Please+try+again+(concurrent+request)", status_code=302
            )
        raise
    return RedirectResponse(
        url=f"/dealers/{dealer_id}?success=Credit+note+{credit_number}+issued",
        status_code=302,
    )


@router.get("/{dealer_id}/ledger", response_class=HTMLResponse)
async def dealer_ledger(
    request: Request,
    dealer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales_mgr),
):
    dr = await db.execute(select(Dealer).where(Dealer.id == dealer_id))
    dealer = dr.scalar_one_or_none()
    if not dealer:
        return RedirectResponse(url="/dealers?error=Not+found", status_code=302)

    orders_r = await db.execute(
        select(DealerOrder).where(DealerOrder.dealer_id == dealer_id).order_by(DealerOrder.order_date)
    )
    orders = orders_r.scalars().all()

    receipts_r = await db.execute(
        select(CustomerReceipt).where(CustomerReceipt.dealer_id == dealer_id).order_by(CustomerReceipt.receipt_date)
    )
    receipts = receipts_r.scalars().all()

    entries = []
    for o in orders:
        od = o.order_date
        odt = datetime(od.year, od.month, od.day) if not isinstance(od, datetime) else od
        entries.append({
            "date": odt,
            "ref": o.order_number,
            "description": f"Order — {(o.items_description or '')[:60]}",
            "debit": float(o.total_amount or 0),
            "credit": 0.0,
            "type": "order",
        })
    for r in receipts:
        rd = r.receipt_date
        dt = datetime(rd.year, rd.month, rd.day) if not isinstance(rd, datetime) else rd
        entries.append({
            "date": dt,
            "ref": r.reference_no or "—",
            "description": f"Payment received ({r.payment_mode or '—'})",
            "debit": 0.0,
            "credit": float(r.amount or 0),
            "type": "receipt",
        })

    entries.sort(key=lambda x: x["date"])

    balance = 0.0
    for e in entries:
        balance = round(balance + e["debit"] - e["credit"], 2)
        e["balance"] = balance

    total_orders   = sum(e["debit"]  for e in entries)
    total_receipts = sum(e["credit"] for e in entries)
    outstanding    = round(total_orders - total_receipts, 2)

    return templates.TemplateResponse("dealers/ledger.html", {
        "request": request, "current_user": current_user,
        "dealer": dealer, "entries": entries,
        "total_orders": total_orders, "total_receipts": total_receipts,
        "outstanding": outstanding,
    })
