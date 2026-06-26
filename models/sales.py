import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, Numeric, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base



class Sale(Base):
    __tablename__ = "sales"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sale_number = Column(String(20), unique=True, nullable=False, index=True)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    sale_price = Column(Numeric(12, 2), nullable=False)
    customer_name = Column(String(100), nullable=True)
    customer_phone = Column(String(20), nullable=True)
    customer_state = Column(String(100), nullable=True)  # For GST state determination (intra/inter)
    invoice_no = Column(String(50), nullable=True)
    payment_mode = Column(String(20), nullable=True)
    sold_by = Column(String(50), nullable=True, index=True)
    sold_at = Column(DateTime, default=app_now)
    notes = Column(Text, nullable=True)
    # ── Transport ────────────────────────────────────────────────────────────────
    payment_reference = Column(String(100), nullable=True)   # cheque no / UTR / NEFT ref
    transport_mode    = Column(String(30), nullable=True)    # courier / hand_delivery / self_pickup
    transport_via     = Column(String(100), nullable=True)   # courier company name
    tracking_number   = Column(String(100), nullable=True)   # AWB / tracking number
    dispatch_date     = Column(DateTime, nullable=True)      # when dispatched
    delivery_status   = Column(String(30), nullable=True)    # pending / dispatched / delivered
    # ── Invoice / PO upload ──────────────────────────────────────────────────────
    invoice_file_path = Column(String(500), nullable=True)   # relative path to uploaded PDF

    device = relationship("Device", back_populates="sales")
    returns = relationship("Return", back_populates="sale", lazy="select")


class Return(Base):
    __tablename__ = "returns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sale_id = Column(UUID(as_uuid=True), ForeignKey("sales.id"), nullable=False, index=True)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    return_date         = Column(DateTime, default=app_now)
    reason              = Column(Text, nullable=True)
    condition_on_return = Column(String(50), nullable=True)
    action_taken        = Column(String(30), nullable=True)   # restock / scrap / credit
    reentered_stage     = Column(String(50), nullable=True)   # iqc (default)
    processed_by        = Column(String(50), nullable=True)
    refund_amount       = Column(Numeric(12, 2), nullable=True)
    notes               = Column(Text, nullable=True)
    # Approval workflow (migration: 20260515_1000)
    approval_status     = Column(String(20), nullable=True, default='pending')   # pending/approved/rejected
    approved_by         = Column(String(50), nullable=True)
    approved_at         = Column(DateTime, nullable=True)
    rejection_reason    = Column(Text, nullable=True)

    sale = relationship("Sale", back_populates="returns")
