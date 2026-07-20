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
    # Admin's closing note — captured on the Close action so a ticket is never
    # closed without a reason attached.
    notes = Column(Text, nullable=True)
    # Up to two screenshots attached when raising. Stored as /uploads/... paths,
    # not blobs, matching how every other attachment in this app is handled.
    # Additive and nullable, so db_validator provisions them at startup.
    photo1_path = Column(String(255), nullable=True)
    photo2_path = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=app_now)
    updated_at = Column(DateTime, default=app_now, onupdate=app_now)
