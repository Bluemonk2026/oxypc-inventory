import uuid
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class StockValidation(Base):
    """Stock-In validation record (the 'Stock Validate' action): quantities and
    condition received, optional reassignment to a department, and notes."""
    __tablename__ = "stock_validations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    barcode = Column(String(100), nullable=True)

    qty_received = Column(Integer, nullable=True)
    condition_received = Column(String(50), nullable=True)
    reassign_department = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)

    validated_by = Column(String(50), nullable=True)
    validated_at = Column(DateTime, default=app_now)

    device = relationship("Device", lazy="select")
