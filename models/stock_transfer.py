import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class StockTransfer(Base):
    __tablename__ = "stock_transfers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)

    # ── Transfer Direction ────────────────────────────────────────────────────
    transfer_type = Column(String(30), nullable=False)    # "trc_to_showroom" | "showroom_to_trc"
    from_warehouse = Column(String(100), nullable=False)
    to_warehouse = Column(String(100), nullable=False)

    # ── Personnel ─────────────────────────────────────────────────────────────
    transferred_by = Column(String(100), nullable=True)   # Order By / sender
    received_by = Column(String(100), nullable=True)      # Receiver Name
    department = Column(String(100), nullable=True)        # e.g. L1/L2 Engineer

    # ── Device snapshot at time of transfer ──────────────────────────────────
    barcode = Column(String(50), nullable=True)
    serial_no = Column(String(100), nullable=True)
    make = Column(String(50), nullable=True)
    model = Column(String(100), nullable=True)
    cpu = Column(String(50), nullable=True)
    generation = Column(String(20), nullable=True)
    ram = Column(String(20), nullable=True)
    hdd = Column(String(20), nullable=True)
    category = Column(String(50), nullable=True)
    lot_number = Column(String(20), nullable=True)
    product_stage = Column(String(50), nullable=True)     # e.g. Finished Good

    # ── Meta ──────────────────────────────────────────────────────────────────
    transfer_date = Column(DateTime, nullable=False, default=app_now)
    notes = Column(Text, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=app_now)

    device = relationship("Device", lazy="select")
