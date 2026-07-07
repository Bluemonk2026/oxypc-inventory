import uuid
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class AttendanceGroup(Base):
    """A named group of employees with a designated manager. The manager can
    view /attendance/report scoped to just this group's members (Attendance
    Config, under Application Settings)."""
    __tablename__ = "attendance_groups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, unique=True)
    manager_username = Column(String(50), nullable=False, index=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=app_now)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))

    members = relationship("AttendanceGroupMember", back_populates="group",
                           cascade="all, delete-orphan", lazy="select")


class AttendanceGroupMember(Base):
    __tablename__ = "attendance_group_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id = Column(UUID(as_uuid=True), ForeignKey("attendance_groups.id"), nullable=False, index=True)
    username = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime, default=app_now)

    group = relationship("AttendanceGroup", back_populates="members")
