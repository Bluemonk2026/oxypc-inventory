import uuid
from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID
from database import Base
from utils.timezone import app_now


class Company(Base):
    """One of possibly several company profiles an admin can define under the
    Company Setting page — used to populate the "Company Details" dropdown on
    Quote/PO generation (Account, Buyer Deal, Supplier Deal detail pages)."""
    __tablename__ = "companies"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name        = Column(String(200), nullable=False)
    company_entity      = Column(String(50), nullable=True)  # Master Data "entity" category — utils/master_data.entity_values
    company_address     = Column(String(500), nullable=True)
    company_gstin       = Column(String(20), nullable=True)
    company_state       = Column(String(100), nullable=True)
    company_state_code  = Column(String(5), nullable=True)
    company_phone       = Column(String(50), nullable=True)
    company_email       = Column(String(100), nullable=True)
    is_active           = Column(Boolean, nullable=False, default=True)
    created_by          = Column(String(50), nullable=True)
    created_at          = Column(DateTime, default=app_now)
    updated_at          = Column(DateTime, default=app_now, onupdate=app_now)
