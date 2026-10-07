"""Manual selling-price override for a Ready to Sale As-Is Lot.

An As-Is Lot's Min Selling Price is a LOT-level total (Lot Price + margin), so
it can't be stored in Device.min_selling_price — that column is per-tag, and a
lot total written there would become each tag's price the moment the lot is
opened back into the Tag table. One row per (lot, sub-lot) holds the override
set by the As-Is table's "Set price" button; no row means "use the formula".
"""
import uuid

from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from database import Base
from utils.timezone import app_now


class AsIsLotPrice(Base):
    __tablename__ = "as_is_lot_prices"
    __table_args__ = (
        UniqueConstraint("lot_id", "sub_lot_number", name="uq_as_is_lot_prices_lot_sublot"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lot_id = Column(UUID(as_uuid=True), ForeignKey("lots.id", ondelete="CASCADE"),
                    nullable=False, index=True)
    sub_lot_number = Column(String(50), nullable=False)
    min_selling_price = Column(Numeric(12, 2), nullable=True)
    max_selling_price = Column(Numeric(12, 2), nullable=True)
    updated_by = Column(String(50), nullable=True)
    updated_at = Column(DateTime, default=app_now, onupdate=app_now)
