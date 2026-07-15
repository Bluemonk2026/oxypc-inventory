import uuid
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class TelecallerDispatchRequest(Base):
    """A telecaller's request to dispatch/sell a ready-to-sale device.

    Raised from the Ready to Sale page (#21); approved on the Ready to Dispatch
    page (#20). Approval enables the Sell button on Ready to Sale.
    """
    __tablename__ = "telecaller_dispatch_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    barcode = Column(String(100), nullable=True)

    telecaller_username = Column(String(50), nullable=True)
    telecaller_name = Column(String(100), nullable=True)

    qty_requested = Column(Integer, nullable=False, default=1)
    qty_available = Column(Integer, nullable=False, default=1)
    grade = Column(String(10), nullable=True)

    status = Column(String(20), nullable=False, default="requested", index=True)  # requested | approved | rejected
    rejected_notes = Column(String(500), nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejected_by = Column(String(50), nullable=True)

    # ── Lot-level requests (Model Summary "Request" button on Ready to Sale) ──
    # source distinguishes a bulk request raised against a model group from the
    # regular per-device Request; model_name/model_make identify the group for
    # the TRC Dashboard's separate "Sales Request for Lot" table.
    source = Column(String(20), nullable=False, default="device")  # device | lot
    model_name = Column(String(150), nullable=True)
    model_make = Column(String(100), nullable=True)

    created_at = Column(DateTime, default=app_now)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String(50), nullable=True)

    device = relationship("Device", lazy="select")
