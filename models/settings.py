# models/settings.py
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, Text, DateTime
from database import Base


class AppSetting(Base):
    """Key/value application settings stored in DB. Key is the primary key."""
    __tablename__ = "app_settings"

    key         = Column(String(50),  primary_key=True)
    value       = Column(Text,        nullable=True)
    description = Column(String(200), nullable=True)
    updated_by  = Column(String(50),  nullable=True)
    updated_at  = Column(DateTime,    default=app_now, onupdate=app_now)
