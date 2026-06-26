from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)  # None = broadcast to all
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    notification_type = Column(String(50), default="info")  # info, success, warning, alert
    barcode = Column(String(100), nullable=True)   # device tag
    brand = Column(String(100), nullable=True)
    model = Column(String(200), nullable=True)
    stage = Column(String(100), nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
