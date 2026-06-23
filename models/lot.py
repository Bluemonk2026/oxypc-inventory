import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, Numeric, Integer, Text, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class Lot(Base):
    __tablename__ = "lots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lot_number = Column(String(100), unique=True, nullable=False, index=True)
    supplier_name = Column(String(200), nullable=False)

    # ── GRN Details ───────────────────────────────────────────────────────────
    grn_system_number = Column(String(50), nullable=True)       # e.g. GRN-178
    grn_number_new = Column(Integer, nullable=True)             # numeric GRN
    grn_date = Column(DateTime, nullable=True)                  # Date of material received
    invoice_date = Column(DateTime, nullable=True)
    invoice_no = Column(String(100), nullable=True)
    invoice_value = Column(Numeric(14, 2), nullable=True)       # Total invoice value
    taxable_amount = Column(Numeric(14, 2), nullable=True)      # Taxable amount

    # ── GST Fields ────────────────────────────────────────────────────────────
    sgst = Column(Numeric(12, 2), nullable=True)                # State GST amount
    cgst = Column(Numeric(12, 2), nullable=True)                # Central GST amount
    igst = Column(Numeric(12, 2), nullable=True)                # Integrated GST amount

    # ── Logistics ─────────────────────────────────────────────────────────────
    vehicle_number = Column(String(30), nullable=True)
    e_way_bill = Column(String(50), nullable=True)
    po_number = Column(String(100), nullable=True)              # Purchase Order number
    vendor_name = Column(String(200), nullable=True)            # Vendor from PO (may differ from supplier)

    # ── Financial ─────────────────────────────────────────────────────────────
    buying_price = Column(Numeric(12, 2), nullable=False)       # Total lot cost
    qty = Column(Integer, nullable=False)
    purchase_date = Column(DateTime, nullable=False)

    notes = Column(Text, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=app_now)
    is_trashed = Column(Boolean, nullable=False, default=False, server_default='false')
    trashed_at = Column(DateTime, nullable=True)

    devices = relationship("Device", back_populates="lot", lazy="select")
    spare_parts_consumption = relationship("SparePartConsumption", back_populates="lot", lazy="select")
    line_items = relationship("LotLineItem", back_populates="lot", lazy="select", cascade="all, delete-orphan")


class LotLineItem(Base):
    __tablename__ = "lot_line_items"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lot_id       = Column(UUID(as_uuid=True), ForeignKey("lots.id"), nullable=False, index=True)

    # Category identity
    sub_category = Column(String(50), nullable=False)        # Laptop / Desktop / Monitor / TFT / UPS etc.
    brand        = Column(String(50), nullable=True)
    model        = Column(String(100), nullable=True)

    # Spec details (as per invoice)
    cpu          = Column(String(100), nullable=True)         # e.g. Intel Core i5-8250U
    generation   = Column(String(50), nullable=True)          # e.g. 8th Gen
    ram_gb       = Column(Integer, nullable=True)             # e.g. 8
    has_ram      = Column(Boolean, default=True, nullable=True)   # False = no RAM (bare chassis)
    storage_gb   = Column(Integer, nullable=True)
    storage_type = Column(String(20), nullable=True)          # SSD / HDD / NVMe / None
    has_storage  = Column(Boolean, default=True, nullable=True)   # False = no storage
    screen_size  = Column(String(20), nullable=True)
    grade        = Column(String(10), nullable=True)          # A/B/C/D

    # Financial
    unit_price   = Column(Numeric(12, 2), nullable=False)
    qty          = Column(Integer, nullable=False, default=1)

    notes        = Column(Text, nullable=True)
    created_at   = Column(DateTime, default=app_now)

    lot = relationship("Lot", back_populates="line_items")
