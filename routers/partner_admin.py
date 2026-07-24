"""Trade Partner — internal admin screens (/trade-partner).

Staff-facing: partner account provisioning, listings manager, bookings queue,
settings, floors, My Desk. Guarded by staff JWT + the trade_partner module
permission. Payment verification stays finance/admin-gated.
"""
import json
import os
import secrets
import string
import uuid as uuid_mod
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func

from database import get_db
from templates_config import templates
from models.dealers import Dealer
from models.crm import CRMContact
from models.user import User, UserRole
from models.lot import Lot
from models.device import Device, DeviceStage
from models.partner import (
    PartnerLoginLog, PartnerListing, PartnerListingDevice, PartnerFloorConfig,
    PartnerBooking, PRICE_SEGMENTS, LISTING_TYPES,
    LotDealerVisibility, LotBookingRequest,
    PartnerBid, PartnerBidDocument, BID_DOC_TYPES,
)
from models.crm import CRMSalesOpportunity
from auth.dependencies import (
    get_current_user, verify_csrf, hash_password, require_module_perm,
)
from services.audit_engine import audit
from services.partner_service import (
    next_listing_code, resolve_floor, ageing_bucket, get_settings, set_setting,
    photos_list, SETTING_DEFAULTS,
)
from auth.partner_auth import normalize_phone
from utils.dealer_code import next_dealer_code
from utils.timezone import app_now
from config import UPLOADS_DIR

router = APIRouter(prefix="/trade-partner", tags=["trade-partner-admin"])

PARTNER_TYPES = ["dealer", "trader", "repair_shop"]


def _gen_temp_password(length: int = 8) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def _sales_users(db: AsyncSession):
    r = await db.execute(
        select(User.username, User.full_name).where(User.status == True)  # noqa: E712
        .order_by(User.username)
    )
    return r.all()


async def _account_candidates(db: AsyncSession):
    """Accounts (CRM Contact Leads) offered in the Enable Portal Access picker.

    Deliberately NOT filtered down to accounts that have no portal login yet.
    Working out whether an account already has one means resolving it through
    the dealer bridge (link, then phone, then name), and a near-miss there would
    silently hide a real account from the operator with no way to tell why.
    Instead every live account is listed and provisioning skips the ones that
    already have access, reporting each by name.
    """
    r = await db.execute(
        select(CRMContact)
        .where(CRMContact.status == "active", CRMContact.is_trashed == False)  # noqa: E712
        .order_by(CRMContact.company_name)
    )
    return r.scalars().all()


async def _dealer_for_account(db: AsyncSession, contact: CRMContact,
                              username: str) -> tuple[Dealer, bool]:
    """Resolve the Dealer row that backs a CRM Account, creating it if needed.

    Returns (dealer, created). Match order is most-trustworthy first:
      1. an explicit crm_contact_id link from a previous provisioning
      2. normalised phone — the portal login *is* a phone, so a collision here
         would break login for whichever dealer lost the race
      3. business name, case-insensitively

    Only live (untrashed) dealers are considered: binding a portal login to a
    trashed dealer would give the partner an account nobody can see or service.
    """
    if contact.id:
        d = (await db.execute(select(Dealer).where(
            Dealer.crm_contact_id == contact.id,
            Dealer.trashed_at.is_(None),
        ))).scalars().first()
        if d:
            return d, False

    phone = normalize_phone(contact.phone or "")
    if phone:
        d = (await db.execute(select(Dealer).where(
            Dealer.phone == phone, Dealer.trashed_at.is_(None),
        ))).scalars().first()
        if d:
            return d, False

    name = (contact.company_name or "").strip()
    if name:
        d = (await db.execute(select(Dealer).where(
            func.lower(Dealer.business_name) == name.lower(),
            Dealer.trashed_at.is_(None),
        ))).scalars().first()
        if d:
            return d, False

    dealer = Dealer(
        # From MAX(code), not count(*): production has 915 dealers numbered up
        # to 0916, so count(*)+1 returned an existing code and the UNIQUE index
        # on dealer_code made this whole request a 500. See utils/dealer_code.
        dealer_code=await next_dealer_code(db),
        business_name=name or (phone or "Unknown Account"),
        contact_person=contact.contact_person,
        phone=phone or None,
        whatsapp_number=normalize_phone(contact.whatsapp or "") or None,
        email=contact.email,
        address=contact.address,
        city=contact.city,
        state=contact.state,
        pincode=contact.pincode,
        gstin=contact.gstin,
        dealer_type="retail",
        assigned_to=contact.assigned_to,
        created_by=username,
        added_by=username,
        source="Trade Partner: provisioned from CRM Account",
    )
    db.add(dealer)
    await db.flush()   # need dealer.id before the caller writes portal fields
    return dealer, True


@router.get("/partners", response_class=HTMLResponse)
async def partners_list(
    request: Request,
    q: str = "",
    current_user: User = Depends(require_module_perm("trade_partner")),
    db: AsyncSession = Depends(get_db),
):
    query = select(Dealer).where(Dealer.portal_enabled == True)  # noqa: E712
    if q:
        like = f"%{q}%"
        query = query.where(
            (Dealer.business_name.ilike(like))
            | (Dealer.portal_phone.ilike(like))
            | (Dealer.dealer_code.ilike(like))
        )
    result = await db.execute(query.order_by(Dealer.business_name))
    partners = result.scalars().all()

    from services.partner_service import compute_dealer_scores
    scores = await compute_dealer_scores(db, [p.id for p in partners])

    return templates.TemplateResponse("trade_partner/partners.html", {
        "request": request, "current_user": current_user,
        "partners": partners, "accounts": await _account_candidates(db),
        "q": q, "scores": scores,
        "sales_users": await _sales_users(db),
        "partner_types": PARTNER_TYPES, "price_segments": PRICE_SEGMENTS,
        "provisioned": None, "failed": None,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/partners/enable")
async def enable_partner(
    request: Request,
    contact_ids: list[str] = Form(default=[]),
    portal_phone: str = Form(""),
    partner_type: str = Form("dealer"),
    price_segment: str = Form("new_dealer"),
    sales_owner_username: str = Form(""),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "add")),
    db: AsyncSession = Depends(get_db),
):
    """Enable portal access for one or more CRM Accounts — one login each.

    Each selected Account is resolved (or bridged) to its Dealer row, because
    every portal foreign key in the system points at dealers.id. See
    _dealer_for_account for the matching order.

    Login phone: with a single Account selected the operator may type an
    override; with several, each Account's own phone is used, since there is no
    sane way to hand-enter N numbers in one modal. Accounts without a usable
    10-digit number are skipped and named in the result, never silently dropped.

    One bad Account does not abort the batch — the others are still provisioned.

    Renders the page directly rather than redirecting: temp passwords must be
    shown once, and the previous redirect put the password in the query string,
    where it landed in browser history, the access log and any proxy in between.
    """
    if partner_type not in PARTNER_TYPES:
        partner_type = "dealer"
    if price_segment not in PRICE_SEGMENTS:
        price_segment = "new_dealer"
    owner = sales_owner_username.strip() or None

    ids = [c for c in (contact_ids or []) if c and c.strip()]
    if not ids:
        return RedirectResponse(
            url="/trade-partner/partners?error=Select+at+least+one+account",
            status_code=302)

    contacts = (await db.execute(
        select(CRMContact).where(CRMContact.id.in_(ids))
    )).scalars().all()
    by_id = {str(c.id): c for c in contacts}

    override = normalize_phone(portal_phone) if len(ids) == 1 else ""
    provisioned, failed = [], []

    # Phones claimed earlier in THIS batch: two accounts sharing a number would
    # both pass the DB check (neither is committed yet) and then collide on the
    # unique index, failing the whole request.
    claimed: set[str] = set()

    for cid in ids:
        contact = by_id.get(cid)
        if contact is None:
            failed.append({"name": cid, "reason": "Account not found"})
            continue
        label = contact.company_name or contact.contact_code

        norm = override or normalize_phone(contact.phone or "")
        if len(norm) != 10:
            failed.append({"name": label, "reason":
                           "No valid 10-digit mobile on the account"})
            continue
        if norm in claimed:
            failed.append({"name": label, "reason":
                           "Another account in this batch uses the same mobile"})
            continue

        dealer, created = await _dealer_for_account(db, contact, current_user.username)
        if dealer.portal_enabled:
            failed.append({"name": label, "reason":
                           f"Already has portal access ({dealer.portal_phone})"})
            continue
        dup = (await db.execute(select(Dealer).where(
            Dealer.portal_phone == norm, Dealer.id != dealer.id
        ))).scalars().first()
        if dup:
            failed.append({"name": label, "reason":
                           f"{norm} is already the login for {dup.business_name}"})
            continue

        temp_password = _gen_temp_password()
        dealer.crm_contact_id = contact.id
        dealer.portal_enabled = True
        dealer.portal_phone = norm
        dealer.portal_password_hash = hash_password(temp_password)
        dealer.partner_type = partner_type
        dealer.price_segment = price_segment
        dealer.sales_owner_username = owner
        dealer.portal_password_version = (dealer.portal_password_version or 1) + 1
        claimed.add(norm)

        await audit(db, action="PARTNER_PORTAL_ENABLED", user=current_user,
                    table_name="dealers", record_id=str(dealer.id),
                    new_value={"portal_phone": norm, "partner_type": partner_type,
                               "price_segment": price_segment,
                               "sales_owner": owner,
                               "crm_contact_id": str(contact.id),
                               "dealer_created": created},
                    request=request)
        provisioned.append({
            "name": label, "dealer_code": dealer.dealer_code,
            "phone": norm, "password": temp_password,
            "dealer_created": created,
        })

    if provisioned:
        await db.commit()
    else:
        # Nothing to keep, and _dealer_for_account may have flushed new Dealer
        # rows for accounts that then failed validation. Rolling back stops
        # those half-built dealers from being left behind with no portal login.
        await db.rollback()

    query = select(Dealer).where(Dealer.portal_enabled == True)  # noqa: E712
    partners = (await db.execute(query.order_by(Dealer.business_name))).scalars().all()
    from services.partner_service import compute_dealer_scores
    scores = await compute_dealer_scores(db, [p.id for p in partners])

    return templates.TemplateResponse("trade_partner/partners.html", {
        "request": request, "current_user": current_user,
        "partners": partners, "accounts": await _account_candidates(db),
        "q": "", "scores": scores,
        "sales_users": await _sales_users(db),
        "partner_types": PARTNER_TYPES, "price_segments": PRICE_SEGMENTS,
        "provisioned": provisioned, "failed": failed,
        "success": (f"Portal access enabled for {len(provisioned)} account(s)"
                    if provisioned else None),
        "error": (None if provisioned else "No portal access was enabled"),
    })


@router.post("/partners/{dealer_id}/update")
async def update_partner(
    request: Request,
    dealer_id: str,
    partner_type: str = Form("dealer"),
    price_segment: str = Form("new_dealer"),
    sales_owner_username: str = Form(""),
    portal_phone: str = Form(""),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "edit")),
    db: AsyncSession = Depends(get_db),
):
    dealer = (await db.execute(select(Dealer).where(Dealer.id == dealer_id))).scalar_one_or_none()
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer not found")

    new_phone = dealer.portal_phone
    if portal_phone.strip():
        norm = normalize_phone(portal_phone)
        if len(norm) != 10:
            return RedirectResponse(
                url="/trade-partner/partners?error=Enter+a+valid+10-digit+login+mobile+number",
                status_code=302)
        dup = (await db.execute(
            select(Dealer).where(Dealer.portal_phone == norm, Dealer.id != dealer.id)
        )).scalar_one_or_none()
        if dup:
            return RedirectResponse(
                url="/trade-partner/partners?error=That+phone+is+already+a+portal+login",
                status_code=302)
        new_phone = norm

    old = {"partner_type": dealer.partner_type, "price_segment": dealer.price_segment,
           "sales_owner": dealer.sales_owner_username, "portal_phone": dealer.portal_phone}
    dealer.partner_type = partner_type if partner_type in PARTNER_TYPES else dealer.partner_type
    dealer.price_segment = price_segment if price_segment in PRICE_SEGMENTS else dealer.price_segment
    dealer.sales_owner_username = sales_owner_username.strip() or None
    dealer.portal_phone = new_phone
    await audit(db, action="PARTNER_PORTAL_UPDATED", user=current_user,
                table_name="dealers", record_id=str(dealer.id),
                old_value=old,
                new_value={"partner_type": dealer.partner_type,
                           "price_segment": dealer.price_segment,
                           "sales_owner": dealer.sales_owner_username,
                           "portal_phone": dealer.portal_phone},
                request=request)
    await db.commit()
    return RedirectResponse(url="/trade-partner/partners?success=Partner+updated", status_code=302)


@router.post("/partners/{dealer_id}/toggle")
async def toggle_partner(
    request: Request,
    dealer_id: str,
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "edit")),
    db: AsyncSession = Depends(get_db),
):
    """Disable/re-enable portal access (does NOT touch the dealer master record)."""
    dealer = (await db.execute(select(Dealer).where(Dealer.id == dealer_id))).scalar_one_or_none()
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer not found")
    dealer.portal_enabled = not dealer.portal_enabled
    # Kill live sessions on disable
    dealer.portal_password_version = (dealer.portal_password_version or 1) + 1
    await audit(db, action="PARTNER_PORTAL_TOGGLED", user=current_user,
                table_name="dealers", record_id=str(dealer.id),
                new_value={"portal_enabled": dealer.portal_enabled}, request=request)
    await db.commit()
    state = "enabled" if dealer.portal_enabled else "disabled"
    return RedirectResponse(url=f"/trade-partner/partners?success=Portal+{state}", status_code=302)


@router.post("/partners/{dealer_id}/reset-password")
async def reset_partner_password(
    request: Request,
    dealer_id: str,
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "edit")),
    db: AsyncSession = Depends(get_db),
):
    dealer = (await db.execute(select(Dealer).where(Dealer.id == dealer_id))).scalar_one_or_none()
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer not found")
    temp_password = _gen_temp_password()
    dealer.portal_password_hash = hash_password(temp_password)
    dealer.portal_password_version = (dealer.portal_password_version or 1) + 1  # invalidates old JWTs
    await audit(db, action="PARTNER_PASSWORD_RESET", user=current_user,
                table_name="dealers", record_id=str(dealer.id), request=request)
    await db.commit()
    return RedirectResponse(
        url=f"/trade-partner/partners?temp_password={temp_password}"
            f"&temp_for={dealer.business_name}&success=Password+reset",
        status_code=302)


# ═══════════════════════════════════════════════════════════════════════════
# Listings Manager
# ═══════════════════════════════════════════════════════════════════════════

def _parse_decimal(raw, default=None):
    try:
        return Decimal(str(raw).replace(",", "").strip())
    except (InvalidOperation, AttributeError, TypeError):
        return default


def _is_floor_approver(user: User) -> bool:
    """Who may publish below floor. Admin-only in MVP — the module-permission
    matrix defaults to permissive when unconfigured, which would silently let
    every role override the margin gate, so we keep this restrictive."""
    role_name = user.role.value if hasattr(user.role, "value") else str(user.role)
    return role_name == "admin"


async def _save_listing_photos(files) -> list:
    """Listing photos are dealer-visible marketing content — served via the
    public /uploads mount (uploads/partner/photos/). Payment proofs are NOT
    stored here; they live outside uploads/ and are served via an authed route."""
    saved = []
    uploads_dir = os.path.join(UPLOADS_DIR, "partner", "photos")
    os.makedirs(uploads_dir, exist_ok=True)
    for f in files or []:
        if not f or not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        safe_name = f"{uuid_mod.uuid4().hex}{ext}"
        content = await f.read()
        if not content or len(content) > 5 * 1024 * 1024:
            continue
        with open(os.path.join(uploads_dir, safe_name), "wb") as out:
            out.write(content)
        saved.append(safe_name)
    return saved


@router.get("/listings", response_class=HTMLResponse)
async def listings_manager(
    request: Request,
    status: str = "",
    listing_type: str = "",
    current_user: User = Depends(require_module_perm("trade_partner")),
    db: AsyncSession = Depends(get_db),
):
    query = select(PartnerListing).where(PartnerListing.is_active == True)  # noqa: E712
    if status:
        query = query.where(PartnerListing.status == status)
    if listing_type:
        query = query.where(PartnerListing.listing_type == listing_type)
    listings = (await db.execute(query.order_by(PartnerListing.created_at.desc()))).scalars().all()

    ageing = {str(l.id): ageing_bucket(l.stock_intake_date or l.created_at) for l in listings}
    # Ageing summary card: count + ₹ value (dealer_price × qty_available) per bucket
    summary = {}
    for l in listings:
        if l.status not in ("published", "paused", "draft"):
            continue
        b = ageing[str(l.id)]["tag"]
        s = summary.setdefault(b, {"count": 0, "value": Decimal("0")})
        s["count"] += 1
        s["value"] += (l.dealer_price or 0) * (l.qty_available or 0)

    stale_cutoff = app_now() - timedelta(hours=48)
    stale_ids = {
        str(l.id) for l in listings
        if l.status == "published" and (l.price_reviewed_at or l.created_at) < stale_cutoff
    }

    lots = (await db.execute(
        select(Lot).where(Lot.is_trashed == False)  # noqa: E712
        .order_by(Lot.created_at.desc()).limit(300)
    )).scalars().all()

    settings = await get_settings(db)
    return templates.TemplateResponse("trade_partner/listings.html", {
        "request": request, "current_user": current_user,
        "listings": listings, "ageing": ageing, "summary": summary,
        "stale_ids": stale_ids, "lots": lots,
        "listing_types": LISTING_TYPES, "segments": ["all"] + PRICE_SEGMENTS,
        "settings": settings,
        "f_status": status, "f_type": listing_type,
        "is_floor_approver": _is_floor_approver(current_user),
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/listings/create")
async def create_listing(
    request: Request,
    listing_type: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    lot_id: str = Form(""),
    fg_brand: str = Form(""),
    fg_grade: str = Form(""),
    fg_qty: int = Form(0),
    qty_total: int = Form(0),
    moq: int = Form(1),
    dealer_price: str = Form(...),
    token_mode: str = Form("pct"),      # pct | flat
    token_value: str = Form(""),
    hold_hours: int = Form(0),
    visible_to_segment: str = Form("all"),
    photos: list[UploadFile] = File(default=[]),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "add")),
    db: AsyncSession = Depends(get_db),
):
    if listing_type not in LISTING_TYPES:
        return RedirectResponse(url="/trade-partner/listings?error=Invalid+listing+type", status_code=302)
    price = _parse_decimal(dealer_price)
    if price is None or price <= 0:
        return RedirectResponse(url="/trade-partner/listings?error=Enter+a+valid+dealer+price", status_code=302)

    settings = await get_settings(db)
    if hold_hours <= 0:
        hold_hours = int(settings.get("default_hold_hours") or 24)

    # Token per unit — server-side resolution only
    tval = _parse_decimal(token_value)
    if token_mode == "flat" and tval and tval > 0:
        token_per_unit = tval
    else:
        pct = tval if (tval and tval > 0) else _parse_decimal(settings.get("default_token_pct"), Decimal("10"))
        token_per_unit = (price * pct / Decimal("100")).quantize(Decimal("0.01"))

    cost_basis = None
    stock_intake = None
    device_ids = []

    if listing_type == "finished_goods":
        # Server picks N oldest ready devices matching brand/grade, not already listed
        if fg_qty <= 0:
            return RedirectResponse(url="/trade-partner/listings?error=Enter+quantity+of+ready+devices", status_code=302)
        dq = select(Device).where(
            Device.current_stage == DeviceStage.ready_to_sale,
            Device.is_active == True,   # noqa: E712
            Device.is_trashed == False, # noqa: E712
            Device.partner_listed == False,  # noqa: E712
        )
        if fg_brand:
            dq = dq.where(Device.brand.ilike(fg_brand))
        if fg_grade:
            dq = dq.where(Device.grade == fg_grade)
        devices = (await db.execute(dq.order_by(Device.created_at.asc()).limit(fg_qty))).scalars().all()
        if len(devices) < fg_qty:
            return RedirectResponse(
                url=f"/trade-partner/listings?error=Only+{len(devices)}+matching+ready+devices+available",
                status_code=302)
        device_ids = [d.id for d in devices]
        prices = [d.device_price for d in devices if d.device_price]
        cost_basis = (sum(prices) / len(prices)).quantize(Decimal("0.01")) if prices else None
        stock_intake = min((d.created_at for d in devices if d.created_at), default=None)
        qty_total = fg_qty
    else:
        if not lot_id:
            return RedirectResponse(url="/trade-partner/listings?error=Select+a+source+lot", status_code=302)
        lot = (await db.execute(select(Lot).where(Lot.id == lot_id))).scalar_one_or_none()
        if not lot:
            return RedirectResponse(url="/trade-partner/listings?error=Lot+not+found", status_code=302)
        if qty_total <= 0:
            qty_total = lot.qty or 0
        if qty_total <= 0:
            return RedirectResponse(url="/trade-partner/listings?error=Enter+quantity", status_code=302)
        if lot.buying_price and lot.qty:
            cost_basis = (Decimal(lot.buying_price) / Decimal(lot.qty)).quantize(Decimal("0.01"))
        stock_intake = lot.grn_date or lot.purchase_date or lot.created_at

    saved_photos = await _save_listing_photos(photos)

    listing = PartnerListing(
        listing_code=await next_listing_code(db),
        listing_type=listing_type,
        lot_id=lot_id or None,
        title=title.strip(),
        description=description.strip() or None,
        brand=fg_brand.strip() or None,
        grade_summary=fg_grade.strip() or None,
        qty_total=qty_total,
        qty_available=qty_total,
        moq=max(moq, 1),
        dealer_price=price,
        token_amount=token_per_unit,
        hold_hours=hold_hours,
        photos=json.dumps(saved_photos) if saved_photos else None,
        status="draft",
        cost_basis=cost_basis,
        visible_to_segment=visible_to_segment if visible_to_segment in (["all"] + PRICE_SEGMENTS) else "all",
        stock_intake_date=stock_intake,
        created_by=current_user.username,
    )
    db.add(listing)
    await db.flush()

    for did in device_ids:
        db.add(PartnerListingDevice(listing_id=listing.id, device_id=did))
    if device_ids:
        await db.execute(update(Device).where(Device.id.in_(device_ids)).values(partner_listed=True))

    await audit(db, action="PARTNER_LISTING_CREATED", user=current_user,
                table_name="partner_listings", record_id=str(listing.id),
                new_value={"code": listing.listing_code, "type": listing_type,
                           "qty": qty_total, "price": str(price),
                           "token_per_unit": str(token_per_unit)},
                request=request)
    await db.commit()
    return RedirectResponse(
        url=f"/trade-partner/listings?success=Listing+{listing.listing_code}+created+as+draft",
        status_code=302)


@router.post("/listings/{listing_id}/publish")
async def publish_listing(
    request: Request,
    listing_id: str,
    floor_override_reason: str = Form(""),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "edit")),
    db: AsyncSession = Depends(get_db),
):
    listing = (await db.execute(select(PartnerListing).where(PartnerListing.id == listing_id))).scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.status not in ("draft", "paused"):
        return RedirectResponse(url="/trade-partner/listings?error=Only+draft%2Fpaused+listings+can+be+published", status_code=302)

    # ── Margin guardrail (rule 11): hard publish gate ──
    floor = await resolve_floor(db, listing.listing_type, listing.cost_basis)
    listing.floor_value = floor
    if floor is not None and Decimal(listing.dealer_price) < floor:
        if not _is_floor_approver(current_user):
            return RedirectResponse(
                url="/trade-partner/listings?error=Below+floor+—+needs+admin%2Ffinance+approval",
                status_code=302)
        if not floor_override_reason.strip():
            return RedirectResponse(
                url="/trade-partner/listings?error=Floor+override+requires+a+reason",
                status_code=302)
        listing.floor_override_by = current_user.username
        listing.floor_override_reason = floor_override_reason.strip()
        await audit(db, action="PARTNER_FLOOR_OVERRIDE", user=current_user,
                    table_name="partner_listings", record_id=str(listing.id),
                    new_value={"code": listing.listing_code,
                               "price": str(listing.dealer_price),
                               "floor": str(floor),
                               "reason": listing.floor_override_reason},
                    request=request)

    listing.status = "published"
    listing.price_reviewed_at = app_now()
    await audit(db, action="PARTNER_LISTING_PUBLISHED", user=current_user,
                table_name="partner_listings", record_id=str(listing.id),
                new_value={"code": listing.listing_code}, request=request)
    await db.commit()
    return RedirectResponse(url=f"/trade-partner/listings?success={listing.listing_code}+published", status_code=302)


@router.post("/listings/{listing_id}/pause")
async def pause_listing(
    request: Request,
    listing_id: str,
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "edit")),
    db: AsyncSession = Depends(get_db),
):
    listing = (await db.execute(select(PartnerListing).where(PartnerListing.id == listing_id))).scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    listing.status = "paused" if listing.status == "published" else listing.status
    await audit(db, action="PARTNER_LISTING_PAUSED", user=current_user,
                table_name="partner_listings", record_id=str(listing.id),
                new_value={"code": listing.listing_code}, request=request)
    await db.commit()
    return RedirectResponse(url=f"/trade-partner/listings?success={listing.listing_code}+paused", status_code=302)


@router.post("/listings/{listing_id}/reprice")
async def reprice_listing(
    request: Request,
    listing_id: str,
    dealer_price: str = Form(""),
    moq: int = Form(0),
    token_value: str = Form(""),
    hold_hours: int = Form(0),
    confirm_only: str = Form(""),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "edit")),
    db: AsyncSession = Depends(get_db),
):
    """Reprice/edit a listing, or just re-confirm the price (48h review rule).
    Existing bookings keep their snapshots — future bookings only."""
    listing = (await db.execute(select(PartnerListing).where(PartnerListing.id == listing_id))).scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    old = {"price": str(listing.dealer_price), "moq": listing.moq,
           "token": str(listing.token_amount), "hold_hours": listing.hold_hours}

    if not confirm_only:
        price = _parse_decimal(dealer_price)
        if price and price > 0:
            # Repricing below floor on a published listing hits the same gate
            floor = await resolve_floor(db, listing.listing_type, listing.cost_basis)
            if (floor is not None and price < floor
                    and listing.status == "published"
                    and not _is_floor_approver(current_user)):
                return RedirectResponse(
                    url="/trade-partner/listings?error=Below+floor+—+needs+admin%2Ffinance+approval",
                    status_code=302)
            listing.dealer_price = price
        tval = _parse_decimal(token_value)
        if tval and tval > 0:
            listing.token_amount = tval
        if moq > 0:
            listing.moq = moq
        if hold_hours > 0:
            listing.hold_hours = hold_hours

    listing.price_reviewed_at = app_now()
    await audit(db, action="PARTNER_LISTING_REPRICED" if not confirm_only else "PARTNER_PRICE_CONFIRMED",
                user=current_user, table_name="partner_listings",
                record_id=str(listing.id), old_value=old,
                new_value={"price": str(listing.dealer_price), "moq": listing.moq,
                           "token": str(listing.token_amount), "hold_hours": listing.hold_hours},
                request=request)
    await db.commit()
    return RedirectResponse(url=f"/trade-partner/listings?success={listing.listing_code}+updated", status_code=302)


# ═══════════════════════════════════════════════════════════════════════════
# Bookings queue + balance chain (rule 12)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/bookings", response_class=HTMLResponse)
async def bookings_queue(
    request: Request,
    status: str = "",
    q: str = "",
    current_user: User = Depends(require_module_perm("trade_partner")),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload
    from services.partner_service import expire_stale_bookings, compute_dealer_scores
    await expire_stale_bookings(db)
    await db.commit()

    query = (select(PartnerBooking)
             .options(selectinload(PartnerBooking.proofs),
                      selectinload(PartnerBooking.listing),
                      selectinload(PartnerBooking.dealer))
             .order_by(PartnerBooking.created_at.desc()))
    if status:
        query = query.where(PartnerBooking.status == status)
    bookings = (await db.execute(query.limit(500))).scalars().all()
    if q:
        ql = q.lower()
        bookings = [b for b in bookings
                    if ql in (b.booking_number or "").lower()
                    or (b.dealer and ql in (b.dealer.business_name or "").lower())
                    or (b.listing and ql in (b.listing.title or "").lower())]

    scores = await compute_dealer_scores(db, [b.dealer_id for b in bookings])
    settings = await get_settings(db)
    base_url = str(request.base_url).rstrip("/")
    return templates.TemplateResponse("trade_partner/bookings.html", {
        "request": request, "current_user": current_user,
        "bookings": bookings, "scores": scores, "settings": settings,
        "base_url": base_url, "f_status": status, "q": q, "now_ts": app_now(),
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


async def _get_booking(db, booking_id) -> PartnerBooking:
    from sqlalchemy.orm import selectinload
    booking = (await db.execute(
        select(PartnerBooking)
        .options(selectinload(PartnerBooking.proofs),
                 selectinload(PartnerBooking.dealer),
                 selectinload(PartnerBooking.listing))
        .where(PartnerBooking.id == booking_id)
    )).scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


def _pending_proof(booking: PartnerBooking, proof_type: str):
    pending = [p for p in booking.proofs
               if p.proof_type == proof_type and p.status == "pending"]
    return pending[-1] if pending else None


@router.post("/bookings/{booking_id}/verify")
async def verify_token_proof(
    request: Request,
    booking_id: str,
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "upload")),
    db: AsyncSession = Depends(get_db),
):
    """Verify the token proof → booking confirmed_token. Finance-separated via
    the 'upload' action bit on the trade_partner module (sales get add/edit only)."""
    booking = await _get_booking(db, booking_id)
    if booking.status != "proof_uploaded":
        return RedirectResponse(url="/trade-partner/bookings?error=Booking+is+not+awaiting+token+verification", status_code=302)
    proof = _pending_proof(booking, "token")
    if proof:
        proof.status = "verified"
        proof.verified_by = current_user.username
        proof.verified_at = app_now()
    booking.status = "confirmed_token"
    booking.confirmed_by = current_user.username
    await audit(db, action="PARTNER_TOKEN_VERIFIED", user=current_user,
                table_name="partner_bookings", record_id=str(booking.id),
                new_value={"booking": booking.booking_number,
                           "token_total": str(booking.token_total)},
                request=request)
    await db.commit()
    return RedirectResponse(url=f"/trade-partner/bookings?success={booking.booking_number}+token+confirmed", status_code=302)


@router.post("/bookings/{booking_id}/reject")
async def reject_booking(
    request: Request,
    booking_id: str,
    rejection_reason: str = Form(...),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "upload")),
    db: AsyncSession = Depends(get_db),
):
    from services.partner_service import restore_booking_qty
    booking = await _get_booking(db, booking_id)
    if booking.status not in ("pending_payment", "proof_uploaded"):
        return RedirectResponse(url="/trade-partner/bookings?error=Only+open+token+bookings+can+be+rejected", status_code=302)
    if not rejection_reason.strip():
        return RedirectResponse(url="/trade-partner/bookings?error=Rejection+requires+a+reason", status_code=302)
    for p in booking.proofs:
        if p.status == "pending":
            p.status = "rejected"
            p.verified_by = current_user.username
            p.verified_at = app_now()
    booking.status = "rejected"
    booking.rejection_reason = rejection_reason.strip()
    await restore_booking_qty(db, booking)
    await audit(db, action="PARTNER_BOOKING_REJECTED", user=current_user,
                table_name="partner_bookings", record_id=str(booking.id),
                new_value={"booking": booking.booking_number,
                           "reason": booking.rejection_reason},
                request=request)
    await db.commit()
    return RedirectResponse(url=f"/trade-partner/bookings?success={booking.booking_number}+rejected+and+stock+released", status_code=302)


@router.post("/bookings/{booking_id}/balance-verify")
async def verify_balance(
    request: Request,
    booking_id: str,
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "upload")),
    db: AsyncSession = Depends(get_db),
):
    """balance_pending (proof) or confirmed_token (offline payment, audited) → ready_for_dispatch."""
    booking = await _get_booking(db, booking_id)
    if booking.status not in ("balance_pending", "confirmed_token"):
        return RedirectResponse(url="/trade-partner/bookings?error=Booking+is+not+awaiting+balance", status_code=302)
    proof = _pending_proof(booking, "balance")
    if proof:
        proof.status = "verified"
        proof.verified_by = current_user.username
        proof.verified_at = app_now()
    booking.status = "ready_for_dispatch"
    booking.balance_verified_by = current_user.username
    await audit(db, action="PARTNER_BALANCE_VERIFIED", user=current_user,
                table_name="partner_bookings", record_id=str(booking.id),
                new_value={"booking": booking.booking_number,
                           "offline_no_proof": proof is None},
                request=request)
    await db.commit()
    return RedirectResponse(url=f"/trade-partner/bookings?success={booking.booking_number}+ready+for+dispatch", status_code=302)


@router.post("/bookings/{booking_id}/dispatched")
async def mark_dispatched(
    request: Request,
    booking_id: str,
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "edit")),
    db: AsyncSession = Depends(get_db),
):
    booking = await _get_booking(db, booking_id)
    if booking.status != "ready_for_dispatch":
        return RedirectResponse(url="/trade-partner/bookings?error=Booking+is+not+ready+for+dispatch", status_code=302)
    booking.status = "dispatched"
    booking.dispatched_at = app_now()
    await audit(db, action="PARTNER_BOOKING_DISPATCHED", user=current_user,
                table_name="partner_bookings", record_id=str(booking.id),
                new_value={"booking": booking.booking_number}, request=request)
    await db.commit()
    return RedirectResponse(url=f"/trade-partner/bookings?success={booking.booking_number}+dispatched", status_code=302)


@router.post("/bookings/{booking_id}/extend")
async def extend_booking(
    request: Request,
    booking_id: str,
    extra_hours: int = Form(24),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "edit")),
    db: AsyncSession = Depends(get_db),
):
    booking = await _get_booking(db, booking_id)
    if booking.status != "pending_payment":
        return RedirectResponse(url="/trade-partner/bookings?error=Only+pending+bookings+can+be+extended", status_code=302)
    extra = min(max(extra_hours, 1), 168)
    booking.expires_at = booking.expires_at + timedelta(hours=extra)
    await audit(db, action="PARTNER_BOOKING_EXTENDED", user=current_user,
                table_name="partner_bookings", record_id=str(booking.id),
                new_value={"booking": booking.booking_number, "extra_hours": extra,
                           "new_expiry": booking.expires_at.isoformat()},
                request=request)
    await db.commit()
    return RedirectResponse(url=f"/trade-partner/bookings?success={booking.booking_number}+extended+{extra}h", status_code=302)


@router.get("/proof-file/{proof_id}")
async def staff_proof_file(
    proof_id: str,
    current_user: User = Depends(require_module_perm("trade_partner")),
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import FileResponse
    from models.partner import PartnerPaymentProof
    from services.partner_service import PROOFS_DIR
    proof = (await db.execute(
        select(PartnerPaymentProof).where(PartnerPaymentProof.id == proof_id)
    )).scalar_one_or_none()
    if not proof or not proof.screenshot_path:
        raise HTTPException(status_code=404, detail="Proof not found")
    path = os.path.join(PROOFS_DIR, os.path.basename(proof.screenshot_path))
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Proof file missing")
    return FileResponse(path)


# ═══════════════════════════════════════════════════════════════════════════
# My Desk — sales owner dashboard (section 19)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/my-desk", response_class=HTMLResponse)
async def my_desk(
    request: Request,
    current_user: User = Depends(require_module_perm("trade_partner")),
    db: AsyncSession = Depends(get_db),
):
    """Everything the logged-in sales owner needs to run dealer activation:
    assigned dealers, pending proofs, expiring holds, expired-needing-a-call,
    never-logged-in dealers, and stale-price listings. Admin sees everything."""
    from sqlalchemy.orm import selectinload
    from services.partner_service import expire_stale_bookings, compute_dealer_scores
    await expire_stale_bookings(db)
    await db.commit()

    role_name = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    is_admin = role_name == "admin"

    dq = select(Dealer).where(Dealer.portal_enabled == True)  # noqa: E712
    if not is_admin:
        dq = dq.where(Dealer.sales_owner_username == current_user.username)
    dealers = (await db.execute(dq.order_by(Dealer.business_name))).scalars().all()
    dealer_ids = [d.id for d in dealers]
    scores = await compute_dealer_scores(db, dealer_ids)

    bookings = []
    if dealer_ids:
        bookings = (await db.execute(
            select(PartnerBooking)
            .options(selectinload(PartnerBooking.dealer), selectinload(PartnerBooking.listing))
            .where(PartnerBooking.dealer_id.in_(dealer_ids))
            .order_by(PartnerBooking.created_at.desc()).limit(300)
        )).scalars().all()

    now = app_now()
    soon = now + timedelta(hours=6)
    pending_proofs = [b for b in bookings if b.status == "proof_uploaded"]
    balance_waiting = [b for b in bookings if b.status in ("confirmed_token", "balance_pending")]
    expiring_soon = [b for b in bookings if b.status == "pending_payment" and b.expires_at <= soon]
    recently_expired = [b for b in bookings if b.status == "expired"][:10]
    never_logged_in = [d for d in dealers if not d.portal_last_login_at]

    # Stale-price queue: published listings not reviewed in 48h
    stale_cutoff = now - timedelta(hours=48)
    stale_listings = (await db.execute(
        select(PartnerListing).where(
            PartnerListing.status == "published",
            PartnerListing.is_active == True,  # noqa: E712
        ).order_by(PartnerListing.price_reviewed_at.asc().nulls_first())
    )).scalars().all()
    stale_listings = [l for l in stale_listings
                      if (l.price_reviewed_at or l.created_at) < stale_cutoff]

    settings = await get_settings(db)
    base_url = str(request.base_url).rstrip("/")
    return templates.TemplateResponse("trade_partner/my_desk.html", {
        "request": request, "current_user": current_user, "is_admin": is_admin,
        "dealers": dealers, "scores": scores,
        "pending_proofs": pending_proofs, "balance_waiting": balance_waiting,
        "expiring_soon": expiring_soon, "recently_expired": recently_expired,
        "never_logged_in": never_logged_in, "stale_listings": stale_listings,
        "settings": settings, "base_url": base_url,
    })


# ═══════════════════════════════════════════════════════════════════════════
# Floor config (admin/finance only, versioned)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/floors", response_class=HTMLResponse)
async def floors_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _is_floor_approver(current_user):
        raise HTTPException(status_code=403, detail="Floor config is admin/finance only")
    rows = (await db.execute(
        select(PartnerFloorConfig).order_by(
            PartnerFloorConfig.listing_type, PartnerFloorConfig.effective_from.desc())
    )).scalars().all()
    return templates.TemplateResponse("trade_partner/floors.html", {
        "request": request, "current_user": current_user, "rows": rows,
        "listing_types": LISTING_TYPES,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/floors/create")
async def create_floor(
    request: Request,
    listing_type: str = Form(...),
    floor_rule_type: str = Form(...),
    floor_pct: str = Form(""),
    floor_value: str = Form(""),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _is_floor_approver(current_user):
        raise HTTPException(status_code=403, detail="Floor config is admin/finance only")
    if listing_type not in LISTING_TYPES:
        raise HTTPException(status_code=400, detail="Invalid listing type")
    pct = _parse_decimal(floor_pct)
    val = _parse_decimal(floor_value)
    if pct is None and val is None:
        return RedirectResponse(url="/trade-partner/floors?error=Enter+a+floor+%25+or+value", status_code=302)
    row = PartnerFloorConfig(
        listing_type=listing_type, floor_rule_type=floor_rule_type.strip()[:30],
        floor_pct=pct, floor_value=val, effective_from=app_now(),
        created_by=current_user.username,
    )
    db.add(row)
    await db.flush()
    await audit(db, action="PARTNER_FLOOR_CONFIG_ADDED", user=current_user,
                table_name="partner_floor_config", record_id=str(row.id),
                new_value={"listing_type": listing_type, "pct": str(pct), "value": str(val)},
                request=request)
    await db.commit()
    return RedirectResponse(url="/trade-partner/floors?success=Floor+version+added", status_code=302)


# ═══════════════════════════════════════════════════════════════════════════
# Settings
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    current_user: User = Depends(require_module_perm("trade_partner")),
    db: AsyncSession = Depends(get_db),
):
    settings = await get_settings(db)
    return templates.TemplateResponse("trade_partner/settings.html", {
        "request": request, "current_user": current_user, "settings": settings,
        "success": request.query_params.get("success"),
    })


@router.post("/settings")
async def settings_save(
    request: Request,
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "edit")),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    changed = {}
    for key in SETTING_DEFAULTS:
        if key in form:
            await set_setting(db, key, str(form.get(key, "")).strip(), current_user.username)
            changed[key] = str(form.get(key, ""))[:80]
    await audit(db, action="PARTNER_SETTINGS_UPDATED", user=current_user,
                table_name="partner_settings", new_value=changed, request=request)
    await db.commit()
    return RedirectResponse(url="/trade-partner/settings?success=Settings+saved", status_code=302)


# ── Manage Lots (item 27) — direct Lot Management visibility, separate from
# the curated PartnerListing pipeline above. ────────────────────────────────

@router.get("/manage-lots", response_class=HTMLResponse)
async def manage_lots(
    request: Request,
    current_user: User = Depends(require_module_perm("trade_partner")),
    db: AsyncSession = Depends(get_db),
):
    lots = (await db.execute(select(Lot).order_by(Lot.purchase_date.desc()))).scalars().all()
    lot_ids = [l.id for l in lots]

    avail_map = {}
    if lot_ids:
        avail_rows = (await db.execute(
            select(Device.lot_id, func.count(Device.id))
            .where(Device.lot_id.in_(lot_ids), Device.is_active == True)
            .group_by(Device.lot_id)
        )).all()
        avail_map = {str(lid): cnt for lid, cnt in avail_rows}

    vis_map: dict = {}
    if lot_ids:
        vis_rows = (await db.execute(
            select(LotDealerVisibility.lot_id, func.count(LotDealerVisibility.id))
            .where(LotDealerVisibility.lot_id.in_(lot_ids))
            .group_by(LotDealerVisibility.lot_id)
        )).all()
        vis_map = {str(lid): cnt for lid, cnt in vis_rows}

    dealers = (await db.execute(
        select(Dealer).where(Dealer.portal_enabled == True).order_by(Dealer.business_name)  # noqa: E712
    )).scalars().all()

    return templates.TemplateResponse("trade_partner/manage_lots.html", {
        "request": request, "current_user": current_user,
        "lots": lots, "avail_map": avail_map, "vis_map": vis_map,
        "dealers": dealers,
        "success": request.query_params.get("success"),
    })


@router.post("/manage-lots/{lot_id}/assign-visibility")
async def assign_lot_visibility(
    lot_id: str,
    request: Request,
    dealer_id: str = Form(...),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "edit")),
    db: AsyncSession = Depends(get_db),
):
    lot = (await db.execute(select(Lot).where(Lot.id == lot_id))).scalar_one_or_none()
    if not lot:
        raise HTTPException(404, "Lot not found")
    dealer = (await db.execute(select(Dealer).where(Dealer.id == dealer_id))).scalar_one_or_none()
    if not dealer:
        raise HTTPException(404, "Dealer not found")

    existing = (await db.execute(
        select(LotDealerVisibility).where(
            LotDealerVisibility.lot_id == lot.id, LotDealerVisibility.dealer_id == dealer.id,
        )
    )).scalar_one_or_none()
    if not existing:
        db.add(LotDealerVisibility(lot_id=lot.id, dealer_id=dealer.id, assigned_by=current_user.username))
        await audit(db, action="LOT_VISIBILITY_ASSIGNED", user=current_user,
                    table_name="lot_dealer_visibility", record_id=str(lot.id),
                    new_value={"lot_number": lot.lot_number, "dealer": dealer.business_name},
                    request=request)
        await db.commit()
    return RedirectResponse(
        url=f"/trade-partner/manage-lots?success=Lot+{lot.lot_number}+visible+to+{dealer.business_name}",
        status_code=302)


# ═══════════════════════════════════════════════════════════════════════════
# Bids Created — captured bids + Mark Won  (sidebar: after Listings Manager)
# ═══════════════════════════════════════════════════════════════════════════

BIDS_DIR = os.path.join(UPLOADS_DIR, "partner", "bids")


async def _bid_rows(db: AsyncSession, bids):
    """Decorate bids with the account/lot/manager columns the page shows.

    Everything is fetched set-based. Doing it per row meant six extra queries
    per bid, and this table is sorted by amount across every listing, so it is
    exactly the page most likely to be long.
    """
    if not bids:
        return []

    dealer_ids = {b.dealer_id for b in bids}
    dealers = {d.id: d for d in (await db.execute(
        select(Dealer).where(Dealer.id.in_(dealer_ids)))).scalars().all()}

    contact_ids = {d.crm_contact_id for d in dealers.values() if d.crm_contact_id}
    contacts = {}
    if contact_ids:
        contacts = {c.id: c for c in (await db.execute(
            select(CRMContact).where(CRMContact.id.in_(contact_ids)))).scalars().all()}

    listing_ids = {b.listing_id for b in bids}
    listings = {l.id: l for l in (await db.execute(
        select(PartnerListing).where(PartnerListing.id.in_(listing_ids)))).scalars().all()}

    lot_ids = {l.lot_id for l in listings.values() if l.lot_id}
    lots = {}
    if lot_ids:
        lots = {l.id: l for l in (await db.execute(
            select(Lot).where(Lot.id.in_(lot_ids)))).scalars().all()}

    owners = {u: (fn or u) for u, fn in (await db.execute(
        select(User.username, User.full_name))).all()}

    bid_ids = [b.id for b in bids]
    docs: dict = {}
    for d in (await db.execute(
        select(PartnerBidDocument).where(PartnerBidDocument.bid_id.in_(bid_ids))
    )).scalars().all():
        docs.setdefault(str(d.bid_id), []).append(d)

    rows = []
    for b in bids:
        dealer = dealers.get(b.dealer_id)
        listing = listings.get(b.listing_id)
        contact = contacts.get(dealer.crm_contact_id) if dealer and dealer.crm_contact_id else None
        lot = lots.get(listing.lot_id) if listing and listing.lot_id else None
        rows.append({
            "bid": b,
            "dealer_name": dealer.business_name if dealer else "-",
            "lot_number": (lot.lot_number if lot
                           else (listing.listing_code if listing else "-")),
            "listing_title": listing.title if listing else "-",
            # Account columns come from the CRM Account behind the dealer. A
            # dealer created directly in Dealer Management has none, so these
            # read as a dash rather than silently borrowing the dealer's name.
            "account_name": contact.company_name if contact else "-",
            "account_contact": (contact.contact_person or contact.phone or "-")
                               if contact else "-",
            "account_category": ((contact.buyer_type or contact.source_type
                                  or contact.contact_type) if contact else None) or "-",
            "manager_name": owners.get(dealer.sales_owner_username, "-")
                            if dealer and dealer.sales_owner_username else "-",
            "documents": docs.get(str(b.id), []),
        })
    return rows


@router.get("/bids", response_class=HTMLResponse)
async def bids_created(
    request: Request,
    current_user: User = Depends(require_module_perm("trade_partner")),
    db: AsyncSession = Depends(get_db),
):
    """Two tables: bids still in play, and the ones already Marked Won.

    Captured bids sort by amount DESC - the operator's question on this page is
    always "what is the best offer on the table", so the answer is row one.
    """
    captured = (await db.execute(
        select(PartnerBid).where(PartnerBid.status == "active")
        .order_by(PartnerBid.bid_amount.desc())
    )).scalars().all()
    won = (await db.execute(
        select(PartnerBid).where(PartnerBid.status == "won")
        .order_by(PartnerBid.won_at.desc())
    )).scalars().all()

    return templates.TemplateResponse("trade_partner/bids.html", {
        "request": request, "current_user": current_user,
        "captured": await _bid_rows(db, captured),
        "won": await _bid_rows(db, won),
        "doc_types": BID_DOC_TYPES,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/bids/{bid_id}/mark-won")
async def mark_bid_won(
    request: Request,
    bid_id: str,
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "edit")),
    db: AsyncSession = Depends(get_db),
):
    """Award the lot to this bid and open a Buyer Deal for it.

    Marking one bid won marks every other active bid on the SAME listing lost.
    Leaving them active would keep a sold lot showing live bids on the partner
    side and let a second bid be marked won against stock already committed.
    """
    bid = (await db.execute(
        select(PartnerBid).where(PartnerBid.id == bid_id).with_for_update()
    )).scalar_one_or_none()
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")
    if bid.status == "won":
        return RedirectResponse(
            url="/trade-partner/bids?error=That+bid+is+already+marked+won",
            status_code=302)
    if bid.status != "active":
        return RedirectResponse(
            url=f"/trade-partner/bids?error=Bid+is+{bid.status}", status_code=302)

    dealer = (await db.execute(
        select(Dealer).where(Dealer.id == bid.dealer_id))).scalar_one_or_none()
    listing = (await db.execute(
        select(PartnerListing).where(PartnerListing.id == bid.listing_id)
    )).scalar_one_or_none()

    n = ((await db.execute(select(func.count(CRMSalesOpportunity.id)))).scalar() or 0) + 1
    opp = CRMSalesOpportunity(
        opp_number=f"OPP-{app_now().year}-{n:04d}",
        # Links to the CRM Account behind the dealer when there is one, so the
        # Buyer Deal lands on that account's profile rather than floating free.
        contact_id=dealer.crm_contact_id if dealer else None,
        title=f"{listing.title if listing else 'Lot'} - won by "
              f"{dealer.business_name if dealer else 'dealer'} ({bid.bid_number})",
        buyer_type="dealer",
        required_qty=listing.qty_available if listing else None,
        grade_required=listing.grade_summary if listing else None,
        stage="won",
        estimated_value=bid.bid_amount,
        assigned_to=dealer.sales_owner_username if dealer else None,
        notes=(f"Created from Trade Partner bid {bid.bid_number} "
               f"({bid.bid_type} price) on listing "
               f"{listing.listing_code if listing else '-'}."),
        created_by=current_user.username,
    )
    db.add(opp)
    await db.flush()

    bid.status = "won"
    bid.won_by = current_user.username
    bid.won_at = app_now()
    bid.opportunity_id = opp.id

    await db.execute(
        update(PartnerBid)
        .where(PartnerBid.listing_id == bid.listing_id,
               PartnerBid.id != bid.id,
               PartnerBid.status == "active")
        .values(status="lost")
    )

    await audit(db, action="PARTNER_BID_MARKED_WON", user=current_user,
                table_name="partner_bids", record_id=str(bid.id),
                new_value={"bid_number": bid.bid_number,
                           "amount": str(bid.bid_amount),
                           "dealer": dealer.business_name if dealer else None,
                           "opportunity": opp.opp_number},
                request=request)
    await db.commit()
    return RedirectResponse(
        url=f"/trade-partner/bids?success=Buyer+Deal+{opp.opp_number}+created",
        status_code=302)


@router.post("/bids/{bid_id}/upload")
async def upload_bid_document(
    request: Request,
    bid_id: str,
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("trade_partner", "edit")),
    db: AsyncSession = Depends(get_db),
):
    """Attach a Quote / PO / Invoice to a bid for the download column."""
    if doc_type not in BID_DOC_TYPES:
        return RedirectResponse(url="/trade-partner/bids?error=Unknown+document+type",
                                status_code=302)
    bid = (await db.execute(
        select(PartnerBid).where(PartnerBid.id == bid_id))).scalar_one_or_none()
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")

    os.makedirs(BIDS_DIR, exist_ok=True)
    # Stored under a generated name: the uploaded filename is attacker-supplied
    # and would otherwise let a path like ../../config.ini escape the directory,
    # or one upload silently overwrite another's.
    ext = os.path.splitext(file.filename or "")[1][:10]
    stored = f"{bid.bid_number}_{doc_type}_{uuid_mod.uuid4().hex[:8]}{ext}"
    with open(os.path.join(BIDS_DIR, stored), "wb") as fh:
        fh.write(await file.read())

    db.add(PartnerBidDocument(
        bid_id=bid.id, doc_type=doc_type, filename=stored,
        original_name=file.filename, uploaded_by=current_user.username,
    ))
    await audit(db, action="PARTNER_BID_DOC_UPLOADED", user=current_user,
                table_name="partner_bid_documents", record_id=str(bid.id),
                new_value={"bid": bid.bid_number, "type": doc_type,
                           "file": file.filename},
                request=request)
    await db.commit()
    return RedirectResponse(url="/trade-partner/bids?success=Document+attached",
                            status_code=302)


@router.get("/bids/document/{doc_id}")
async def download_bid_document(
    doc_id: str,
    current_user: User = Depends(require_module_perm("trade_partner")),
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import FileResponse
    doc = (await db.execute(
        select(PartnerBidDocument).where(PartnerBidDocument.id == doc_id)
    )).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    # basename() again on read: even though upload generates the name, a row
    # edited by any other path must not be able to walk out of BIDS_DIR.
    path = os.path.join(BIDS_DIR, os.path.basename(doc.filename))
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(path, filename=doc.original_name or doc.filename)
