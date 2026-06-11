import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Boolean, Numeric, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class TelecallingSession(Base):
    __tablename__ = "telecalling_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_username = Column(String(50), nullable=False)
    session_date = Column(DateTime, default=app_now)
    total_calls = Column(Integer, default=0)
    connected_calls = Column(Integer, default=0)
    interested_leads = Column(Integer, default=0)
    orders_placed = Column(Integer, default=0)
    target_calls = Column(Integer, default=50)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=app_now)


class TelecallingRecord(Base):
    __tablename__ = "telecalling_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dealer_id = Column(UUID(as_uuid=True), ForeignKey("dealers.id"), nullable=True)
    dealer_name = Column(String(200), nullable=True)

    # ── Lead / Contact info ───────────────────────────────────────────────
    customer_name  = Column(String(200), nullable=True)
    phone          = Column(String(20), nullable=False)
    email          = Column(String(200), nullable=True)
    customer_type  = Column(String(30), nullable=True)   # end_customer, corporate, individual, dealer, reseller
    city           = Column(String(100), nullable=True)
    state          = Column(String(100), nullable=True)

    # ── Product requirement details ───────────────────────────────────────
    category       = Column(String(50), nullable=True)   # Laptop, Desktop, Mobile, Server, Tablet, Workstation
    brand          = Column(String(100), nullable=True)
    model          = Column(String(200), nullable=True)
    generation     = Column(String(50), nullable=True)   # 8th Gen, 10th Gen, etc.
    processor      = Column(String(200), nullable=True)  # Intel i5-10210U, Ryzen 5 4500U, etc.
    ram            = Column(String(50), nullable=True)   # 8GB, 16GB, 32GB
    hard_disk      = Column(String(100), nullable=True)  # 256GB SSD, 1TB HDD, etc.
    product_type   = Column(String(30), nullable=True)   # Refurbished, New, Used
    grade          = Column(String(10), nullable=True)   # A, B, C, A+
    lot_reference  = Column(String(100), nullable=True)
    product_interest = Column(String(200), nullable=True)  # legacy free-text field

    # ── Call tracking ─────────────────────────────────────────────────────
    called_by         = Column(String(50), nullable=False)
    call_date         = Column(DateTime, default=app_now)
    call_outcome      = Column(String(30), nullable=True)  # interested, not_interested, callback, order_placed, no_answer, do_not_call
    quantity_required = Column(Integer, nullable=True)
    budget            = Column(Numeric(12, 2), nullable=True)
    next_followup     = Column(DateTime, nullable=True)
    whatsapp_sent     = Column(Boolean, default=False)
    notes             = Column(Text, nullable=True)
    created_at        = Column(DateTime, default=app_now)

    # ── Mobile PWA v2 (sprint 2026-05) — cross-module integration ────────
    call_source       = Column(String(20), nullable=False, default='prospect')
    crm_contact_id    = Column(UUID(as_uuid=True), ForeignKey("crm_contacts.id"), nullable=True)
    lot_id            = Column(UUID(as_uuid=True), ForeignKey("lots.id"), nullable=True)
    lot_line_item_id  = Column(UUID(as_uuid=True), ForeignKey("lot_line_items.id"), nullable=True)
    dealer_order_id   = Column(UUID(as_uuid=True), ForeignKey("dealer_orders.id"), nullable=True)
    crm_quote_id      = Column(UUID(as_uuid=True), ForeignKey("crm_quotes.id"), nullable=True)
    idempotency_key   = Column(String(64), nullable=True, unique=True)
    device_id         = Column(String(100), nullable=True)
    latitude          = Column(Numeric(10, 7), nullable=True)
    longitude         = Column(Numeric(10, 7), nullable=True)
    call_duration_secs = Column(Integer, nullable=True)
    is_active         = Column(Boolean, nullable=False, default=True)
    deleted_at        = Column(DateTime, nullable=True)

    dealer = relationship("Dealer", foreign_keys=[dealer_id])


class TelecallingAssignment(Base):
    """Daily pre-assigned call queue. Written by sales_manager;
    consumed by mobile PWA via sp_telecalling_daily_queue."""
    __tablename__ = "telecalling_assignments"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_username  = Column(String(50), nullable=False)
    lead_phone      = Column(String(20), nullable=False)
    dealer_id       = Column(UUID(as_uuid=True), ForeignKey("dealers.id"), nullable=True)
    crm_contact_id  = Column(UUID(as_uuid=True), ForeignKey("crm_contacts.id"), nullable=True)
    customer_name   = Column(String(200), nullable=True)
    city            = Column(String(100), nullable=True)
    category        = Column(String(50), nullable=True)
    priority        = Column(String(10), nullable=False, default='normal')
    assigned_by     = Column(String(50), nullable=False)
    assigned_at     = Column(DateTime, nullable=False, default=app_now)
    due_date        = Column(DateTime, nullable=False)
    status          = Column(String(20), nullable=False, default='pending')
    call_record_id  = Column(UUID(as_uuid=True), ForeignKey("telecalling_records.id"), nullable=True)
    notes           = Column(Text, nullable=True)
    is_active       = Column(Boolean, nullable=False, default=True)
    deleted_at      = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, default=app_now)
