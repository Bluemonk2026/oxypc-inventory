"""Trade Partner — shared service logic.

Route handlers (web now, JSON APIs for native apps later) call these functions
so the core listing/booking/floor/ageing logic never has to be rewritten.
"""
import json
import os
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.partner import (
    PartnerListing, PartnerBooking, PartnerFloorConfig, PartnerSetting,
    PartnerPaymentProof, PartnerLoginLog, PartnerListingView,
)
from utils.timezone import app_now
from config import BASE_DIR

# Payment proofs are sensitive financial documents. They live OUTSIDE the
# publicly mounted uploads/ tree and are served only through authed routes.
PROOFS_DIR = os.path.join(BASE_DIR, "private_uploads", "partner_proofs")


# ── Number generators (max-suffix based, gap-safe like PO numbering) ──────

async def next_listing_code(db: AsyncSession) -> str:
    result = await db.execute(
        select(func.max(PartnerListing.listing_code))
        .where(PartnerListing.listing_code.like("TPL-%"))
    )
    mx = result.scalar()
    n = 1
    if mx:
        try:
            n = int(str(mx).rsplit("-", 1)[-1]) + 1
        except (ValueError, IndexError):
            n = 1
    return f"TPL-{n:04d}"


async def next_booking_number(db: AsyncSession) -> str:
    result = await db.execute(
        select(func.max(PartnerBooking.booking_number))
        .where(PartnerBooking.booking_number.like("TPB-%"))
    )
    mx = result.scalar()
    n = 1
    if mx:
        try:
            n = int(str(mx).rsplit("-", 1)[-1]) + 1
        except (ValueError, IndexError):
            n = 1
    return f"TPB-{n:04d}"


# ── Settings ───────────────────────────────────────────────────────────────

SETTING_DEFAULTS = {
    "default_hold_hours": "24",
    "default_token_pct": "10",
    "bank_details": "",
    "upi_id": "",
    "whatsapp_launch_template": (
        "Namaste {dealer}! You now have first access to the OxyPC Trade Partner "
        "portal — live stock at dealer prices, block lots with a small token.\n"
        "Login: {url}\nMobile: {phone}\nPassword: {password}\n"
        "Demo video: {video}"
    ),
    "incentive_text": "",
}


async def get_settings(db: AsyncSession) -> dict:
    rows = (await db.execute(select(PartnerSetting))).scalars().all()
    settings = dict(SETTING_DEFAULTS)
    for r in rows:
        if r.value is not None:
            settings[r.key] = r.value
    return settings


async def set_setting(db: AsyncSession, key: str, value: str, username: str = None):
    row = await db.get(PartnerSetting, key)
    if row:
        row.value = value
        row.updated_by = username
    else:
        db.add(PartnerSetting(key=key, value=value, updated_by=username))


# ── Margin floor (rule 11) ────────────────────────────────────────────────

async def resolve_floor(db: AsyncSession, listing_type: str,
                        cost_basis: Optional[Decimal]) -> Optional[Decimal]:
    """Resolve the effective floor price/unit for a listing type from the latest
    effective-dated partner_floor_config row. Returns None when no floor is
    configured (publish allowed without gate)."""
    result = await db.execute(
        select(PartnerFloorConfig)
        .where(
            PartnerFloorConfig.listing_type == listing_type,
            PartnerFloorConfig.effective_from <= app_now(),
        )
        .order_by(PartnerFloorConfig.effective_from.desc())
        .limit(1)
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        return None
    if cfg.floor_pct is not None and cost_basis:
        pct_floor = (Decimal(cost_basis) * (Decimal("1") + Decimal(cfg.floor_pct) / Decimal("100")))
        if cfg.floor_value is not None:
            return max(pct_floor, Decimal(cfg.floor_value))
        return pct_floor
    if cfg.floor_value is not None:
        return Decimal(cfg.floor_value)
    return None


# ── Inventory ageing (section 18) ─────────────────────────────────────────

AGEING_BUCKETS = [
    (7,    "fresh",       "Fresh",       "success"),
    (15,   "push",        "Push",        "info"),
    (30,   "discount",    "Discount",    "warning"),
    (None, "liquidation", "Liquidation", "danger"),
]


def ageing_bucket(intake_date) -> dict:
    """Bucket a stock-intake date per the ageing table. Returns tag metadata."""
    if not intake_date:
        return {"days": None, "tag": "unknown", "label": "—", "color": "secondary"}
    days = max((app_now() - intake_date).days, 0)
    for limit, tag, label, color in AGEING_BUCKETS:
        if limit is None or days <= limit:
            return {"days": days, "tag": tag, "label": label, "color": color}
    return {"days": days, "tag": "liquidation", "label": "Liquidation", "color": "danger"}


# ── Photos helper ─────────────────────────────────────────────────────────

def photos_list(listing: PartnerListing) -> list:
    try:
        return json.loads(listing.photos) if listing.photos else []
    except (ValueError, TypeError):
        return []


# ── Booking engine (rules 3–6, 13) ────────────────────────────────────────

ACTIVE_BOOKING_STATUSES = ("pending_payment", "proof_uploaded")


async def expire_stale_bookings(db: AsyncSession) -> int:
    """Lazy expiry sweep (rule 6): expire pending_payment bookings past their
    hold and restore listing availability. Called on every catalog/booking
    read so holds never over-persist even if no scheduler runs. Caller commits."""
    now = app_now()
    stale = (await db.execute(
        select(PartnerBooking).where(
            PartnerBooking.status == "pending_payment",
            PartnerBooking.expires_at < now,
        )
    )).scalars().all()
    for b in stale:
        b.status = "expired"
        listing = await db.get(PartnerListing, b.listing_id)
        if listing:
            listing.qty_available = (listing.qty_available or 0) + b.qty
            if listing.status == "sold_out" and listing.qty_available > 0:
                listing.status = "published"
        await _apply_penalty_ladder(db, b.dealer_id)
    return len(stale)


async def _apply_penalty_ladder(db: AsyncSession, dealer_id):
    """Rule 13: 3 expired in 30 days → token-only access; 5 → auto-disable."""
    from models.dealers import Dealer
    cutoff = app_now() - timedelta(days=30)
    expired_30d = (await db.execute(
        select(func.count(PartnerBooking.id)).where(
            PartnerBooking.dealer_id == dealer_id,
            PartnerBooking.status == "expired",
            PartnerBooking.updated_at >= cutoff,
        )
    )).scalar() or 0
    if expired_30d < 3:
        return
    dealer = await db.get(Dealer, dealer_id)
    if not dealer:
        return
    from services.audit_engine import audit
    if expired_30d >= 5 and dealer.portal_enabled:
        dealer.portal_enabled = False
        dealer.portal_password_version = (dealer.portal_password_version or 1) + 1
        await audit(db, action="PARTNER_AUTO_DISABLED",
                    table_name="dealers", record_id=str(dealer.id),
                    new_value={"expired_bookings_30d": expired_30d},
                    notes="penalty ladder step 5 — pending admin review")
    elif not dealer.portal_token_only:
        dealer.portal_token_only = True
        await audit(db, action="PARTNER_TOKEN_ONLY_FLAGGED",
                    table_name="dealers", record_id=str(dealer.id),
                    new_value={"expired_bookings_30d": expired_30d},
                    notes="penalty ladder step 3")


class BookingError(Exception):
    """User-facing booking failure (MOQ, sold out, duplicate hold…)."""


async def create_booking(db: AsyncSession, dealer, listing_id, qty: int) -> PartnerBooking:
    """Create a token booking with an atomic stock hold. Caller commits.

    Raises BookingError with a dealer-safe message on any rule violation.
    """
    from sqlalchemy import update as sa_update

    listing = await db.get(PartnerListing, listing_id)
    if not listing or listing.status != "published" or not listing.is_active:
        raise BookingError("This listing is no longer available.")
    seg = dealer.price_segment or "new_dealer"
    if listing.visible_to_segment not in ("all", seg):
        raise BookingError("This listing is not available to your account.")
    if qty < max(listing.moq or 1, 1):
        raise BookingError(f"Minimum order quantity is {listing.moq} units.")
    if qty <= 0:
        raise BookingError("Enter a valid quantity.")

    # Rule 4 / penalty ladder: one active booking per listing per dealer;
    # token-only dealers get one active booking TOTAL and half the hold window.
    active_q = select(func.count(PartnerBooking.id)).where(
        PartnerBooking.dealer_id == dealer.id,
        PartnerBooking.status.in_(ACTIVE_BOOKING_STATUSES),
    )
    if not dealer.portal_token_only:
        active_q = active_q.where(PartnerBooking.listing_id == listing.id)
    active = (await db.execute(active_q)).scalar() or 0
    if active > 0:
        if dealer.portal_token_only:
            raise BookingError(
                "Your account is limited to one active booking at a time. "
                "Complete or cancel your current booking first.")
        raise BookingError("You already have an active booking on this listing.")

    # Rule 3: atomic conditional decrement — no race double-booking
    result = await db.execute(
        sa_update(PartnerListing)
        .where(
            PartnerListing.id == listing.id,
            PartnerListing.status == "published",
            PartnerListing.qty_available >= qty,
        )
        .values(qty_available=PartnerListing.qty_available - qty)
    )
    if result.rowcount == 0:
        raise BookingError("Just sold out — not enough units left at this moment.")

    await db.refresh(listing)
    if listing.qty_available <= 0:
        listing.status = "sold_out"

    hold_hours = listing.hold_hours or 24
    if dealer.portal_token_only:
        hold_hours = max(hold_hours // 2, 1)

    from datetime import timedelta
    price = Decimal(listing.dealer_price)
    token_per_unit = Decimal(listing.token_amount)
    booking = PartnerBooking(
        booking_number=await next_booking_number(db),
        listing_id=listing.id,
        dealer_id=dealer.id,
        qty=qty,
        unit_price_snapshot=price,
        token_per_unit_snapshot=token_per_unit,
        token_total=(token_per_unit * qty).quantize(Decimal("0.01")),
        status="pending_payment",
        expires_at=app_now() + timedelta(hours=hold_hours),
    )
    db.add(booking)
    await db.flush()
    return booking


async def restore_booking_qty(db: AsyncSession, booking: PartnerBooking):
    """Give a booking's units back to the listing (reject/cancel/expire)."""
    listing = await db.get(PartnerListing, booking.listing_id)
    if listing:
        listing.qty_available = (listing.qty_available or 0) + booking.qty
        if listing.status == "sold_out" and listing.qty_available > 0:
            listing.status = "published"


# ── Payment proofs (Day 4) ────────────────────────────────────────────────

ALLOWED_PROOF_EXTS = (".jpg", ".jpeg", ".png", ".pdf")
MAX_PROOF_BYTES = 5 * 1024 * 1024


async def save_proof_file(upload) -> Optional[str]:
    """Persist a proof screenshot to the private (non-public) proofs dir.
    Returns the stored filename, or None if the file is missing/invalid."""
    import uuid as uuid_mod
    if not upload or not upload.filename:
        return None
    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in ALLOWED_PROOF_EXTS:
        return None
    content = await upload.read()
    if not content or len(content) > MAX_PROOF_BYTES:
        return None
    os.makedirs(PROOFS_DIR, exist_ok=True)
    safe_name = f"{uuid_mod.uuid4().hex}{ext}"
    with open(os.path.join(PROOFS_DIR, safe_name), "wb") as out:
        out.write(content)
    return safe_name


# ── Dealer score (section 17): computed view, no ML ───────────────────────

def _score_color(score: int) -> str:
    if score >= 70:
        return "success"
    if score >= 40:
        return "warning"
    return "danger"


async def compute_dealer_scores(db: AsyncSession, dealer_ids: list) -> dict:
    """0–100 behavioral score per dealer. Returns {str(dealer_id): {score, color}}.

    +30 confirmed bookings (capped) · +20 repeat orders · +15 payment speed
    (proof <6h of booking) · +15 engagement (logins+views, capped)
    −25 expired ratio · −15 rejected proofs
    """
    scores = {}
    if not dealer_ids:
        return scores
    dealer_ids = list({d for d in dealer_ids})

    bookings = (await db.execute(
        select(PartnerBooking).where(PartnerBooking.dealer_id.in_(dealer_ids))
    )).scalars().all()
    proofs_by_booking = {}
    if bookings:
        proofs = (await db.execute(
            select(PartnerPaymentProof).where(
                PartnerPaymentProof.booking_id.in_([b.id for b in bookings]))
        )).scalars().all()
        for p in proofs:
            proofs_by_booking.setdefault(p.booking_id, []).append(p)

    login_counts = dict((await db.execute(
        select(PartnerLoginLog.dealer_id, func.count(PartnerLoginLog.id))
        .where(PartnerLoginLog.dealer_id.in_(dealer_ids),
               PartnerLoginLog.success == True)  # noqa: E712
        .group_by(PartnerLoginLog.dealer_id)
    )).all())
    view_counts = dict((await db.execute(
        select(PartnerListingView.dealer_id, func.count(PartnerListingView.id))
        .where(PartnerListingView.dealer_id.in_(dealer_ids))
        .group_by(PartnerListingView.dealer_id)
    )).all())

    CONFIRMED = ("confirmed_token", "balance_pending", "ready_for_dispatch", "dispatched")
    for did in dealer_ids:
        my = [b for b in bookings if b.dealer_id == did]
        confirmed = [b for b in my if b.status in CONFIRMED]
        expired = [b for b in my if b.status == "expired"]
        rejected_proofs = sum(
            1 for b in my for p in proofs_by_booking.get(b.id, [])
            if p.status == "rejected")
        fast_pays = 0
        for b in confirmed:
            plist = proofs_by_booking.get(b.id, [])
            first = min((p.uploaded_at for p in plist if p.uploaded_at), default=None)
            if first and b.created_at and (first - b.created_at) <= timedelta(hours=6):
                fast_pays += 1

        score = 0
        score += min(len(confirmed) * 10, 30)
        score += min(max(len(confirmed) - 1, 0) * 10, 20)
        if confirmed:
            score += round(15 * fast_pays / len(confirmed))
        engagement = (login_counts.get(did, 0) or 0) + (view_counts.get(did, 0) or 0)
        score += round(15 * min(engagement, 30) / 30)
        if my:
            score -= round(25 * len(expired) / len(my))
        score -= min(rejected_proofs * 5, 15)
        score = max(0, min(100, score))
        scores[str(did)] = {"score": score, "color": _score_color(score)}
    return scores
