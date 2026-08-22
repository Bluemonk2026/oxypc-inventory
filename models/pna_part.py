import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from database import Base
from utils.timezone import app_now


class DevicePNAPart(Base):
    """A part marked PNA (Part Not Available) for one tag number.

    Raised from the Parts Consumption table on Device Detail and from the
    Request Parts modal on the L3/L4 board, and counted back on the L1/L2 and
    L3/L4 queues so a supervisor can see which tags are stalled waiting on
    parts nobody can source.

    Kept as its own table rather than a flag on part_requests because a part
    can be PNA without a request ever having been raised for it — that is the
    common case, and the whole point of the marking.

    Unmarking sets is_active=False rather than deleting the row: the fact that
    a part was once PNA is history a supervisor may need to explain a delay.
    """

    __tablename__ = "device_pna_parts"
    __table_args__ = (
        UniqueConstraint("device_id", "part_name", name="uq_device_pna_part"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"),
                       nullable=False, index=True)
    barcode = Column(String(100), nullable=True, index=True)

    part_name = Column(String(150), nullable=False)
    part_category = Column(String(100), nullable=True)
    part_id = Column(UUID(as_uuid=True), ForeignKey("spare_parts.id"), nullable=True)

    # parts_consumption | l3l4 — which screen the mark came from.
    source = Column(String(30), nullable=False, default="parts_consumption")

    marked_by = Column(String(50), nullable=True)
    marked_at = Column(DateTime, default=app_now)
    cleared_by = Column(String(50), nullable=True)
    cleared_at = Column(DateTime, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True,
                       server_default=text("true"), index=True)
