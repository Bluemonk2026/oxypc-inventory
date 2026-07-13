"""OxyPC Customer Care Agent — post-sale warranty, diagnostics & ticketing.

Bounded context, all tables prefixed care_. The customer-installed desktop
agent authenticates with a per-device bearer token (hashed at rest, same
pattern as models/api_key.py) resolved to exactly one care_device_pairings
row — every query in routers/care_api.py must scope through that row's
device_id/sale_id, never accept one from the client.
"""
import hashlib
import secrets
import uuid
from utils.timezone import app_now
from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Text, Boolean, Numeric, Integer,
    Index, text, JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


TICKET_STATUSES = [
    "open", "assigned", "in_progress", "awaiting_customer",
    "needs_pickup", "resolved", "closed", "cancelled", "reopened",
]
TICKET_PRIORITIES = ["low", "medium", "high", "critical"]
WARRANTY_STATUSES = [
    "not_started", "active", "expiring", "expired", "void",
    "suspended", "replaced", "returned", "bought_back",
]


class CareDevicePairing(Base):
    __tablename__ = "care_device_pairings"
    __table_args__ = (
        Index("ix_care_pairings_device_active", "device_id", "is_active"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    sale_id = Column(UUID(as_uuid=True), ForeignKey("sales.id"), nullable=True, index=True)
    serial_no = Column(String(100), nullable=True)

    # One-time provisioning secret (imaging-time) — hashed, single-use, expiring
    provisioning_token_hash = Column(String(64), nullable=True, unique=True)
    provisioning_token_expires_at = Column(DateTime, nullable=True)
    provisioning_redeemed_at = Column(DateTime, nullable=True)

    # Long-lived device credential — hashed server-side, DPAPI-protected on the agent
    device_token_hash = Column(String(64), nullable=True, unique=True)
    device_token_issued_at = Column(DateTime, nullable=True)
    token_last_rotated_at = Column(DateTime, nullable=True)

    paired_at = Column(DateTime, nullable=True)
    agent_version = Column(String(20), nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    last_ip_hash = Column(String(64), nullable=True)  # hashed, never raw IP at rest

    is_active = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    revoked_at = Column(DateTime, nullable=True)
    revoked_reason = Column(String(200), nullable=True)

    # Customer-controlled marketing consent (spec 17.4) — defaults False
    # everywhere until a customer explicitly opts in via a tray privacy
    # screen (not built yet); care_offers with is_marketing=True must only
    # ever be sent to pairings where this is True.
    marketing_opt_in = Column(Boolean, nullable=False, default=False, server_default=text("false"))

    created_by = Column(String(50), nullable=True)  # staff username who created the pending pairing
    created_at = Column(DateTime, default=app_now)
    updated_at = Column(DateTime, default=app_now, onupdate=app_now)

    tickets = relationship("CareSupportTicket", back_populates="pairing", lazy="select")

    @staticmethod
    def generate_token() -> tuple:
        """Returns (raw_token, sha256_hash) — raw is shown/redeemed once, never stored."""
        raw = "care_" + secrets.token_hex(32)
        return raw, hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def hash_token(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()


class CareWarranty(Base):
    """Authoritative warranty record — explicit business rules, not inferred dates."""
    __tablename__ = "care_warranties"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    sale_id = Column(UUID(as_uuid=True), ForeignKey("sales.id"), nullable=True, index=True)
    policy_id = Column(String(50), nullable=True)
    coverage_type = Column(String(30), nullable=True)  # main_device, battery, adapter, accessory
    start_event = Column(String(30), nullable=True)     # invoice_date, delivery_date, replacement_dispatch
    start_date = Column(DateTime, nullable=True)
    expiry_date = Column(DateTime, nullable=True)
    battery_expiry_date = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="not_started")
    extension_reference = Column(String(100), nullable=True)
    replacement_reference = Column(String(100), nullable=True)
    void_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=app_now)
    updated_at = Column(DateTime, default=app_now, onupdate=app_now)


class CareSupportTicket(Base):
    __tablename__ = "care_support_tickets"
    __table_args__ = (
        Index("ix_care_tickets_pairing_status", "pairing_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_number = Column(String(20), unique=True, nullable=False, index=True)  # CARE-0001
    pairing_id = Column(UUID(as_uuid=True), ForeignKey("care_device_pairings.id"), nullable=False, index=True)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    sale_id = Column(UUID(as_uuid=True), ForeignKey("sales.id"), nullable=True)

    category = Column(String(50), nullable=False)
    subcategory = Column(String(50), nullable=True)
    description = Column(Text, nullable=False)
    priority = Column(String(10), nullable=False, default="medium")
    status = Column(String(20), nullable=False, default="open", index=True)
    customer_contact_preference = Column(String(20), nullable=True)  # call, whatsapp, email

    assigned_to = Column(String(50), nullable=True)
    resolved_by = Column(String(50), nullable=True)
    resolution_notes = Column(Text, nullable=True)         # internal
    customer_visible_notes = Column(Text, nullable=True)    # shown to customer via agent

    pickup_required = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    pickup_reference = Column(String(50), nullable=True)

    # Phase 2 hooks — columns exist now so remote control is additive, not a migration
    remote_session_requested = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    remote_session_consented_at = Column(DateTime, nullable=True)

    idempotency_key = Column(String(100), nullable=True, unique=True)  # dedupes offline-queue retries

    created_at = Column(DateTime, default=app_now)
    updated_at = Column(DateTime, default=app_now, onupdate=app_now)
    resolved_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)

    pairing = relationship("CareDevicePairing", back_populates="tickets")
    events = relationship("CareTicketEvent", back_populates="ticket", lazy="select",
                          order_by="CareTicketEvent.created_at")
    snapshots = relationship("CareDiagnosticSnapshot", back_populates="ticket", lazy="select")


class CareTicketEvent(Base):
    """Append-only ticket history — status changes, assignments, notes."""
    __tablename__ = "care_ticket_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("care_support_tickets.id"), nullable=False, index=True)
    event_type = Column(String(30), nullable=False)  # created, status_change, assigned, note_added, resolved
    old_status = Column(String(20), nullable=True)
    new_status = Column(String(20), nullable=True)
    actor_type = Column(String(10), nullable=False, default="staff")  # staff, customer, system
    actor_id = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=app_now)

    ticket = relationship("CareSupportTicket", back_populates="events")


class CareDiagnosticSnapshot(Base):
    """Read-only hardware telemetry — versioned schema, allowlisted fields only."""
    __tablename__ = "care_diagnostic_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pairing_id = Column(UUID(as_uuid=True), ForeignKey("care_device_pairings.id"), nullable=False, index=True)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("care_support_tickets.id"), nullable=True, index=True)

    diagnostic_profile = Column(String(30), nullable=False, default="support_basic_v1")
    schema_version = Column(Integer, nullable=False, default=1)
    agent_version = Column(String(20), nullable=True)

    bios_serial = Column(String(100), nullable=True)
    manufacturer = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    cpu = Column(String(150), nullable=True)
    ram_gb = Column(Integer, nullable=True)
    storage_summary = Column(String(200), nullable=True)
    battery_health_pct = Column(Integer, nullable=True)
    battery_cycle_count = Column(Integer, nullable=True)
    smart_status = Column(String(20), nullable=True)
    os_version = Column(String(100), nullable=True)
    hardware_warning_summary = Column(Text, nullable=True)
    system_error_summary = Column(Text, nullable=True)  # redacted — no filenames/usernames

    raw_json = Column(JSON, nullable=True)  # full allowlisted payload, for staff detail view

    captured_at = Column(DateTime, default=app_now)
    created_at = Column(DateTime, default=app_now)

    ticket = relationship("CareSupportTicket", back_populates="snapshots")


class CareOffer(Base):
    __tablename__ = "care_offers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    image_url = Column(String(500), nullable=True)
    cta_label = Column(String(50), nullable=True)
    cta_url = Column(String(500), nullable=True)

    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    target_type = Column(String(30), nullable=False, default="all")  # all, model, warranty_window, sale_range
    target_value = Column(String(200), nullable=True)

    channel = Column(String(20), nullable=False, default="in_app")  # in_app, whatsapp, both
    is_marketing = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    consent_required = Column(Boolean, nullable=False, default=True, server_default=text("true"))

    created_by = Column(String(50), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = Column(DateTime, default=app_now)
    updated_at = Column(DateTime, default=app_now, onupdate=app_now)


class CareOfferDelivery(Base):
    """Every offer send attempt — required so campaign sends stay traceable
    (spec section 19.4). One row per (offer, device) send attempt."""
    __tablename__ = "care_offer_deliveries"
    __table_args__ = (
        Index("ix_care_offer_deliveries_offer_device", "offer_id", "device_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    offer_id = Column(UUID(as_uuid=True), ForeignKey("care_offers.id"), nullable=False, index=True)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    channel = Column(String(20), nullable=False)  # in_app, whatsapp
    delivery_status = Column(String(20), nullable=False, default="sent")  # sent, failed, skipped_no_consent
    error_message = Column(String(300), nullable=True)
    sent_at = Column(DateTime, default=app_now)
    sent_by = Column(String(50), nullable=True)


class CareAgentEvent(Base):
    """Operational telemetry only — no personal content. Health dashboard feed."""
    __tablename__ = "care_agent_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pairing_id = Column(UUID(as_uuid=True), ForeignKey("care_device_pairings.id"), nullable=False, index=True)
    event_type = Column(String(40), nullable=False)  # agent_started, pairing_completed, ticket_submitted, ...
    agent_version = Column(String(20), nullable=True)
    metadata_json = Column(JSON, nullable=True)
    occurred_at = Column(DateTime, default=app_now, index=True)


class CareAuditLog(Base):
    """Customer-support-specific audit trail — kept separate from staff audit_logs
    so customer-facing access never mixes with internal-staff audit rows."""
    __tablename__ = "care_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action = Column(String(50), nullable=False)
    pairing_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    ticket_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    actor_type = Column(String(10), nullable=False, default="staff")  # staff, customer, system
    actor_id = Column(String(50), nullable=True)
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    ip_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=app_now, index=True)


DISPATCH_EXCEPTION_REASONS = [
    "corporate_no_software", "non_windows", "clean_os_request",
    "as_is_sale", "temporary_technical",
]


class CareDispatchException(Base):
    """Recorded reason a unit ships WITHOUT an active Care Agent pairing
    (spec section 16). Advisory only today — routers/dispatch.py and
    routers/sales.py do NOT hard-block on the absence of a pairing/exception
    yet, since Phase 4 imaging integration that would auto-provision every
    unit hasn't shipped; hard-blocking now would fail every live sale. This
    table exists so the readiness check has something real to report against
    once that gate is turned on."""
    __tablename__ = "care_dispatch_exceptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    reason = Column(String(30), nullable=False)
    notes = Column(Text, nullable=True)
    approved_by = Column(String(50), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = Column(DateTime, default=app_now)
