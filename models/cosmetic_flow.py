import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from database import Base
from utils.timezone import app_now


class CosmeticFlowRow(Base):
    """A saved 'Flow Data' row on Cosmetic & Paint's All Tags tab.

    One row = one user assignment per mid-pipeline cosmetic stage (Cleaning
    through Water Sanding). Purely a definition table today — nothing reads
    these rows yet to drive behaviour; the business rule for how a flow gets
    applied is deferred (see All Tags Flow Data card). Only Admin and
    Cosmetic Manager can create/edit/delete rows.

    A user-facing "label" lets rows stay identifiable in a growing list
    (e.g. "Team A", "Night Shift") — optional since a flow's meaning may
    only become clear once usage is defined.
    """

    __tablename__ = "cosmetic_flow_rows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label = Column(String(100), nullable=True)

    cleaning_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    putty_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    dry_sanding_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    masking_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    painting_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    water_sanding_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=app_now)
    updated_by = Column(String(50), nullable=True)
    updated_at = Column(DateTime, default=app_now, onupdate=app_now)
