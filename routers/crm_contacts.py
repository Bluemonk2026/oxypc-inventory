"""CRM Contacts router — unified buyer/supplier registry."""
import csv
import io
import json
from datetime import datetime
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select, func, or_, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from templates_config import templates
from database import get_db
from utils.csv_decode import decode_csv_bytes
from utils.timezone import app_now
from services.audit_engine import audit
from auth.dependencies import get_current_user, verify_csrf, require_module_perm
from models.user import User, UserRole
from models.crm import (
    CRMContact, CRMContactNumber, CRMSourcingDeal, CRMSalesOpportunity,
    CRMActivity, CRMPurchaseOrder, SOURCE_TYPES, BUYER_TYPES,
)


def _parse_contact_numbers(form) -> list[tuple[str, str, str]]:
    """Extract (person_name, phone, email) rows from the repeating Contact
    Numbers section. Skips fully-blank rows. Used by create + update."""
    names = form.getlist("cn_person[]")
    phones = form.getlist("cn_phone[]")
    emails = form.getlist("cn_email[]")
    rows: list[tuple[str, str, str]] = []
    for i in range(max(len(names), len(phones), len(emails))):
        nm = (names[i] if i < len(names) else "").strip()
        ph = (phones[i] if i < len(phones) else "").strip()
        em = (emails[i] if i < len(emails) else "").strip()
        if nm or ph or em:
            rows.append((nm, ph, em))
    return rows

router = APIRouter(prefix="/crm/contacts", tags=["crm-contacts"], dependencies=[Depends(verify_csrf)])

CRM_ROLES = (
    UserRole.admin, UserRole.sales, UserRole.sales_manager,
    UserRole.telecaller, UserRole.inventory_manager,
)

# ── helpers ──────────────────────────────────────────────────────────────────

async def _next_code(db: AsyncSession) -> str:
    result = await db.execute(select(func.count(CRMContact.id)))
    n = (result.scalar() or 0) + 1
    return f"CRM{n:04d}"


# ── LIST ─────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def list_contacts(
    request: Request,
    q: str = Query(default=""),
    contact_type: str = Query(default=""),
    source_type: str = Query(default=""),
    buyer_type: str = Query(default=""),
    contacted: str = Query(default=""),        # "yes" | "no" | ""
    created_by_filter: str = Query(default=""),  # admin-only: filter by who added the contact
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Subquery of contact IDs that have at least one activity log
    has_activity_subq = select(CRMActivity.contact_id).distinct()

    # Distinct list of (username, full_name) for contacts creator dropdown — admin only
    crm_users: list[tuple[str, str]] = []
    if current_user.role == UserRole.admin:
        users_result = await db.execute(
            select(CRMContact.created_by, User.full_name)
            .join(User, CRMContact.created_by == User.username, isouter=True)
            .where(CRMContact.created_by.isnot(None))
            .distinct()
            .order_by(User.full_name, CRMContact.created_by)
        )
        crm_users = [(row[0], row[1] or row[0]) for row in users_result.all()]

    # Active (non-trashed) contacts with all filters applied
    query = select(CRMContact).where(CRMContact.is_trashed == False)
    if q:
        like = f"%{q}%"
        query = query.where(or_(
            CRMContact.company_name.ilike(like),
            CRMContact.contact_person.ilike(like),
            CRMContact.phone.ilike(like),
            CRMContact.city.ilike(like),
        ))
    if contact_type:
        query = query.where(CRMContact.contact_type == contact_type)
    if source_type:
        query = query.where(CRMContact.source_type == source_type)
    if buyer_type:
        query = query.where(CRMContact.buyer_type == buyer_type)
    if contacted == "yes":
        query = query.where(CRMContact.id.in_(has_activity_subq))
    elif contacted == "no":
        query = query.where(CRMContact.id.notin_(has_activity_subq))
    # Admin-only: filter by the user who created the contact
    if created_by_filter and current_user.role == UserRole.admin:
        query = query.where(CRMContact.created_by == created_by_filter)

    result = await db.execute(query.order_by(CRMContact.company_name))
    contacts = result.scalars().all()

    # Trashed contacts (always full list, no filters)
    trashed_result = await db.execute(
        select(CRMContact).where(CRMContact.is_trashed == True).order_by(CRMContact.company_name)
    )
    trashed_contacts = trashed_result.scalars().all()

    # Most-recent activity per contact — drives "Contacted/Not Yet" pill + Last Outcome column
    all_ids = [c.id for c in contacts] + [c.id for c in trashed_contacts]
    # activity_map: str(contact_id) -> {"outcome": str, "date": datetime|None}
    activity_map: dict = {}
    if all_ids:
        rn_col = func.row_number().over(
            partition_by=CRMActivity.contact_id,
            order_by=CRMActivity.activity_date.desc()
        ).label("rn")
        act_inner = select(
            CRMActivity.contact_id,
            CRMActivity.outcome,
            CRMActivity.activity_date,
            rn_col,
        ).where(CRMActivity.contact_id.in_(all_ids)).subquery()
        act_rows = (await db.execute(
            select(act_inner.c.contact_id, act_inner.c.outcome, act_inner.c.activity_date)
            .where(act_inner.c.rn == 1)
        )).all()
        activity_map = {
            str(r.contact_id): {
                "outcome": r.outcome or "",
                "date":    r.activity_date,
            }
            for r in act_rows
        }

    contacted_set = set(activity_map.keys())   # contact IDs that have ≥1 activity

    # Contact-numbers count + tooltip data per contact (one grouped query, no N+1).
    # numbers_map: str(contact_id) -> list[(person_name, phone)]
    # numbers_map: str(contact_id) -> list[{name, phone, email}]
    numbers_map: dict = {}
    if all_ids:
        num_rows = (await db.execute(
            select(CRMContactNumber.contact_id,
                   CRMContactNumber.person_name,
                   CRMContactNumber.phone,
                   CRMContactNumber.email)
            .where(CRMContactNumber.contact_id.in_(all_ids))
            .order_by(CRMContactNumber.contact_id, CRMContactNumber.sort_order)
        )).all()
        for r in num_rows:
            numbers_map.setdefault(str(r.contact_id), []).append({
                "name": r.person_name or "",
                "phone": r.phone or "",
                "email": r.email or "",
            })

    counts = {
        "total":     len(contacts),
        "suppliers": sum(1 for c in contacts if c.contact_type in ("supplier", "both")),
        "buyers":    sum(1 for c in contacts if c.contact_type in ("buyer", "both")),
        "active":    sum(1 for c in contacts if c.status == "active"),
    }

    return templates.TemplateResponse("crm/contacts/list.html", {
        "request": request, "current_user": current_user,
        "contacts": contacts, "counts": counts,
        "trashed_contacts": trashed_contacts,
        "activity_map": activity_map,
        "numbers_map": numbers_map,
        "contacted_set": contacted_set,
        "q": q, "contact_type": contact_type,
        "source_type": source_type, "buyer_type": buyer_type,
        "contacted": contacted,
        "created_by_filter": created_by_filter,
        "crm_users": crm_users,
        "source_types": SOURCE_TYPES, "buyer_types": BUYER_TYPES,
    })


# ── BULK UPLOAD (simple direct import) ───────────────────────────────────────

@router.get("/upload", response_class=HTMLResponse)
async def upload_contacts_form(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse("crm/contacts/upload.html", {
        "request": request, "current_user": current_user,
        "result": None, "error": None,
    })


@router.post("/upload")
async def upload_contacts_csv(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not (file.filename or "").lower().endswith(".csv"):
        return templates.TemplateResponse("crm/contacts/upload.html", {
            "request": request, "current_user": current_user,
            "result": None, "error": "Please upload a .csv file",
        })

    content = await file.read()
    try:
        text_content = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text_content = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text_content))
    fieldnames_lower = {(c or "").strip().lower() for c in (reader.fieldnames or [])}
    if "company_name" not in fieldnames_lower:
        return templates.TemplateResponse("crm/contacts/upload.html", {
            "request": request, "current_user": current_user,
            "result": None,
            "error": "CSV must contain at least a 'company_name' column",
        })

    _valid_contact_types = {"supplier", "buyer", "both"}
    _valid_source_types  = {v for v, _ in SOURCE_TYPES} | {""}
    _valid_buyer_types   = {v for v, _ in BUYER_TYPES}  | {""}
    _valid_statuses      = {"active", "inactive", "blacklisted"}

    created, skipped, errors = 0, 0, []

    for i, row in enumerate(reader, start=2):
        company = (row.get("company_name") or "").strip()
        if not company:
            skipped += 1
            continue

        phone = (row.get("phone") or "").strip() or None

        # Skip duplicates (match on company_name + phone)
        existing = (await db.execute(
            select(CRMContact).where(
                CRMContact.company_name == company,
                CRMContact.phone == phone,
            )
        )).scalars().first()
        if existing:
            skipped += 1
            continue

        contact_type = (row.get("contact_type") or "buyer").strip()
        if contact_type not in _valid_contact_types:
            contact_type = "buyer"

        source_type = (row.get("source_type") or "").strip() or None
        if source_type and source_type not in _valid_source_types:
            source_type = None

        buyer_type = (row.get("buyer_type") or "").strip() or None
        if buyer_type and buyer_type not in _valid_buyer_types:
            buyer_type = None

        status = (row.get("status") or "active").strip()
        if status not in _valid_statuses:
            status = "active"

        try:
            code = await _next_code(db)
            db.add(CRMContact(
                contact_code=code,
                company_name=company,
                contact_person=(row.get("contact_person") or "").strip() or None,
                phone=phone,
                whatsapp=(row.get("whatsapp") or "").strip() or None,
                email=(row.get("email") or "").strip() or None,
                contact_type=contact_type,
                source_type=source_type,
                buyer_type=buyer_type,
                city=(row.get("city") or "").strip() or None,
                state=(row.get("state") or "").strip() or None,
                gstin=(row.get("gstin") or "").strip() or None,
                tags=(row.get("tags") or "").strip() or None,
                notes=(row.get("notes") or "").strip() or None,
                status=status,
                created_by=current_user.username,
            ))
            await db.flush()
            created += 1
        except Exception as e:
            await db.rollback()
            errors.append(f"Row {i}: {str(e)[:100]}")

    await db.commit()

    return templates.TemplateResponse("crm/contacts/upload.html", {
        "request": request, "current_user": current_user,
        "result": {"created": created, "skipped": skipped, "errors": errors},
        "error": None,
    })


# ── IMPORT CSV ────────────────────────────────────────────────────────────────

@router.get("/import-csv", response_class=HTMLResponse)
async def import_csv_form(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse("crm/contacts/import.html", {
        "request": request, "current_user": current_user,
        "preview": None, "errors": None,
    })


@router.post("/import-csv", response_class=HTMLResponse)
async def import_csv_preview(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        return templates.TemplateResponse("crm/contacts/import.html", {
            "request": request, "current_user": current_user,
            "preview": None, "errors": ["File too large. Maximum allowed size is 2 MB."],
        })
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    rows = list(reader)
    if len(rows) > 500:
        return templates.TemplateResponse("crm/contacts/import.html", {
            "request": request, "current_user": current_user,
            "preview": None, "errors": [f"Too many rows ({len(rows)}). Maximum 500 rows per import."],
        })
    errors = []
    preview = []
    for i, row in enumerate(rows, 1):
        company = (row.get("company_name") or "").strip()
        phone   = (row.get("phone") or "").strip()
        if not company:
            errors.append(f"Row {i}: company_name is required")
            continue
        dup = None
        if phone:
            r = await db.execute(select(CRMContact).where(CRMContact.phone == phone))
            dup = r.scalar_one_or_none()
        preview.append({
            "row": i,
            "company_name": company,
            "contact_person": (row.get("contact_person") or "").strip(),
            "phone": phone,
            "whatsapp": (row.get("whatsapp") or "").strip(),
            "email": (row.get("email") or "").strip(),
            "contact_type": (row.get("contact_type") or "supplier").strip(),
            "source_type": (row.get("source_type") or "").strip(),
            "buyer_type": (row.get("buyer_type") or "").strip(),
            "city": (row.get("city") or "").strip(),
            "state": (row.get("state") or "").strip(),
            "gstin": (row.get("gstin") or "").strip(),
            "tags": (row.get("tags") or "").strip(),
            "duplicate": dup.company_name if dup else None,
        })
    preview_json = json.dumps(preview)
    return templates.TemplateResponse("crm/contacts/import.html", {
        "request": request, "current_user": current_user,
        "preview": preview, "errors": errors,
        "preview_json": preview_json,
    })


@router.post("/import-confirm")
async def import_csv_confirm(
    request: Request,
    preview_data: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        rows = json.loads(preview_data)
        if not isinstance(rows, list):
            raise ValueError("invalid payload")
    except (ValueError, TypeError):
        return RedirectResponse(url="/crm/contacts?error=Invalid+import+data", status_code=302)

    _valid_contact_types = {"supplier", "buyer", "both"}
    _valid_source_types  = {v for v, _ in SOURCE_TYPES} | {""}
    _valid_buyer_types   = {v for v, _ in BUYER_TYPES}  | {""}

    imported = 0
    skipped = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("duplicate"):
            skipped += 1
            continue
        company = (row.get("company_name") or "").strip()
        if not company:
            continue
        contact_type = (row.get("contact_type") or "supplier").strip()
        if contact_type not in _valid_contact_types:
            contact_type = "supplier"
        source_type = (row.get("source_type") or "").strip()
        if source_type not in _valid_source_types:
            source_type = None
        buyer_type = (row.get("buyer_type") or "").strip()
        if buyer_type not in _valid_buyer_types:
            buyer_type = None
        code = await _next_code(db)
        c = CRMContact(
            contact_code=code,
            company_name=company,
            contact_person=(row.get("contact_person") or "").strip() or None,
            phone=(row.get("phone") or "").strip() or None,
            whatsapp=(row.get("whatsapp") or "").strip() or None,
            email=(row.get("email") or "").strip() or None,
            contact_type=contact_type,
            source_type=source_type or None,
            buyer_type=buyer_type or None,
            city=(row.get("city") or "").strip() or None,
            state=(row.get("state") or "").strip() or None,
            gstin=(row.get("gstin") or "").strip() or None,
            tags=(row.get("tags") or "").strip() or None,
            created_by=current_user.username,
        )
        db.add(c)
        imported += 1
    await db.commit()
    return RedirectResponse(
        url=f"/crm/contacts?success=Imported+{imported}+contacts,+{skipped}+skipped+(duplicates)",
        status_code=302,
    )


# ── EXPORT CSV ────────────────────────────────────────────────────────────────

@router.get("/export-csv")
async def export_contacts_csv(
    request: Request,
    q: str = Query(default=""),
    contact_type: str = Query(default=""),
    source_type: str = Query(default=""),
    buyer_type: str = Query(default=""),
    contacted: str = Query(default=""),
    created_by_filter: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export filtered contacts as CSV — admin only."""
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin only")

    # Same filter logic as list_contacts
    from models.crm import CRMActivity
    has_activity_subq = select(CRMActivity.contact_id).distinct()
    query = select(CRMContact).where(CRMContact.is_trashed == False)
    if q:
        like = f"%{q}%"
        query = query.where(or_(
            CRMContact.company_name.ilike(like),
            CRMContact.contact_person.ilike(like),
            CRMContact.phone.ilike(like),
            CRMContact.city.ilike(like),
        ))
    if contact_type:
        query = query.where(CRMContact.contact_type == contact_type)
    if source_type:
        query = query.where(CRMContact.source_type == source_type)
    if buyer_type:
        query = query.where(CRMContact.buyer_type == buyer_type)
    if contacted == "yes":
        query = query.where(CRMContact.id.in_(has_activity_subq))
    elif contacted == "no":
        query = query.where(CRMContact.id.notin_(has_activity_subq))
    if created_by_filter:
        query = query.where(CRMContact.created_by == created_by_filter)

    result = await db.execute(query.order_by(CRMContact.company_name))
    contacts = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Contact Code", "Type", "Company Name", "Contact Person",
        "Phone", "WhatsApp", "Email", "GSTIN", "City", "State",
        "Source Type", "Buyer Type", "Status", "Tags",
        "Credit Limit", "Outstanding", "Assigned To", "Created By", "Created At",
    ])
    for c in contacts:
        writer.writerow([
            c.contact_code, c.contact_type, c.company_name, c.contact_person or "",
            c.phone or "", c.whatsapp or "", c.email or "", c.gstin or "",
            c.city or "", c.state or "",
            c.source_type or "", c.buyer_type or "", c.status,
            c.tags or "", float(c.credit_limit or 0), float(c.outstanding or 0),
            c.assigned_to or "", c.created_by or "",
            c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else "",
        ])
    csv_bytes = output.getvalue().encode("utf-8-sig")
    from utils.timezone import app_now
    filename = f"crm-contacts-{app_now().strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── ACCOUNTS BULK UPLOAD (accounts + call records in one sheet) ───────────────
#
# Registered ABOVE the "/{contact_id}" route on purpose: that path parameter
# matches any single segment, so a template route declared after it would be
# swallowed and "/crm/contacts/calls" would be looked up as a contact id.

@router.get("/calls/bulk-upload-template")
async def account_calls_bulk_upload_template(
    current_user: User = Depends(get_current_user),
):
    """Sample CSV for the Accounts bulk upload.

    Auth-guarded to match the upload endpoint it feeds. The rows are fictional,
    but a public endpoint still hands out the module's exact field names to
    anyone who asks, and only signed-in staff have any use for it.

    Row 1 is a full account + a call. Row 2 is account detail only (no call
    columns) — that is the supported way to import or update accounts without
    manufacturing a call record for each one.
    """
    header = (
        "company_name,contact_person,phone,whatsapp,email,gstin,address,city,state,pincode,"
        "contact_type,source_type,buyer_type,assigned_to,"
        "call_date,call_type,call_mode,call_outcome,summary,items_discussed,"
        "next_followup_date,notes\n"
    )
    sample = (
        "Example Traders,Ravi Kumar,9876543210,9876543210,ravi@example.com,"
        "07AABCU9603R1ZM,12 Nehru Place,New Delhi,Delhi,110019,"
        "buyer,trader,dealer,sales_user,"
        "2026-07-15,outbound,phone,interested,Discussed i5 8th gen stock,"
        "i5 8th Gen laptops,2026-07-22,Wants 20 units\n"
        "ABC Electronics,Sunita Rao,9812345678,,sunita@abc.com,,,Mumbai,Maharashtra,,"
        "buyer,,retail,,,,,,,,,\n"
    )
    return StreamingResponse(
        iter([(header + sample).encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition":
                 "attachment; filename=accounts_bulk_upload_template.csv"},
    )


@router.post("/calls/bulk-upload", response_class=HTMLResponse)
async def account_calls_bulk_upload(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One uploader covering all five cases the operator asked for:

      1. update an existing Account and log a call
      2. update an existing Account with no call columns filled
      3. create a new Account and log a call
      4. create a new Account with no call columns filled
      5. plain account sheets, so the separate Bulk Upload CSV button is
         redundant — its column names are accepted here unchanged

    Mirrors the dealer call-records uploader (routers/dealers.py) deliberately:
    same header aliasing, same "one bad row never aborts the file" contract,
    same set-based lookup instead of a query per row.
    """
    form = await request.form()
    upload = form.get("file")
    if not upload or not hasattr(upload, "read"):
        return RedirectResponse(url="/crm/contacts?error=No+file+uploaded",
                                status_code=302)

    text_content = decode_csv_bytes(await upload.read())
    text_content = text_content.replace("\r\n", "\n").replace("\r", "\n").strip()

    def _norm(s) -> str:
        if not s or not isinstance(s, str):
            return ""
        return s.lower().strip().replace(" ", "_").replace("-", "_")

    # Accepts the headers of the existing Bulk Upload CSV template as well as
    # the natural spellings a telecaller's own sheet uses.
    _ALIASES = {
        "account":        "company_name", "account_name":  "company_name",
        "company":        "company_name", "business_name": "company_name",
        "firm_name":      "company_name", "dealer_name":   "company_name",
        "contact":        "contact_person", "person_name": "contact_person",
        "owner_name":     "contact_person", "contact_name": "contact_person",
        "mobile":         "phone",        "mobile_number": "phone",
        "phone_number":   "phone",        "contact_no":    "phone",
        "whatsapp_number": "whatsapp",
        "email_id":       "email",        "mail":          "email",
        "gst":            "gstin",        "gst_no":        "gstin",
        "gst_number":     "gstin",
        "pin":            "pincode",      "pin_code":      "pincode",
        "type":           "contact_type",
        "assigned":       "assigned_to",  "sales_person":  "assigned_to",
        "date":           "call_date",    "called_on":     "call_date",
        "mode":           "call_mode",
        "outcome":        "call_outcome",
        "remark":         "notes",        "remarks":       "notes",
        "discussion":     "summary",      "call_summary":  "summary",
        "followup_date":  "next_followup_date",
        "next_followup":  "next_followup_date",
    }

    # csv key -> CRMContact attribute. Only non-blank values are applied, so a
    # sparse sheet never blanks out detail already on the account.
    _ACCOUNT_COLS = {
        "company_name": "company_name", "contact_person": "contact_person",
        "phone": "phone", "whatsapp": "whatsapp", "email": "email",
        "gstin": "gstin", "pan": "pan", "address": "address",
        "city": "city", "state": "state", "pincode": "pincode",
        "contact_type": "contact_type", "source_type": "source_type",
        "buyer_type": "buyer_type", "assigned_to": "assigned_to",
        "notes": "notes",
    }

    # A row is a CALL only if it carries one of these. Without this test, a
    # plain account list would manufacture one blank activity per account and
    # inflate every call count on the CRM dashboard.
    _CALL_COLS = (
        "call_date", "call_type", "call_mode", "call_outcome", "summary",
        "items_discussed", "next_followup_date",
    )

    reader = csv.DictReader(io.StringIO(text_content))
    raw_fields = reader.fieldnames or []
    reader.fieldnames = [_ALIASES.get(_norm(h), _norm(h)) for h in raw_fields]
    rows = [
        {k: (str(v).strip() if v is not None else "") for k, v in r.items() if k}
        for r in reader
    ]
    if not rows:
        return RedirectResponse(url="/crm/contacts?error=No+rows+found+in+file",
                                status_code=302)

    # Two set-based lookups rather than one query per row.
    want_phones = {r.get("phone", "") for r in rows if r.get("phone", "")}
    want_names = {r.get("company_name", "").lower()
                  for r in rows if r.get("company_name", "")}

    by_phone: dict = {}
    by_name: dict = {}
    if want_phones:
        res = await db.execute(select(CRMContact).where(
            CRMContact.phone.in_(want_phones), CRMContact.is_trashed == False))  # noqa: E712
        by_phone = {c.phone: c for c in res.scalars().all()}
    if want_names:
        res = await db.execute(select(CRMContact).where(
            func.lower(CRMContact.company_name).in_(want_names),
            CRMContact.is_trashed == False))  # noqa: E712
        by_name = {(c.company_name or "").strip().lower(): c
                   for c in res.scalars().all()}

    def _to_date(val: str):
        if not val:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
        raise ValueError(f"unrecognised date '{val}'")

    valid_dirs = {"outbound", "inbound"}
    valid_modes = {"call", "whatsapp", "visit", "email", "meeting", "note"}

    logged, errors = 0, []
    created_accounts, updated_accounts = 0, 0
    code_base = ((await db.execute(select(func.count(CRMContact.id)))).scalar() or 0) + 1
    new_seq = 0

    for i, row in enumerate(rows, start=2):   # row 1 = header
        try:
            phone = row.get("phone", "")
            name = row.get("company_name", "")

            contact = by_phone.get(phone) if phone else None
            if contact is None and name:
                contact = by_name.get(name.lower())

            if contact is None:
                if not (phone or name):
                    errors.append(f"Row {i}: needs a company_name or a phone")
                    continue
                new_seq += 1
                contact = CRMContact(
                    contact_code=f"CRM{code_base + new_seq - 1:04d}",
                    company_name=name or phone,
                    contact_type=(row.get("contact_type", "") or "buyer"),
                    status="active",
                    created_by=current_user.username,
                )
                for col, attr in _ACCOUNT_COLS.items():
                    val = row.get(col, "")
                    if val:
                        setattr(contact, attr, val)
                db.add(contact)
                # flush so contact.id exists for the CRMActivity FK, and so a
                # later row for the same account reuses this one rather than
                # creating a second copy from within the same file.
                await db.flush()
                if phone:
                    by_phone[phone] = contact
                if name:
                    by_name[name.lower()] = contact
                created_accounts += 1
            else:
                changed = False
                for col, attr in _ACCOUNT_COLS.items():
                    val = row.get(col, "")
                    if val and (getattr(contact, attr, None) or "") != val:
                        setattr(contact, attr, val)
                        changed = True
                if changed:
                    updated_accounts += 1

            if not any(row.get(c, "") for c in _CALL_COLS):
                continue   # account-detail-only row: cases 2 and 4

            direction = (row.get("call_type", "").lower() or "outbound")
            if direction not in valid_dirs:
                direction = "outbound"
            mode = (row.get("call_mode", "").lower() or "call")
            if mode == "phone":          # dealer sheets spell it this way
                mode = "call"
            if mode == "in_person":
                mode = "visit"
            if mode not in valid_modes:
                mode = "call"

            # summary is NOT NULL on crm_activities. Fall back through the
            # columns most likely to carry the gist before giving up, so a row
            # that plainly is a call is never rejected over a blank cell.
            summary = (row.get("summary", "") or row.get("items_discussed", "")
                       or row.get("notes", "")
                       or f"{mode} on {row.get('call_date', '') or 'unspecified date'}")

            # performed_by is the rep the row names, not whoever ran the upload
            # — crediting the uploader would pile the whole file onto one
            # account and hide each call from the rep who actually made it.
            row_agent = row.get("assigned_to", "")
            db.add(CRMActivity(
                contact_id=contact.id,
                activity_type=mode,
                direction=direction,
                summary=summary,
                outcome=row.get("call_outcome", "").lower() or None,
                performed_by=row_agent or current_user.username,
                activity_date=_to_date(row.get("call_date", "")) or app_now(),
                next_followup=_to_date(row.get("next_followup_date", "")),
                followup_assigned_to=row_agent or None,
            ))
            logged += 1
        except Exception as exc:
            errors.append(f"Row {i}: {exc}")

    await audit(db, action="CRM_ACCOUNT_BULK_UPLOAD", user=current_user,
                table_name="crm_contacts", record_id="bulk",
                new_value={"created_accounts": created_accounts,
                           "updated_accounts": updated_accounts,
                           "calls_logged": logged,
                           "skipped": len(errors), "rows": len(rows)})
    await db.commit()

    return templates.TemplateResponse("bulk_upload/result.html", {
        "request": request, "current_user": current_user,
        "upload_type": " · ".join(
            ["Accounts"]
            + ([f"{created_accounts} account(s) created"] if created_accounts else [])
            + ([f"{updated_accounts} account(s) updated"] if updated_accounts else [])
            + ([f"{logged} call(s) logged"] if logged else [])),
        "inserted": created_accounts + updated_accounts + logged,
        "errors": errors,
        "back_url": "/crm/contacts",
    })


# ── NEW ───────────────────────────────────────────────────────────────────────

@router.get("/new", response_class=HTMLResponse)
async def new_contact_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse("crm/contacts/form.html", {
        "request": request, "current_user": current_user,
        "contact": None, "contact_numbers": [],
        "source_types": SOURCE_TYPES, "buyer_types": BUYER_TYPES,
    })


@router.post("/new")
async def create_contact(
    request: Request,
    contact_type:   str = Form(default="supplier"),
    company_name:   str = Form(...),
    email:          str = Form(default=None),
    gstin:          str = Form(default=None),
    pan:            str = Form(default=None),
    address:        str = Form(default=None),
    city:           str = Form(default=None),
    state:          str = Form(default=None),
    pincode:        str = Form(default=None),
    source_type:    str = Form(default=None),
    buyer_type:     str = Form(default=None),
    credit_limit:   float = Form(default=0),
    tags:           str = Form(default=None),
    notes:          str = Form(default=None),
    status:         str = Form(default="active"),
    assigned_to:    str = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _perm: User = Depends(require_module_perm("crm_contacts", "add")),
):
    # Contact person / phone / whatsapp now live per-person in Contact Numbers.
    number_rows = _parse_contact_numbers(await request.form())
    for _attempt in range(3):
        code = await _next_code(db)
        contact = CRMContact(
            contact_code=code, contact_type=contact_type,
            company_name=company_name,
            email=email or None, gstin=gstin or None, pan=pan or None,
            address=address or None, city=city or None,
            state=state or None, pincode=pincode or None,
            source_type=source_type or None, buyer_type=buyer_type or None,
            credit_limit=credit_limit,
            tags=tags or None, notes=notes or None, status=status,
            assigned_to=assigned_to or current_user.username,
            created_by=current_user.username,
        )
        db.add(contact)
        try:
            await db.flush()   # assigns contact.id; raises on duplicate code
        except IntegrityError:
            await db.rollback()
            continue
        for i, (nm, ph, em) in enumerate(number_rows):
            db.add(CRMContactNumber(
                contact_id=contact.id, person_name=nm or None,
                phone=ph or None, email=em or None, sort_order=i,
            ))
        await db.commit()
        return RedirectResponse(url=f"/crm/contacts/{contact.id}?success=Contact+created", status_code=302)
    return RedirectResponse(url="/crm/contacts?error=Failed+to+generate+unique+contact+code,+please+retry", status_code=302)


# ── PROFILE ───────────────────────────────────────────────────────────────────

@router.get("/{contact_id}", response_class=HTMLResponse)
async def contact_profile(
    request: Request,
    contact_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMContact).where(CRMContact.id == contact_id))
    contact = result.scalar_one_or_none()
    if not contact:
        return RedirectResponse(url="/crm/contacts?error=Contact+not+found", status_code=302)

    acts_r = await db.execute(
        select(CRMActivity)
        .where(CRMActivity.contact_id == contact.id)
        .order_by(CRMActivity.activity_date.desc()).limit(20)
    )
    activities = acts_r.scalars().all()

    deals_r = await db.execute(
        select(CRMSourcingDeal)
        .where(CRMSourcingDeal.contact_id == contact.id)
        .order_by(CRMSourcingDeal.created_at.desc())
    )
    sourcing_deals = deals_r.scalars().all()

    opps_r = await db.execute(
        select(CRMSalesOpportunity)
        .where(CRMSalesOpportunity.contact_id == contact.id)
        .order_by(CRMSalesOpportunity.created_at.desc())
    )
    sales_opps = opps_r.scalars().all()

    # ── Trade Partner bids for this Account ─────────────────────────────────
    # Portal logins hang off Dealer rows, which link back here via
    # crm_contact_id. One Account can have several dealer logins, so collect
    # them all before querying bids.
    from models.dealers import Dealer
    from models.partner import PartnerBid
    from models.lot import Lot

    dealer_ids = [d for (d,) in (await db.execute(
        select(Dealer.id).where(Dealer.crm_contact_id == contact.id)
    )).all()]

    lost_bids, won_bid_lots = [], {}
    if dealer_ids:
        bids = (await db.execute(
            select(PartnerBid).where(
                PartnerBid.dealer_id.in_(dealer_ids),
                PartnerBid.status.in_(("lost", "won")),
            ).order_by(PartnerBid.bid_amount.desc())
        )).scalars().all()

        lot_ids = {b.lot_id for b in bids if b.lot_id}
        lots = {}
        if lot_ids:
            lots = {l.id: l for l in (await db.execute(
                select(Lot).where(Lot.id.in_(lot_ids)))).scalars().all()}

        for b in bids:
            lot = lots.get(b.lot_id) if b.lot_id else None
            if b.status == "lost":
                base = b.base_amount
                lost_bids.append({
                    "bid": b,
                    "lot_id": str(lot.id) if lot else None,
                    "lot_number": lot.lot_number if lot else "—",
                    "shortfall": (b.bid_amount - base) if base else None,
                })
            elif b.opportunity_id and lot:
                # Lets the Sales Opportunities table link the lot a won bid
                # produced — the opportunity itself has no lot FK, only a title.
                won_bid_lots[str(b.opportunity_id)] = {
                    "lot_id": str(lot.id), "lot_number": lot.lot_number,
                }

    # Purchase Deals — POs where this contact is the supplier (eager-load .contact
    # so the shared partial can show the supplier name without an async lazy load).
    pos_r = await db.execute(
        select(CRMPurchaseOrder)
        .options(selectinload(CRMPurchaseOrder.contact))
        .where(CRMPurchaseOrder.contact_id == contact.id)
        .order_by(CRMPurchaseOrder.created_at.desc())
    )
    purchase_orders = pos_r.scalars().all()

    # ── Quotes Generated ─────────────────────────────────────────────────────
    # Every quote raised for this Account, summarised by its line items. The
    # Opportunity number comes from the Buyer Deal that points at the quote —
    # a quote written straight from the Account has none, so it shows "—".
    from models.crm import CRMQuote
    from routers.crm_quotes import quote_summary_rows, active_terms_by_type
    from services.opportunity_lot import lots_won_by_contact

    quotes = (await db.execute(
        select(CRMQuote).where(CRMQuote.contact_id == contact.id)
        .order_by(CRMQuote.created_at.desc())
    )).scalars().all()
    quote_rows = await quote_summary_rows(db, quotes)
    terms_by_type = await active_terms_by_type(db)
    # Lots this Account won at auction — the "Quote for Bid Won" picker.
    won_lots = await lots_won_by_contact(db, contact.id)

    source_map = dict(SOURCE_TYPES)
    buyer_map  = dict(BUYER_TYPES)

    # ── Scorecard stats ───────────────────────────────────────────────────────
    scorecard = {
        "total_deals":   len(sourcing_deals),
        "won_deals":     sum(1 for d in sourcing_deals if d.stage == "won"),
        "lost_deals":    sum(1 for d in sourcing_deals if d.stage == "lost"),
        "open_deals":    sum(1 for d in sourcing_deals if d.stage not in ("won", "lost")),
        "pipeline_value": sum(float(d.our_offer_total or d.asking_price_total or 0)
                              for d in sourcing_deals if d.stage not in ("won", "lost")),
        "won_value":     sum(float(d.final_price_total or d.our_offer_total or 0)
                              for d in sourcing_deals if d.stage == "won"),
        "total_opps":    len(sales_opps),
        "won_opps":      sum(1 for o in sales_opps if o.stage == "won"),
        "open_opps":     sum(1 for o in sales_opps if o.stage not in ("won", "lost")),
        "total_activities": 0,  # filled below
        "call_count":    sum(1 for a in activities if a.activity_type == "call"),
        "whatsapp_count":sum(1 for a in activities if a.activity_type == "whatsapp"),
        "visit_count":   sum(1 for a in activities if a.activity_type == "visit"),
    }
    # total activity count (not limited to 20)
    act_count_r = await db.execute(
        select(func.count(CRMActivity.id)).where(CRMActivity.contact_id == contact.id)
    )
    scorecard["total_activities"] = act_count_r.scalar() or 0
    scorecard["win_rate"] = (
        round(scorecard["won_deals"] / scorecard["total_deals"] * 100)
        if scorecard["total_deals"] > 0 else None
    )

    return templates.TemplateResponse("crm/contacts/profile.html", {
        "request": request, "current_user": current_user,
        "contact": contact, "activities": activities,
        "sourcing_deals": sourcing_deals, "sales_opps": sales_opps,
        "lost_bids": lost_bids, "won_bid_lots": won_bid_lots,
        "purchase_orders": purchase_orders,
        "quote_rows": quote_rows, "terms_by_type": terms_by_type,
        "won_lots": won_lots,
        "source_map": source_map, "buyer_map": buyer_map,
        "scorecard": scorecard,
    })


# ── EDIT ─────────────────────────────────────────────────────────────────────

@router.get("/{contact_id}/edit", response_class=HTMLResponse)
async def edit_contact_form(
    request: Request,
    contact_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMContact).where(CRMContact.id == contact_id))
    contact = result.scalar_one_or_none()
    if not contact:
        return RedirectResponse(url="/crm/contacts?error=Not+found", status_code=302)
    nums_r = await db.execute(
        select(CRMContactNumber)
        .where(CRMContactNumber.contact_id == contact.id)
        .order_by(CRMContactNumber.sort_order)
    )
    contact_numbers = nums_r.scalars().all()
    return templates.TemplateResponse("crm/contacts/form.html", {
        "request": request, "current_user": current_user,
        "contact": contact, "contact_numbers": contact_numbers,
        "source_types": SOURCE_TYPES, "buyer_types": BUYER_TYPES,
    })


@router.post("/{contact_id}/edit")
async def update_contact(
    request: Request,
    contact_id: str,
    contact_type:   str = Form(default="supplier"),
    company_name:   str = Form(...),
    email:          str = Form(default=None),
    gstin:          str = Form(default=None),
    pan:            str = Form(default=None),
    address:        str = Form(default=None),
    city:           str = Form(default=None),
    state:          str = Form(default=None),
    pincode:        str = Form(default=None),
    source_type:    str = Form(default=None),
    buyer_type:     str = Form(default=None),
    credit_limit:   float = Form(default=0),
    tags:           str = Form(default=None),
    notes:          str = Form(default=None),
    status:         str = Form(default="active"),
    assigned_to:    str = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMContact).where(CRMContact.id == contact_id))
    contact = result.scalar_one_or_none()
    if not contact:
        return RedirectResponse(url="/crm/contacts?error=Not+found", status_code=302)

    contact.contact_type = contact_type
    contact.company_name = company_name
    contact.email = email or None
    # contact_person / phone / whatsapp are no longer on the form (they live in
    # Contact Numbers now) — existing DB values are left untouched, not wiped.
    contact.gstin = gstin or None
    contact.pan = pan or None
    contact.address = address or None
    contact.city = city or None
    contact.state = state or None
    contact.pincode = pincode or None
    contact.source_type = source_type or None
    contact.buyer_type = buyer_type or None
    contact.credit_limit = credit_limit
    contact.tags = tags or None
    contact.notes = notes or None
    contact.status = status
    contact.assigned_to = assigned_to

    # Replace the Contact Numbers child rows with whatever the form submitted.
    number_rows = _parse_contact_numbers(await request.form())
    await db.execute(delete(CRMContactNumber).where(CRMContactNumber.contact_id == contact.id))
    for i, (nm, ph, em) in enumerate(number_rows):
        db.add(CRMContactNumber(
            contact_id=contact.id, person_name=nm or None,
            phone=ph or None, email=em or None, sort_order=i,
        ))
    await db.commit()
    return RedirectResponse(url=f"/crm/contacts/{contact_id}?success=Contact+updated", status_code=302)


# ── TRASH / RESTORE ───────────────────────────────────────────────────────────

@router.post("/{contact_id}/trash")
async def trash_contact(
    contact_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMContact).where(CRMContact.id == contact_id))
    contact = result.scalar_one_or_none()
    if contact:
        contact.is_trashed = True
        await db.commit()
    return RedirectResponse(url="/crm/contacts?success=Contact+moved+to+trash", status_code=302)


@router.post("/{contact_id}/restore")
async def restore_contact(
    contact_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(CRMContact).where(CRMContact.id == contact_id))
    contact = result.scalar_one_or_none()
    if contact:
        contact.is_trashed = False
        await db.commit()
    return RedirectResponse(url="/crm/contacts?success=Contact+restored", status_code=302)
