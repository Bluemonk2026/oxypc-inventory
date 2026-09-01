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
    customer_address = Column(Text, nullable=True)
    invoice_no = Column(String(50), nullable=True)
    # Widened from 20: Payment Mode now sources from Master Data's Dropdown
    # Configuration (payment_mode category, e.g. "Bank Transfer (NEFT/RTGS/IMPS)"
    # at 30 chars), not the old hardcoded cash/upi/card/credit codes.
    payment_mode = Column(String(50), nullable=True)
    sold_by = Column(String(50), nullable=True, index=True)
    # Who gets CREDIT for the sale, which is not the same thing as sold_by —
    # sold_by records the logged-in operator who keyed the entry. Free text
    # rather than a user FK because the people credited (floor staff, walk-in
    # counter) do not all have platform logins.
    sales_person = Column(String(100), nullable=True, index=True)
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
    # ── Warranty at sale (Phase 1a) ──────────────────────────────────────────────
    warranty_type       = Column(String(20), default="none")   # none/30_days/6_months/1_year
    warranty_expires_at = Column(DateTime, nullable=True)       # server-computed from sold_at + duration
    # ── Sales channel (Admin Dashboard analytics) ─────────────────────────────
    sale_channel = Column(String(20), nullable=True)   # procurement / telecaller / showroom
    # ── Selling company, resolved and SNAPSHOTTED at sale time (2026-08) ──────
    # Matched from the sold device's entity to the Company Setting row tagged
    # with that same entity. company_id is kept for traceability/joins, but
    # the invoice-relevant fields are copied here too — a genuine snapshot,
    # not just a foreign key — because a foreign key alone would still change
    # if someone later edits THAT SAME company's name/GSTIN/address rather
    # than switching companies. A Tax Invoice/Delivery Challan is a legal
    # document: it must always show the company exactly as it was on the sale
    # date, regardless of edits or deactivation afterward. Nullable: sales
    # recorded before this column existed have no snapshot and print.py/
    # waybill.py fall back to the pre-existing "oldest active company" live
    # lookup for those (see get_company_settings).
    company_id           = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    company_name         = Column(String(200), nullable=True)
    company_address      = Column(String(500), nullable=True)
    company_gstin        = Column(String(20), nullable=True)
    company_state        = Column(String(100), nullable=True)
    company_state_code   = Column(String(5), nullable=True)
    company_phone        = Column(String(50), nullable=True)
    company_email        = Column(String(100), nullable=True)

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
    # RMA capture (Phase 1b)
    return_type         = Column(String(20), default="customer")   # customer/dealer
    serial_captured     = Column(String(100), nullable=True)       # serial/barcode scanned at RMA time
    warranty_status     = Column(String(20), nullable=True)        # in_warranty/out_of_warranty/no_warranty (server-computed)
    complaint_text      = Column(Text, nullable=True)               # RMA complaint/issue description
    # Inventory Manager's "Return Stock" table (Verify action) — captured once
    # the returned tag has actually been repaired, distinct from refund_amount
    # above (what the CUSTOMER got back) and from Part Cost (derived on read
    # from SparePartConsumption, not stored here).
    repair_cost         = Column(Numeric(12, 2), nullable=True)
    labour_cost         = Column(Numeric(12, 2), nullable=True)

    sale = relationship("Sale", back_populates="returns")
