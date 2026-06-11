import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Boolean, Date, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    username = Column(String(50), nullable=False)
    full_name = Column(String(100), nullable=True)
    date = Column(Date, nullable=False, index=True)
    check_in = Column(DateTime, nullable=True)
    check_out = Column(DateTime, nullable=True)
    check_in_ip = Column(String(50), nullable=True)
    check_out_ip = Column(String(50), nullable=True)
    status = Column(String(20), default="present")  # present, absent, half_day, late, wfh
    notes = Column(Text, nullable=True)
    marked_by = Column(String(50), nullable=True)  # for admin-marked attendance
    created_at = Column(DateTime, default=app_now)

    user = relationship("User", foreign_keys=[user_id])
