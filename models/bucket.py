import uuid
import secrets
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, Integer, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from database import Base


def _new_bucket_number() -> str:
    return f"BKT{secrets.randbelow(90_000_000) + 10_000_000:08d}"


class Bucket(Base):
    __tablename__ = "buckets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bucket_number = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=True)
    location = Column(String(100), nullable=True)
    category = Column(String(50), nullable=True)
    # status: stock_in | trc_pending | validated
    status = Column(String(20), nullable=False, default="stock_in")
    received_qty = Column(Integer, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=app_now)
    updated_at = Column(DateTime, default=app_now, onupdate=app_now)

    # Movement / production tracking (Batch D)
    location_id = Column(UUID(as_uuid=True), ForeignKey("storage_locations.id"), nullable=True, index=True)
    assigned_to_production = Column(Boolean, nullable=False, default=False)
    assigned_to_production_by = Column(String(50), nullable=True)
    assigned_to_production_at = Column(DateTime, nullable=True)
