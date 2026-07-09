"""OxyPC Trade Partner — dealer-facing B2B portal models.

All tables prefixed partner_ (the existing dealer_* tables belong to the
internal telecalling module). Dealer identity itself stays on the existing
`dealers` table (portal columns added there) so the dealer master remains
the single source of truth.
"""
import uuid
from utils.timezone import app_now
from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Text, Boolean, Numeric, Integer,
    Index, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


# ── Listing types / statuses (plain varchars, validated in service layer) ──
LISTING_TYPES = ["finished_goods", "bulk_lot", "functional_ok", "as_is"]
LISTING_STATUSES = ["draft", "published", "paused", "sold_out"]
BOOKING_STATUSES = [
    "pending_payment", "proof_uploaded", "confirmed_token",
    "balance_pending", "ready_for_dispatch", "dispatched",
    "rejected", "expired", "cancelled",
]
PRICE_SEGMENTS = ["new_dealer", "verified", "high_volume", "city_captain", "trader"]


class PartnerListing(Base):
    __tablename__ = "partner_listings"
    __table_args__ = (
        Index("ix_partner_listings_status_type", "status", "listing_type"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_code = Column(String(20), unique=True, nullable=False, index=True)  # TPL-0001
    listing_type = Column(String(20), nullable=False)  # finished_goods, bulk_lot, functional_ok, as_is
    lot_id = Column(UUID(as_uuid=True), ForeignKey("lots.id"), nullable=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    brand = Column(String(100), nullable=True)
    model_summary = Column(String(300), nullable=True)
    grade_summary = Column(String(100), nullable=True)   # e.g. "A/B mix"
    qty_total = Column(Integer, nullable=False, default=0)
    qty_available = Column(Integer, nullable=False, default=0)
    moq = Column(Integer, nullable=False, default=1)
    dealer_price = Column(Numeric(12, 2), nullable=False, default=0)   # per unit
    token_amount = Column(Numeric(12, 2), nullable=False, default=0)   # resolved ₹ per unit
    hold_hours = Column(Integer, nullable=False, default=24)
    photos = Column(Text, nullable=True)  # JSON list of filenames under uploads/partner/
    status = Column(String(20), nullable=False, default="draft")
    # Margin guardrail
    cost_basis = Column(Numeric(12, 2), nullable=True)      # internal reference, NEVER dealer-exposed
    floor_value = Column(Numeric(12, 2), nullable=True)      # resolved floor at publish time
    floor_override_by = Column(String(50), nullable=True)    # username; set only on audited override
    floor_override_reason = Column(Text, nullable=True)
    # Price tiering readiness (Phase 1 uses standard price for all)
    price_tier = Column(String(30), nullable=False, default="standard")
    visible_to_segment = Column(String(30), nullable=False, default="all")
    price_reviewed_at = Column(DateTime, nullable=True)      # 48h stale-price rule
    # Ageing source: intake date of underlying stock (lot created_at / GRN date)
    stock_intake_date = Column(DateTime, nullable=True)
    created_by = Column(String(50), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = Column(DateTime, default=app_now)
    updated_at = Column(DateTime, default=app_now, onupdate=app_now)

    devices = relationship("PartnerListingDevice", back_populates="listing", lazy="select")


class PartnerListingDevice(Base):
    """Ready-stock devices backing a finished-goods listing (blocks double-listing)."""
    __tablename__ = "partner_listing_devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id = Column(UUID(as_uuid=True), ForeignKey("partner_listings.id"), nullable=False, index=True)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=app_now)

    listing = relationship("PartnerListing", back_populates="devices")


class PartnerFloorConfig(Base):
    """Versioned margin floors per listing type — never overwritten, effective-dated."""
    __tablename__ = "partner_floor_config"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_type = Column(String(20), nullable=False, index=True)
    floor_rule_type = Column(String(30), nullable=False)  # margin_pct, floor_price_pct, recovery_value, liquidation_min
    floor_pct = Column(Numeric(6, 2), nullable=True)      # e.g. 8.00 = 8% over cost basis
    floor_value = Column(Numeric(12, 2), nullable=True)   # absolute ₹ floor where applicable
    effective_from = Column(DateTime, nullable=False, default=app_now)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=app_now)


class PartnerBooking(Base):
    __tablename__ = "partner_bookings"
    __table_args__ = (
        Index("ix_partner_bookings_status_expiry", "status", "expires_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_number = Column(String(30), unique=True, nullable=False, index=True)  # TPB-0001
    listing_id = Column(UUID(as_uuid=True), ForeignKey("partner_listings.id"), nullable=False, index=True)
    dealer_id = Column(UUID(as_uuid=True), ForeignKey("dealers.id"), nullable=False, index=True)
    qty = Column(Integer, nullable=False)
    unit_price_snapshot = Column(Numeric(12, 2), nullable=False)
    token_per_unit_snapshot = Column(Numeric(12, 2), nullable=False)
    token_total = Column(Numeric(14, 2), nullable=False)
    status = Column(String(30), nullable=False, default="pending_payment", index=True)
    expires_at = Column(DateTime, nullable=False)
    rejection_reason = Column(Text, nullable=True)
    confirmed_by = Column(String(50), nullable=True)
    balance_verified_by = Column(String(50), nullable=True)
    dispatched_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=app_now)
    updated_at = Column(DateTime, default=app_now, onupdate=app_now)

    listing = relationship("PartnerListing", lazy="select")
    dealer = relationship("Dealer", lazy="select")
    proofs = relationship("PartnerPaymentProof", back_populates="booking", lazy="select")

    @property
    def balance_due(self):
        return (self.unit_price_snapshot * self.qty) - self.token_total


class PartnerPaymentProof(Base):
    __tablename__ = "partner_payment_proofs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id = Column(UUID(as_uuid=True), ForeignKey("partner_bookings.id"), nullable=False, index=True)
    proof_type = Column(String(10), nullable=False, default="token")  # token | balance
    utr_reference = Column(String(100), nullable=True)
    amount_claimed = Column(Numeric(14, 2), nullable=True)
    screenshot_path = Column(String(500), nullable=True)  # stored filename under uploads/partner/
    status = Column(String(20), nullable=False, default="pending")  # pending, verified, rejected
    uploaded_at = Column(DateTime, default=app_now)
    verified_by = Column(String(50), nullable=True)
    verified_at = Column(DateTime, nullable=True)

    booking = relationship("PartnerBooking", back_populates="proofs")


class PartnerSetting(Base):
    """Key/value settings for the partner portal (hold hours, token %, bank details,
    WhatsApp launch template, incentive text)."""
    __tablename__ = "partner_settings"

    key = Column(String(50), primary_key=True)
    value = Column(Text, nullable=True)
    updated_by = Column(String(50), nullable=True)
    updated_at = Column(DateTime, default=app_now, onupdate=app_now)


class PartnerLoginLog(Base):
    __tablename__ = "partner_login_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dealer_id = Column(UUID(as_uuid=True), ForeignKey("dealers.id"), nullable=True, index=True)
    phone_attempted = Column(String(30), nullable=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(300), nullable=True)
    success = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=app_now, index=True)


class PartnerListingView(Base):
    """Raw dealer-engagement feed for the dealer score."""
    __tablename__ = "partner_listing_views"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id = Column(UUID(as_uuid=True), ForeignKey("partner_listings.id"), nullable=False, index=True)
    dealer_id = Column(UUID(as_uuid=True), ForeignKey("dealers.id"), nullable=False, index=True)
    viewed_at = Column(DateTime, default=app_now)
