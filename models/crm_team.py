"""
Account Team Mapping — CRM Module Extension
Table: crm_contact_team_members

Rows are fully replaced (deleted + re-inserted) on every save rather than
edited in place — see services/crm_team.py:replace_team_buckets(). History
lives in the existing audit_logs table via services/audit_engine.audit(),
same convention as every other write in this app, so there is no soft-delete
column here.
"""
import uuid
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from database import Base


class CRMContactTeamMember(Base):
    __tablename__ = "crm_contact_team_members"
    __table_args__ = (
        UniqueConstraint("contact_id", "user_id", "role_bucket", name="uq_crm_team_member_bucket"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("crm_contacts.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    role_bucket = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=app_now)
    created_by = Column(String(50), ForeignKey("users.username"), nullable=True)
