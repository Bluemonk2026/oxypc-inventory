import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, Numeric, Integer, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class SparePart(Base):
    __tablename__ = "spare_parts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    part_code = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(150), nullable=False)
    category = Column(String(30), nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False, default=0)
    qty_in_stock = Column(Integer, nullable=False, default=0)
    min_stock_alert = Column(Integer, nullable=False, default=5)
    supplier = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=app_now)

    purchases = relationship("SparePartPurchase", back_populates="part", lazy="select")
    consumptions = relationship("SparePartConsumption", back_populates="part", lazy="select")


class SparePartPurchase(Base):
    __tablename__ = "spare_parts_purchases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    part_id = Column(UUID(as_uuid=True), ForeignKey("spare_parts.id"), nullable=False)
    qty = Column(Integer, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    total_price = Column(Numeric(12, 2), nullable=False)
    supplier = Column(String(100), nullable=True)
    purchase_date = Column(DateTime, nullable=False, default=app_now)
    invoice_no = Column(String(50), nullable=True)
    purchased_by = Column(String(50), nullable=True)

    part = relationship("SparePart", back_populates="purchases")


class SparePartConsumption(Base):
    __tablename__ = "spare_parts_consumption"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True)
    lot_id = Column(UUID(as_uuid=True), ForeignKey("lots.id"), nullable=True)
    repair_job_id = Column(UUID(as_uuid=True), ForeignKey("repair_jobs.id"), nullable=True, index=True)
    part_id = Column(UUID(as_uuid=True), ForeignKey("spare_parts.id"), nullable=False)
    qty_used = Column(Integer, nullable=False)
    unit_cost = Column(Numeric(10, 2), nullable=False)
    total_cost = Column(Numeric(12, 2), nullable=False)
    used_by = Column(String(50), nullable=True)
    used_at = Column(DateTime, default=app_now)
    stage = Column(String(20), nullable=True)
    notes = Column(Text, nullable=True)

    device = relationship("Device", back_populates="spare_parts_consumption")
    lot = relationship("Lot", back_populates="spare_parts_consumption")
    part = relationship("SparePart", back_populates="consumptions")
    repair_job = relationship("RepairJob", back_populates="spare_part_consumptions", foreign_keys=[repair_job_id])


class RAMTracking(Base):
    __tablename__ = "ram_tracking"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action = Column(String(20), nullable=False)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True)
    destination_device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True)
    ram_gb = Column(Integer, nullable=True)
    ram_type = Column(String(20), nullable=True)
    by_user = Column(String(50), nullable=True)
    at = Column(DateTime, default=app_now)
    notes = Column(Text, nullable=True)

    device = relationship("Device", back_populates="ram_tracking", foreign_keys=[device_id])
