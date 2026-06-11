# models/cost_config.py
"""
CostConfig — configurable rates for the cost engine.

Keys used by the system:
  repair_labour_rate  — Rs per repair attempt when engineer enters no cost (default 150)
  cosmetic_rate       — Rs per device that passed through cosmetic pipeline (default 50)
"""
import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, Numeric, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from database import Base


class CostConfig(Base):
    __tablename__ = "cost_config"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key         = Column(String(50), unique=True, nullable=False, index=True)
    value       = Column(Numeric(10, 2), nullable=False)
    description = Column(Text, nullable=True)
    updated_by  = Column(String(50), nullable=True)
    updated_at  = Column(DateTime, default=app_now, onupdate=app_now)
