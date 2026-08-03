# models/business_pl_override.py
"""
BusinessPLOverride — admin manual corrections to a Business P&L monthly row.

Business P&L's monthly figures are computed from Sale/Device/SparePartConsumption/
RepairAttempt data. An admin sometimes needs to correct a month after the fact
(a mis-costed device, a labour bill entered late, a one-off adjustment) without
that correction silently vanishing the next time the underlying data changes —
this table holds the override, the report applies it on top of the computed
value at render time. A null field means "no override, use the computed value";
only components an admin actually edited replace the computed figure.
"""
import uuid
from sqlalchemy import Column, Integer, String, Numeric, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from database import Base
from utils.timezone import app_now


class BusinessPLOverride(Base):
    __tablename__ = "business_pl_overrides"
    __table_args__ = (
        UniqueConstraint("year", "month", name="uq_business_pl_override_year_month"),
    )

    id                    = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    year                  = Column(Integer, nullable=False, index=True)
    month                 = Column(Integer, nullable=False)  # 1-12
    revenue_override      = Column(Numeric(14, 2), nullable=True)
    device_cogs_override  = Column(Numeric(14, 2), nullable=True)
    parts_cogs_override   = Column(Numeric(14, 2), nullable=True)
    labour_cogs_override  = Column(Numeric(14, 2), nullable=True)
    updated_by            = Column(String(50), nullable=True)
    updated_at            = Column(DateTime, default=app_now, onupdate=app_now)
