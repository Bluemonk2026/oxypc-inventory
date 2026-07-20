"""Trade Partner portal — dealer-facing routes (/partner).

Data boundary: these routes render dealer-safe data ONLY (partner_listings
snapshots). They must never touch lots.buying_price, supplier_name, internal
margins, cost_basis, or staff data. Auth is the partner JWT cookie — staff
sessions cannot open these routes.
"""
import os
import secrets
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func

from urllib.parse import quote

from database import get_db
from templates_config import templates
from models.dealers import Dealer
from models.user import User
from models.partner import (
    PartnerListing, PartnerLoginLog, PartnerListingView, PartnerBooking,
    PartnerPaymentProof, LotDealerVisibility, LotBookingRequest,
)
from models.lot import Lot
from models.device import Device
from auth.dependencies import verify_password
from auth.partner_auth import (
    get_current_partner, verify_partner_csrf, create_partner_token,
    new_partner_csrf, normalize_phone,
    PARTNER_TOKEN_COOKIE, PARTNER_CSRF_COOKIE, PARTNER_SESSION_MINUTES,
)
from services.audit_engine import audit
from services.partner_service import (
    get_settings, ageing_bucket, photos_list, expire_stale_bookings,
    create_booking, BookingError,
)
from utils.timezone import app_now
from config import COOKIE_SECURE
from limiter import limiter, ip_key_func

router = APIRouter(prefix="/partner", tags=["trade-partner-portal"])

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def _login_page(request: Request, error: str = None):
    csrf_tok = new_partner_csrf()
    resp = templates.TemplateResponse("partner/login.html", {
        "request": request, "error": error, "login_csrf": csrf_tok,
    })
    resp.set_cookie(PARTNER_CSRF_COOKIE, csrf_tok, httponly=False,
                    samesite="strict", secure=COOKIE_SECURE)
    return resp


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return _login_page(request)


@router.post("/login")
@limiter.limit("5/minute", key_func=ip_key_func)
async def login(
    request: Request,
    phone: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # CSRF: double-submit against the partner cookie set on the login page
    cookie_token = request.cookies.get(PARTNER_CSRF_COOKIE, "")
    form = await request.form()
    if not cookie_token or form.get("csrf_token", "") != cookie_token:
        return _login_page(request, "Session expired — please try again.")

    norm = normalize_phone(phone)
    result = await db.execute(select(Dealer).where(Dealer.portal_phone == norm))
    dealer = result.scalar_one_or_none()

    ua = (request.headers.get("user-agent") or "")[:300]
    ip = request.client.host if request.client else None

    if dealer:
        cutoff = app_now() - timedelta(minutes=LOCKOUT_MINUTES)
        fail_r = await db.execute(
            select(func.count(PartnerLoginLog.id)).where(
                PartnerLoginLog.dealer_id == dealer.id,
                PartnerLoginLog.success == False,  # noqa: E712
                PartnerLoginLog.created_at >= cutoff,
            )
        )
        if (fail_r.scalar() or 0) >= MAX_FAILED_ATTEMPTS:
            return _login_page(
                request,
                f"Account locked — too many failed attempts. Try again in {LOCKOUT_MINUTES} minutes.",
            )

    if (
        not dealer
        or not dealer.portal_enabled
        or dealer.status != "active"
        or not dealer.portal_password_hash
        or not verify_password(password, dealer.portal_password_hash)
    ):
        db.add(PartnerLoginLog(dealer_id=dealer.id if dealer else None,
                               phone_attempted=norm, ip_address=ip,
                               user_agent=ua, success=False))
        await db.commit()
        return _login_page(request, "Invalid phone number or password")

    token = create_partner_token(dealer)
    db.add(PartnerLoginLog(dealer_id=dealer.id, phone_attempted=norm,
                           ip_address=ip, user_agent=ua, success=True))
    await db.execute(update(Dealer).where(Dealer.id == dealer.id)
                     .values(portal_last_login_at=app_now()))
    await db.commit()

    csrf_tok = new_partner_csrf()
    _max_age = PARTNER_SESSION_MINUTES * 60
    resp = RedirectResponse(url="/partner/catalog", status_code=302)
    resp.set_cookie(PARTNER_TOKEN_COOKIE, token, httponly=True, samesite="strict",
                    max_age=_max_age, secure=COOKIE_SECURE)
    resp.set_cookie(PARTNER_CSRF_COOKIE, csrf_tok, httponly=False, samesite="strict",
                    max_age=_max_age, secure=COOKIE_SECURE)
    return resp


@router.post("/logout")
async def logout(request: Request, _csrf=Depends(verify_partner_csrf)):
    resp = RedirectResponse(url="/partner/login", status_code=302)
    resp.delete_cookie(PARTNER_TOKEN_COOKIE)
    resp.delete_cookie(PARTNER_CSRF_COOKIE)
    return resp


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, dealer: Dealer = Depends(get_current_partner)):
    return RedirectResponse(url="/partner/catalog", status_code=302)


@router.get("/sw.js")
async def service_worker():
    """Serve the PWA service worker from /partner/sw.js so its scope covers
    the whole dealer portal (a /static path would scope it to /static)."""
    from fastapi.responses import FileResponse
    from config import BASE_DIR
    return FileResponse(
        os.path.join(BASE_DIR, "static", "partner", "sw.js"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


async def _sales_owner_wa(db: AsyncSession, dealer: Dealer):
    """WhatsApp number of the dealer's assigned sales owner (digits only)."""
    if not dealer.sales_owner_username:
        return None
    owner = (await db.execute(
        select(User).where(User.username == dealer.sales_owner_username)
    )).scalar_one_or_none()
    if not owner or not owner.whatsapp_number:
        return None
    digits = "".join(ch for ch in owner.whatsapp_number if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return digits or None


@router.get("/catalog", response_class=HTMLResponse)
async def catalog(
    request: Request,
    listing_type: str = "",
    brand: str = "",
    grade: str = "",
    sort: str = "newest",
    dealer: Dealer = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db),
):
    """Published listings, dealer-safe fields only."""
    await expire_stale_bookings(db)
    await db.commit()

    q = select(PartnerListing).where(
        PartnerListing.status == "published",
        PartnerListing.is_active == True,  # noqa: E712
        PartnerListing.qty_available > 0,
    )
    if listing_type:
        q = q.where(PartnerListing.listing_type == listing_type)
    if brand:
        q = q.where(PartnerListing.brand.ilike(f"%{brand}%"))
    if grade:
        q = q.where(PartnerListing.grade_summary.ilike(f"%{grade}%"))
    if sort == "price_low":
        q = q.order_by(PartnerListing.dealer_price.asc())
    elif sort == "price_high":
        q = q.order_by(PartnerListing.dealer_price.desc())
    else:
        q = q.order_by(PartnerListing.created_at.desc())
    listings = (await db.execute(q)).scalars().all()

    # visible_to_segment gate (MVP segment logic that IS live)
    seg = dealer.price_segment or "new_dealer"
    listings = [l for l in listings if l.visible_to_segment in ("all", seg)]

    ageing = {str(l.id): ageing_bucket(l.stock_intake_date or l.created_at) for l in listings}
    if sort == "fresh":
        listings.sort(key=lambda l: ageing[str(l.id)]["days"] or 0)
    elif sort == "deals":
        # Older stock first — where the deals are
        listings.sort(key=lambda l: ageing[str(l.id)]["days"] or 0, reverse=True)

    settings = await get_settings(db)

    # ── Requests for Lot visibility (item 28) — direct Lot Management rows
    # this dealer has been granted visibility on. Dealer-safe fields only:
    # never expose lot.buying_price/supplier_name — "Price" here is the
    # dealer-facing selling_price, same boundary rule as the rest of this file.
    vis_rows = (await db.execute(
        select(Lot).join(LotDealerVisibility, LotDealerVisibility.lot_id == Lot.id)
        .where(LotDealerVisibility.dealer_id == dealer.id)
        .order_by(Lot.purchase_date.desc())
    )).scalars().all()
    visible_lots = []
    if vis_rows:
        lot_ids = [l.id for l in vis_rows]
        avail_rows = (await db.execute(
            select(Device.lot_id, func.count(Device.id))
            .where(Device.lot_id.in_(lot_ids), Device.is_active == True)
            .group_by(Device.lot_id)
        )).all()
        avail_map = {str(lid): cnt for lid, cnt in avail_rows}
        my_bookings = (await db.execute(
            select(LotBookingRequest).where(
                LotBookingRequest.dealer_id == dealer.id,
                LotBookingRequest.lot_id.in_(lot_ids),
                LotBookingRequest.status != "withdrawn",
            )
        )).scalars().all()
        booking_by_lot = {str(b.lot_id): b for b in my_bookings}
        for lot in vis_rows:
            lid = str(lot.id)
            visible_lots.append({
                "id": lid, "lot_number": lot.lot_number,
                "purchase_date": lot.purchase_date,
                "available_quantity": avail_map.get(lid, 0),
                "price": float(lot.selling_price) if lot.selling_price is not None else None,
                "booking": booking_by_lot.get(lid),
            })

    return templates.TemplateResponse("partner/catalog.html", {
        "request": request, "dealer": dealer, "listings": listings,
        "ageing": ageing, "incentive_text": settings.get("incentive_text") or "",
        "f_type": listing_type, "f_brand": brand, "f_grade": grade, "f_sort": sort,
        "partner_csrf": request.cookies.get(PARTNER_CSRF_COOKIE, ""),
        "visible_lots": visible_lots,
    })


@router.get("/listings/{listing_id}", response_class=HTMLResponse)
async def listing_detail(
    request: Request,
    listing_id: str,
    dealer: Dealer = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db),
):
    listing = (await db.execute(
        select(PartnerListing).where(PartnerListing.id == listing_id)
    )).scalar_one_or_none()
    seg = dealer.price_segment or "new_dealer"
    if (not listing or not listing.is_active
            or listing.status not in ("published", "sold_out")
            or listing.visible_to_segment not in ("all", seg)):
        return RedirectResponse(url="/partner/catalog", status_code=302)

    # Engagement capture for the dealer score
    db.add(PartnerListingView(listing_id=listing.id, dealer_id=dealer.id))
    await db.commit()

    share_text = quote(
        f"{listing.title}\n{listing.qty_available} units · "
        f"Grade {listing.grade_summary or '-'} · ₹{listing.dealer_price:,.0f}/unit "
        f"(MOQ {listing.moq})\n{str(request.base_url).rstrip('/')}/partner/listings/{listing.id}"
    )
    owner_wa = await _sales_owner_wa(db, dealer)
    ask_text = quote(f"Hi, I'm interested in {listing.listing_code} — {listing.title}")

    return templates.TemplateResponse("partner/listing_detail.html", {
        "request": request, "dealer": dealer, "listing": listing,
        "photos": photos_list(listing),
        "ageing": ageing_bucket(listing.stock_intake_date or listing.created_at),
        "share_text": share_text, "owner_wa": owner_wa, "ask_text": ask_text,
        "error": request.query_params.get("error"),
        "partner_csrf": request.cookies.get(PARTNER_CSRF_COOKIE, ""),
    })


@router.post("/lots/{lot_id}/book")
async def book_lot(
    request: Request,
    lot_id: str,
    qty: int = Form(1),
    _csrf=Depends(verify_partner_csrf),
    dealer: Dealer = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db),
):
    """Catalog page 'Book' button (item 28) — only for Lots this dealer has
    been granted visibility on. Raises a lightweight LotBookingRequest, not a
    priced PartnerBooking (Lots aren't priced/tokened like PartnerListings)."""
    visible = (await db.execute(
        select(LotDealerVisibility).where(
            LotDealerVisibility.lot_id == lot_id, LotDealerVisibility.dealer_id == dealer.id,
        )
    )).scalar_one_or_none()
    if not visible:
        return RedirectResponse(url="/partner/catalog?error=Lot+not+available+to+you", status_code=302)

    existing = (await db.execute(
        select(LotBookingRequest).where(
            LotBookingRequest.lot_id == lot_id, LotBookingRequest.dealer_id == dealer.id,
            LotBookingRequest.status != "withdrawn",
        )
    )).scalar_one_or_none()
    if existing:
        return RedirectResponse(url="/partner/catalog?error=Already+booked+this+lot", status_code=302)

    booking = LotBookingRequest(lot_id=lot_id, dealer_id=dealer.id, qty_requested=max(1, qty))
    db.add(booking)
    await audit(db, action="LOT_BOOKING_REQUESTED", table_name="lot_booking_requests",
                record_id=str(booking.id), new_value={"lot_id": lot_id, "dealer": dealer.business_name, "qty": qty},
                notes=f"dealer:{dealer.business_name}", request=request)
    await db.commit()
    return RedirectResponse(url="/partner/catalog?success=Lot+booking+requested", status_code=302)


@router.post("/lots/{lot_id}/withdraw")
async def withdraw_lot_booking(
    request: Request,
    lot_id: str,
    _csrf=Depends(verify_partner_csrf),
    dealer: Dealer = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db),
):
    """Catalog page 'Withdraw' button (item 28)."""
    booking = (await db.execute(
        select(LotBookingRequest).where(
            LotBookingRequest.lot_id == lot_id, LotBookingRequest.dealer_id == dealer.id,
            LotBookingRequest.status != "withdrawn",
        )
    )).scalar_one_or_none()
    if not booking:
        return RedirectResponse(url="/partner/catalog?error=No+active+booking+to+withdraw", status_code=302)
    booking.status = "withdrawn"
    await audit(db, action="LOT_BOOKING_WITHDRAWN", table_name="lot_booking_requests",
                record_id=str(booking.id), notes=f"dealer:{dealer.business_name}", request=request)
    await db.commit()
    return RedirectResponse(url="/partner/catalog?success=Booking+withdrawn", status_code=302)


@router.post("/listings/{listing_id}/book")
async def book_listing(
    request: Request,
    listing_id: str,
    qty: int = Form(...),
    _csrf=Depends(verify_partner_csrf),
    dealer: Dealer = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db),
):
    await expire_stale_bookings(db)
    try:
        booking = await create_booking(db, dealer, listing_id, qty)
    except BookingError as e:
        await db.rollback()
        return RedirectResponse(
            url=f"/partner/listings/{listing_id}?error={quote(str(e))}", status_code=302)
    await audit(db, action="PARTNER_BOOKING_CREATED",
                table_name="partner_bookings", record_id=str(booking.id),
                new_value={"booking": booking.booking_number, "dealer": dealer.dealer_code,
                           "qty": qty, "token_total": str(booking.token_total)},
                notes=f"dealer:{dealer.business_name}", request=request)
    await db.commit()
    return RedirectResponse(url=f"/partner/bookings/{booking.id}", status_code=302)


@router.get("/bookings", response_class=HTMLResponse)
async def my_bookings(
    request: Request,
    dealer: Dealer = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db),
):
    await expire_stale_bookings(db)
    await db.commit()
    bookings = (await db.execute(
        select(PartnerBooking).where(PartnerBooking.dealer_id == dealer.id)
        .order_by(PartnerBooking.created_at.desc())
    )).scalars().all()
    listings = {}
    for b in bookings:
        if str(b.listing_id) not in listings:
            listings[str(b.listing_id)] = await db.get(PartnerListing, b.listing_id)

    # Lot Booking Requests (item 28) — shown alongside the priced-listing
    # bookings above, kept as a separate lightweight section since they're
    # not part of the token-payment flow.
    lot_bookings = (await db.execute(
        select(LotBookingRequest).where(
            LotBookingRequest.dealer_id == dealer.id, LotBookingRequest.status != "withdrawn",
        ).order_by(LotBookingRequest.created_at.desc())
    )).scalars().all()
    lots_by_id = {}
    for lb in lot_bookings:
        if str(lb.lot_id) not in lots_by_id:
            lots_by_id[str(lb.lot_id)] = await db.get(Lot, lb.lot_id)

    return templates.TemplateResponse("partner/bookings.html", {
        "request": request, "dealer": dealer, "bookings": bookings,
        "listings": listings,
        "lot_bookings": lot_bookings, "lots_by_id": lots_by_id,
        "partner_csrf": request.cookies.get(PARTNER_CSRF_COOKIE, ""),
    })


@router.get("/bookings/{booking_id}", response_class=HTMLResponse)
async def booking_detail(
    request: Request,
    booking_id: str,
    dealer: Dealer = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db),
):
    await expire_stale_bookings(db)
    await db.commit()
    from sqlalchemy.orm import selectinload
    booking = (await db.execute(
        select(PartnerBooking)
        .options(selectinload(PartnerBooking.proofs))
        .where(
            PartnerBooking.id == booking_id,
            PartnerBooking.dealer_id == dealer.id,
        )
    )).scalar_one_or_none()
    if not booking:
        return RedirectResponse(url="/partner/bookings", status_code=302)
    listing = await db.get(PartnerListing, booking.listing_id)
    settings = await get_settings(db)
    owner_wa = await _sales_owner_wa(db, dealer)
    ask_text = quote(f"Hi, regarding my booking {booking.booking_number} ({listing.title if listing else ''})")
    return templates.TemplateResponse("partner/booking_detail.html", {
        "request": request, "dealer": dealer, "booking": booking,
        "listing": listing, "settings": settings,
        "owner_wa": owner_wa, "ask_text": ask_text,
        "proofs": booking.proofs if booking else [],
        "error": request.query_params.get("error"),
        "success": request.query_params.get("success"),
        "partner_csrf": request.cookies.get(PARTNER_CSRF_COOKIE, ""),
    })


@router.post("/bookings/{booking_id}/proof")
async def upload_proof(
    request: Request,
    booking_id: str,
    proof_type: str = Form("token"),
    utr_reference: str = Form(...),
    amount_claimed: str = Form(""),
    screenshot: UploadFile = File(...),
    _csrf=Depends(verify_partner_csrf),
    dealer: Dealer = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db),
):
    booking = (await db.execute(
        select(PartnerBooking).where(
            PartnerBooking.id == booking_id,
            PartnerBooking.dealer_id == dealer.id,
        )
    )).scalar_one_or_none()
    if not booking:
        return RedirectResponse(url="/partner/bookings", status_code=302)

    proof_type = "balance" if proof_type == "balance" else "token"
    if proof_type == "token" and booking.status != "pending_payment":
        return RedirectResponse(
            url=f"/partner/bookings/{booking.id}?error={quote('Token proof already submitted or booking is closed.')}",
            status_code=302)
    if proof_type == "balance" and booking.status not in ("confirmed_token", "balance_pending"):
        return RedirectResponse(
            url=f"/partner/bookings/{booking.id}?error={quote('Balance proof can be uploaded after the token is confirmed.')}",
            status_code=302)

    from services.partner_service import save_proof_file
    safe_name = await save_proof_file(screenshot)
    if not safe_name:
        return RedirectResponse(
            url=f"/partner/bookings/{booking.id}?error={quote('Upload a jpg/png/pdf up to 5 MB.')}",
            status_code=302)

    from decimal import Decimal, InvalidOperation
    try:
        amount = Decimal(str(amount_claimed).replace(",", "").strip()) if amount_claimed.strip() else None
    except InvalidOperation:
        amount = None

    proof = PartnerPaymentProof(
        booking_id=booking.id, proof_type=proof_type,
        utr_reference=utr_reference.strip()[:100],
        amount_claimed=amount, screenshot_path=safe_name,
    )
    db.add(proof)
    # Rule 6: proof upload freezes the countdown / advances the chain
    if proof_type == "token":
        booking.status = "proof_uploaded"
    else:
        booking.status = "balance_pending"
    await db.flush()
    await audit(db, action="PARTNER_PROOF_UPLOADED",
                table_name="partner_payment_proofs", record_id=str(proof.id),
                new_value={"booking": booking.booking_number, "type": proof_type,
                           "utr": proof.utr_reference,
                           "amount": str(amount) if amount is not None else None},
                notes=f"dealer:{dealer.business_name}", request=request)
    await db.commit()
    return RedirectResponse(
        url=f"/partner/bookings/{booking.id}?success={quote('Proof submitted — verification usually takes a few business hours.')}",
        status_code=302)


@router.get("/bookings/{booking_id}/proof-file/{proof_id}")
async def proof_file(
    booking_id: str,
    proof_id: str,
    dealer: Dealer = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db),
):
    """Authed proof serving — only the owning dealer (staff use the admin route)."""
    from fastapi.responses import FileResponse
    from services.partner_service import PROOFS_DIR
    proof = (await db.execute(
        select(PartnerPaymentProof)
        .join(PartnerBooking, PartnerBooking.id == PartnerPaymentProof.booking_id)
        .where(
            PartnerPaymentProof.id == proof_id,
            PartnerPaymentProof.booking_id == booking_id,
            PartnerBooking.dealer_id == dealer.id,
        )
    )).scalar_one_or_none()
    if not proof or not proof.screenshot_path:
        return RedirectResponse(url="/partner/bookings", status_code=302)
    path = os.path.join(PROOFS_DIR, os.path.basename(proof.screenshot_path))
    if not os.path.exists(path):
        return RedirectResponse(url="/partner/bookings", status_code=302)
    return FileResponse(path)


@router.post("/bookings/{booking_id}/cancel")
async def cancel_booking(
    request: Request,
    booking_id: str,
    _csrf=Depends(verify_partner_csrf),
    dealer: Dealer = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db),
):
    booking = (await db.execute(
        select(PartnerBooking).where(
            PartnerBooking.id == booking_id,
            PartnerBooking.dealer_id == dealer.id,
        )
    )).scalar_one_or_none()
    if not booking or booking.status not in ("pending_payment", "proof_uploaded"):
        return RedirectResponse(url="/partner/bookings", status_code=302)
    from services.partner_service import restore_booking_qty
    booking.status = "cancelled"
    await restore_booking_qty(db, booking)
    await audit(db, action="PARTNER_BOOKING_CANCELLED",
                table_name="partner_bookings", record_id=str(booking.id),
                new_value={"booking": booking.booking_number, "by": "dealer"},
                notes=f"dealer:{dealer.business_name}", request=request)
    await db.commit()
    return RedirectResponse(url="/partner/bookings", status_code=302)


@router.get("/profile", response_class=HTMLResponse)
async def profile(request: Request, dealer: Dealer = Depends(get_current_partner)):
    return templates.TemplateResponse("partner/profile.html", {
        "request": request, "dealer": dealer,
        "partner_csrf": request.cookies.get(PARTNER_CSRF_COOKIE, ""),
    })
