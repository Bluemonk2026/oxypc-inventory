import uuid
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class PartRequest(Base):
    """A spare-part request raised by an L1/L2/L3 engineer from the device
    Parts Consumption section. Actioned by the Spare Parts Manager on the
    Part Master page (Handover / Not In Stock / Procure)."""
    __tablename__ = "part_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    work_order_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=True)
    work_id = Column(String(12), nullable=True)            # engineer WorkID snapshot
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    barcode = Column(String(100), nullable=True)
    stage = Column(String(5), nullable=True)               # l1 | l2 | l3 (page that raised it)

    part_id = Column(UUID(as_uuid=True), ForeignKey("spare_parts.id"), nullable=True)
    part_name = Column(String(150), nullable=False)        # fixed-list label snapshot

    requested_by = Column(String(50), nullable=True)       # engineer username
    engineer_name = Column(String(100), nullable=True)

    qty_requested = Column(Integer, nullable=False, default=1)
    qty_handed_over = Column(Integer, nullable=False, default=0)

    # requested | handed_over | not_in_stock | procure
    status = Column(String(20), nullable=False, default="requested", index=True)

    created_at = Column(DateTime, default=app_now)
    actioned_at = Column(DateTime, nullable=True)
    actioned_by = Column(String(50), nullable=True)

    device = relationship("Device", lazy="select")
    part = relationship("SparePart", lazy="select")


class PartSourcingRequest(Base):
    """Raised when the Spare Parts Manager clicks 'Procure' on a part request.
    Appears in the CRM Dashboard 'Pending Requests For Part Sourcing' (Sales
    Manager closes the deal) and mirrored read-only on the Part Master page."""
    __tablename__ = "part_sourcing_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    part_request_id = Column(UUID(as_uuid=True), ForeignKey("part_requests.id"), nullable=True)
    part_id = Column(UUID(as_uuid=True), ForeignKey("spare_parts.id"), nullable=True)
    part_code = Column(String(20), nullable=True)
    part_name = Column(String(150), nullable=False)

    qty_requested = Column(Integer, nullable=False, default=1)
    qty_sourced = Column(Integer, nullable=False, default=0)

    raised_by = Column(String(50), nullable=True)          # spare parts manager username
    status = Column(String(10), nullable=False, default="open", index=True)  # open | closed
    source_deal_id = Column(String(50), nullable=True)     # entered at Close Deal

    created_at = Column(DateTime, default=app_now)
    closed_at = Column(DateTime, nullable=True)
    closed_by = Column(String(50), nullable=True)
