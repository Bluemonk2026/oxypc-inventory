"""CRM Contacts router — unified buyer/supplier registry."""
import csv
import io
import json
from datetime import datetime
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user, verify_csrf, require_module_perm
from models.user import User, UserRole
from models.crm import (
    CRMContact, CRMSourcingDeal, CRMSalesOpportunity, CRMActivity,
    SOURCE_TYPES, BUYER_TYPES,
)

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


# ── NEW ───────────────────────────────────────────────────────────────────────

@router.get("/new", response_class=HTMLResponse)
async def new_contact_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse("crm/contacts/form.html", {
        "request": request, "current_user": current_user,
        "contact": None,
        "source_types": SOURCE_TYPES, "buyer_types": BUYER_TYPES,
    })


@router.post("/new")
async def create_contact(
    request: Request,
    contact_type:   str = Form(default="supplier"),
    company_name:   str = Form(...),
    contact_person: str = Form(default=None),
    phone:          str = Form(default=None),
    whatsapp:       str = Form(default=None),
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
    for _attempt in range(3):
        code = await _next_code(db)
        contact = CRMContact(
            contact_code=code, contact_type=contact_type,
            company_name=company_name, contact_person=contact_person or None,
            phone=phone or None, whatsapp=whatsapp or None,
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
            await db.commit()
            return RedirectResponse(url=f"/crm/contacts/{contact.id}?success=Contact+created", status_code=302)
        except IntegrityError:
            await db.rollback()
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
    return templates.TemplateResponse("crm/contacts/form.html", {
        "request": request, "current_user": current_user,
        "contact": contact,
        "source_types": SOURCE_TYPES, "buyer_types": BUYER_TYPES,
    })


@router.post("/{contact_id}/edit")
async def update_contact(
    request: Request,
    contact_id: str,
    contact_type:   str = Form(default="supplier"),
    company_name:   str = Form(...),
    contact_person: str = Form(default=None),
    phone:          str = Form(default=None),
    whatsapp:       str = Form(default=None),
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
    contact.contact_person = contact_person or None
    contact.phone = phone or None
    contact.whatsapp = whatsapp or None
    contact.email = email or None
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
