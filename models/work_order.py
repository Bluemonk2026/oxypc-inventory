import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class WorkOrder(Base):
    """A work assignment created when a device is moved to an engineer via Stock Transfer.

    Carries a unique 12-digit WorkID and drives the repair Pending list
    (WorkID first column + Timeline = days pending since the day after assignment).
    """
    __tablename__ = "work_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_id = Column(String(12), unique=True, nullable=False, index=True)  # 12-digit numeric

    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    barcode = Column(String(100), nullable=True)          # snapshot for fast display

    stage = Column(String(5), nullable=False)             # "l1" | "l2" | "l3"
    assigned_role = Column(String(30), nullable=True)     # e.g. l1_engineer
    assigned_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    assigned_username = Column(String(50), nullable=True)
    assigned_name = Column(String(100), nullable=True)

    status = Column(String(20), nullable=False, default="pending")  # pending | in_progress | completed
    source_transfer_id = Column(UUID(as_uuid=True), ForeignKey("stock_transfers.id"), nullable=True)

    assigned_at = Column(DateTime, nullable=False, default=app_now)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=app_now)

    device = relationship("Device", lazy="select")
