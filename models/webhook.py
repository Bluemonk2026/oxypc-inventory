"""
Webhook model — outbound HTTP delivery configuration.

Each row represents one subscriber URL that receives signed HTTP POSTs
for its subscribed event types.
"""
import uuid
import hashlib
from datetime import datetime
from utils.timezone import app_now

from sqlalchemy import Column, String, Boolean, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID

from database import Base


class Webhook(Base):
    __tablename__ = "webhooks"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name        = Column(String(100), nullable=False)
    url         = Column(String(500), nullable=False)
    secret_hash = Column(String(64), nullable=False)
    event_types = Column(JSON, nullable=False, default=list)
    is_active   = Column(Boolean, default=True, nullable=False)
    created_by  = Column(String(50), nullable=False)
    created_at  = Column(DateTime, default=app_now, nullable=False)
    deleted_at  = Column(DateTime, nullable=True)

    @staticmethod
    def hash_secret(raw_secret: str) -> str:
        """SHA-256 hash of the signing secret for safe storage."""
        return hashlib.sha256(raw_secret.encode()).hexdigest()
