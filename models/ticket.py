import uuid
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from database import Base
from utils.timezone import app_now


class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(String(10), unique=True, nullable=False, index=True)
    status = Column(String(10), nullable=False, default="Open")  # Open | Closed
    raised_by = Column(String(50), nullable=False, index=True)
    raised_on = Column(DateTime, nullable=False, default=app_now)
    feedback = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=app_now)
    updated_at = Column(DateTime, default=app_now, onupdate=app_now)
