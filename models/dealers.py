import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Boolean, Numeric, Integer, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class Dealer(Base):
    __tablename__ = "dealers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dealer_code = Column(String(20), unique=True, nullable=False, index=True)
    business_name = Column(String(200), nullable=False)
    first_name = Column(String(100), nullable=True)   # Contact first name (for WA personalisation)
    last_name = Column(String(100), nullable=True)    # Contact last name
    contact_person = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=True)
    whatsapp_number = Column(String(20), nullable=True)
    email = Column(String(100), nullable=True)
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    pincode = Column(String(10), nullable=True)
    gstin = Column(String(20), nullable=True)
    dealer_type = Column(String(30), default="retail")  # retail, wholesale, corporate, service
    credit_limit = Column(Numeric(14, 2), default=0)
    outstanding_amount = Column(Numeric(14, 2), default=0)
    total_purchases = Column(Numeric(14, 2), default=0)
    last_sale_date = Column(DateTime, nullable=True)
    last_sale_amount = Column(Numeric(14, 2), nullable=True)
    preferred_categories = Column(String(200), nullable=True)  # comma-separated: Laptop, Desktop
    notes = Column(Text, nullable=True)
    status = Column(String(20), default="active")  # active, inactive, blacklisted
    assigned_to = Column(String(50), nullable=True)  # sales exec username
    created_by = Column(String(50), nullable=True)
    source     = Column(String(200), nullable=True)   # e.g. "WhatsApp Group: Dealers Delhi"
    added_by   = Column(String(50),  nullable=True)   # username who added this dealer
    created_at = Column(DateTime, default=app_now)
    updated_at = Column(DateTime, default=app_now, onupdate=app_now)

    calls = relationship("DealerCall", back_populates="dealer", lazy="select")
    assignments = relationship("DealerAssignment", back_populates="dealer", lazy="select")


class DealerAssignment(Base):
    __tablename__ = "dealer_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dealer_id = Column(UUID(as_uuid=True), ForeignKey("dealers.id"), nullable=False)
    assigned_to = Column(String(50), nullable=False)  # username of sales exec
    assigned_by = Column(String(50), nullable=False)
    assigned_at = Column(DateTime, default=app_now)
    is_active = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)

    dealer = relationship("Dealer", back_populates="assignments")


class DealerCall(Base):
    __tablename__ = "dealer_calls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dealer_id = Column(UUID(as_uuid=True), ForeignKey("dealers.id"), nullable=False)
    called_by = Column(String(50), nullable=False)  # username
    call_date = Column(DateTime, default=app_now)
    call_type = Column(String(20), default="outbound")  # outbound, inbound
    call_mode = Column(String(20), default="phone")  # phone, whatsapp, in_person
    duration_mins = Column(Integer, nullable=True)
    call_outcome = Column(String(30), nullable=True)  # interested, not_interested, callback, order_placed, no_answer, followup
    items_discussed = Column(Text, nullable=True)  # what products discussed
    quote_given = Column(Numeric(12, 2), nullable=True)
    next_followup_date = Column(DateTime, nullable=True, index=True)
    whatsapp_sent = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=app_now)

    dealer = relationship("Dealer", back_populates="calls")


class DealerOrder(Base):
    __tablename__ = "dealer_orders"
    __table_args__ = (
        Index(
            "ix_dealer_orders_overdue",
            "payment_due_date",
            "due_amount",
            postgresql_where=text("due_amount > 0 AND payment_due_date IS NOT NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dealer_id = Column(UUID(as_uuid=True), ForeignKey("dealers.id"), nullable=False)
    order_number = Column(String(30), unique=True, nullable=False)
    order_date = Column(DateTime, default=app_now)
    items_description = Column(Text, nullable=True)
    total_amount = Column(Numeric(14, 2), default=0)
    paid_amount = Column(Numeric(14, 2), default=0)
    due_amount = Column(Numeric(14, 2), default=0)
    payment_due_date = Column(DateTime, nullable=True)
    payment_mode = Column(String(20), nullable=True)  # cash, bank, credit, upi
    invoice_number = Column(String(50), nullable=True)
    invoice_sent_whatsapp = Column(Boolean, default=False)
    payment_reminder_sent = Column(Boolean, default=False)
    status = Column(String(20), default="pending")  # pending, confirmed, delivered, cancelled, paid
    notes = Column(Text, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=app_now)

    dealer = relationship("Dealer")


class DealerCreditNote(Base):
    """Goods return / credit note issued against a dealer order."""
    __tablename__ = "dealer_credit_notes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credit_number = Column(String(30), unique=True, nullable=False, index=True)
    dealer_id = Column(UUID(as_uuid=True), ForeignKey("dealers.id"), nullable=False, index=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("dealer_orders.id"), nullable=True, index=True)
    credit_date = Column(DateTime, default=app_now)
    amount = Column(Numeric(14, 2), nullable=False)
    reason = Column(String(200), nullable=True)
    items_description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=app_now)

    # Application tracking — set when CN balance is applied against an open order
    is_applied = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    applied_at = Column(DateTime, nullable=True)
    applied_to_order_id = Column(UUID(as_uuid=True), ForeignKey("dealer_orders.id"), nullable=True)

    dealer = relationship("Dealer", lazy="select")
    order = relationship("DealerOrder", foreign_keys=[order_id], lazy="select")
    applied_to_order = relationship("DealerOrder", foreign_keys=[applied_to_order_id], lazy="select")
