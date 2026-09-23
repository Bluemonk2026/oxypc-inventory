import uuid
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class Deal(Base):
    """All Deals — a simple deal header against a CRM Account (+ one of its
    Locations), with a line-items table whose totals roll up into Amount.

    Deal ID follows the CRMPurchaseOrder po_number convention (max-suffix
    derivation + retry-on-IntegrityError at the call site, see
    routers/deals.py's _next_deal_number) rather than a plain count, since
    count-based numbering collides after any row is ever deleted.
    """
    __tablename__ = "deals"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deal_number  = Column(String(30), unique=True, nullable=False, index=True)  # DEAL-2026-0001

    contact_id   = Column(UUID(as_uuid=True), ForeignKey("crm_contacts.id"), nullable=False, index=True)
    location_id  = Column(UUID(as_uuid=True), ForeignKey("crm_contact_locations.id"), nullable=True, index=True)

    amount       = Column(Numeric(14, 2), nullable=False, default=0)

    created_by   = Column(String(50), nullable=True)
    created_at   = Column(DateTime, default=app_now)

    # Deal lifecycle — pending until the Approve action is taken.
    status       = Column(String(20), nullable=False, default="pending")  # pending/approved
    approved_by  = Column(String(50), nullable=True)
    approved_at  = Column(DateTime, nullable=True)

    # Same pending/paid vocabulary as CRMQuote/CRMPurchaseOrder.payment_status.
    payment_status = Column(String(20), nullable=False, default="pending")  # pending/paid
    paid_by        = Column(String(50), nullable=True)
    paid_at        = Column(DateTime, nullable=True)

    contact  = relationship("CRMContact")
    location = relationship("CRMContactLocation")
    items    = relationship("DealItem", back_populates="deal",
                             cascade="all, delete-orphan", order_by="DealItem.sort_order")


class DealItem(Base):
    """A line item on a Deal — Item Name / Quantity / Unit Price / Total
    Price. Managed as line-items (cascade delete-orphan), mirroring
    CRMQuoteItem / CRMPOLineItem."""
    __tablename__ = "deal_items"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deal_id     = Column(UUID(as_uuid=True), ForeignKey("deals.id"), nullable=False, index=True)
    item_name   = Column(String(200), nullable=False)
    quantity    = Column(Integer, nullable=False, default=1)
    unit_price  = Column(Numeric(12, 2), nullable=False, default=0)
    total_price = Column(Numeric(14, 2), nullable=False, default=0)
    sort_order  = Column(Integer, default=0)

    deal = relationship("Deal", back_populates="items")
