"""
Spare-part sales — the parts-side equivalent of models/sales.py.

Two tables:
  PartSaleRequest — raised on "Ready to Sale Parts", approved/rejected on
                    "Parts Sale Request". An APPROVED, not-yet-consumed
                    request is what unlocks the Sell button for that part.
  PartSale        — a completed spare-part sale, listed on "Spare Part Sales".

Field naming mirrors models/sales.Sale wherever the concept is the same so
the two sale flows stay recognisably identical.
"""
import uuid
from sqlalchemy import (Column, String, Integer, Numeric, DateTime, Text,
                        Boolean, ForeignKey)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base
from utils.timezone import app_now


class PartSaleRequest(Base):
    """A request to sell a spare part, awaiting approval."""
    __tablename__ = "part_sale_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    part_id = Column(UUID(as_uuid=True), ForeignKey("spare_parts.id"),
                     nullable=False, index=True)
    # Snapshot of the part at request time — the master row can change later.
    part_code = Column(String(20), nullable=True)
    part_name = Column(String(150), nullable=True)
    make = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)

    qty_requested = Column(Integer, nullable=False, default=1)
    # pending | approved | rejected
    status = Column(String(20), nullable=False, default="pending", index=True)
    # Set once a sale has been made against this approval, so one approval
    # authorises one sale rather than unlocking the part permanently.
    is_consumed = Column(Boolean, nullable=False, default=False)

    requested_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=app_now)
    actioned_at = Column(DateTime, nullable=True)
    actioned_by = Column(String(50), nullable=True)
    reject_reason = Column(String(300), nullable=True)

    part = relationship("SparePart", lazy="select")


class PartSale(Base):
    """A completed spare-part sale."""
    __tablename__ = "part_sales"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sale_number = Column(String(20), unique=True, nullable=False, index=True)
    part_id = Column(UUID(as_uuid=True), ForeignKey("spare_parts.id"),
                     nullable=False, index=True)
    request_id = Column(UUID(as_uuid=True), ForeignKey("part_sale_requests.id"),
                        nullable=True)
    # Snapshot — a sold record must stay accurate even if the master changes.
    part_code = Column(String(20), nullable=True)
    part_name = Column(String(150), nullable=True)
    make = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)

    qty = Column(Integer, nullable=False, default=1)
    stock_unit_price = Column(Numeric(10, 2), nullable=True)   # cost basis at sale time
    sale_unit_price = Column(Numeric(10, 2), nullable=False, default=0)
    total_sale_price = Column(Numeric(12, 2), nullable=False, default=0)
    margin = Column(Numeric(12, 2), nullable=True)             # (sale - stock) x qty

    # ── Customer / invoice (mirrors Sale) ────────────────────────────────────
    customer_name = Column(String(100), nullable=True)
    customer_phone = Column(String(20), nullable=True)
    customer_state = Column(String(100), nullable=True)
    customer_address = Column(Text, nullable=True)
    invoice_no = Column(String(50), nullable=True)
    # Widened from 20: Payment Mode now sources from Master Data's Dropdown
    # Configuration (payment_mode category, e.g. "Bank Transfer (NEFT/RTGS/IMPS)"
    # at 30 chars), not the old hardcoded cash/upi/card/credit codes.
    payment_mode = Column(String(50), nullable=True)
    payment_reference = Column(String(100), nullable=True)
    sold_by = Column(String(50), nullable=True, index=True)
    # Credited salesperson, distinct from sold_by (the logged-in operator).
    # Mirrors Sale.sales_person so both sale types report the same way.
    sales_person = Column(String(100), nullable=True, index=True)
    sold_at = Column(DateTime, default=app_now)
    notes = Column(Text, nullable=True)

    # ── Transport (mirrors Sale) ─────────────────────────────────────────────
    transport_mode = Column(String(30), nullable=True)
    transport_via = Column(String(100), nullable=True)
    tracking_number = Column(String(100), nullable=True)
    dispatch_date = Column(DateTime, nullable=True)
    delivery_status = Column(String(30), nullable=True)
    invoice_file_path = Column(String(500), nullable=True)

    sale_channel = Column(String(20), nullable=True)

    part = relationship("SparePart", lazy="select")
