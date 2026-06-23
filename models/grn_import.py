import uuid
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, Integer, Numeric, Boolean
from sqlalchemy.dialects.postgresql import UUID
from database import Base


class GRNImport(Base):
    """A GRN created by uploading an invoice PDF. Fields are best-effort extracted
    from the PDF and editable. GRN number is a 12-digit auto-generated id."""
    __tablename__ = "grn_imports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grn_number = Column(String(12), unique=True, nullable=False, index=True)  # 12-digit

    lot_number = Column(String(60), nullable=True)       # parsed from invoice PDF (best-effort)
    invoice_number = Column(String(100), nullable=True)
    invoice_date = Column(String(40), nullable=True)     # text (parsed from PDF, may be free-form)
    sender_name = Column(String(200), nullable=True)
    quantity = Column(Integer, nullable=True)
    amount = Column(Numeric(14, 2), nullable=True)
    validated = Column(Boolean, default=False, nullable=True)   # set via Validate GRN modal
    source = Column(String(20), nullable=True, default="invoice")   # 'invoice' (GRN with Invoice) | 'post_iqc' (GRN post IQC)

    file_name = Column(String(255), nullable=True)
    file_path = Column(String(500), nullable=True)
    file_hash = Column(String(64), nullable=True, index=True)  # SHA-256 for dedupe

    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=app_now)

    # Soft delete (compliance: GRN docs are kept + audit-logged, just hidden)
    is_deleted = Column(Boolean, nullable=False, default=False, server_default="false")
    deleted_at = Column(DateTime, nullable=True)
