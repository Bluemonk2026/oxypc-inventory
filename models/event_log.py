"""
EventLog model — append-only record of every published event.
"""
import uuid
from datetime import datetime
from utils.timezone import app_now

from sqlalchemy import Column, String, Integer, DateTime, JSON, Index
from sqlalchemy.dialects.postgresql import UUID

from database import Base


class EventLog(Base):
    __tablename__ = "event_log"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type       = Column(String(50), nullable=False)
    payload          = Column(JSON, nullable=False)
    source_module    = Column(String(50), nullable=True)
    published_at     = Column(DateTime, default=app_now, nullable=False)
    webhook_attempts = Column(Integer, default=0, nullable=False)
    last_attempt_at  = Column(DateTime, nullable=True)
    last_status_code = Column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_event_log_event_type",   "event_type"),
        Index("ix_event_log_published_at", "published_at"),
    )
