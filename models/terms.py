"""Terms & Conditions — reusable long-form policies (payment / delivery /
disclaimer). Managed in the admin 'Terms and Condition' page and embedded into
generated Purchase Order documents."""
import uuid
from utils.timezone import app_now
from sqlalchemy import Column, String, Text, Boolean, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from database import Base

# (value, label) — the three policy buckets
TERM_TYPES = [
    ("payment",    "Payment Terms"),
    ("delivery",   "Delivery Terms"),
    ("disclaimer", "Disclaimer"),
]
TERM_TYPE_LABELS = dict(TERM_TYPES)


class TermsCondition(Base):
    __tablename__ = "terms_conditions"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    term_type     = Column(String(20),  nullable=False, index=True)  # payment/delivery/disclaimer
    title         = Column(String(200), nullable=False)
    content       = Column(Text,        nullable=False)
    is_active     = Column(Boolean,     default=True, nullable=False)
    display_order = Column(Integer,     default=0)
    created_by    = Column(String(50),  nullable=True)
    created_at    = Column(DateTime,    default=app_now)
    updated_at    = Column(DateTime,    default=app_now, onupdate=app_now)
