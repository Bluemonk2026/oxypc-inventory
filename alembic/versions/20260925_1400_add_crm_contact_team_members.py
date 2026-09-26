"""add_crm_contact_team_members

Revision ID: 20260925_1400
Revises: 20260925_1200
Create Date: 2026-09-25 14:00:00

Adds crm_contact_team_members — Account Team Mapping feature. Row-replace
semantics (no soft delete); history lives in audit_logs. In practice this
table gets auto-created by db_validator.fix_missing_tables() on the next
server restart, same as every other table in this app's history — this
migration exists to keep Alembic history accurate for a fresh environment
that runs `alembic upgrade` directly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '20260925_1400'
down_revision: Union[str, None] = '20260925_1200'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    def table_exists(name: str) -> bool:
        result = conn.execute(
            sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :n"),
            {"n": name},
        )
        return result.fetchone() is not None

    if not table_exists("crm_contact_team_members"):
        op.create_table(
            'crm_contact_team_members',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('contact_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('crm_contacts.id'), nullable=False),
            sa.Column('user_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('users.id'), nullable=False),
            sa.Column('role_bucket', sa.String(20), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False,
                      server_default=sa.text('NOW()')),
            sa.Column('created_by', sa.String(50),
                      sa.ForeignKey('users.username'), nullable=True),
            sa.UniqueConstraint('contact_id', 'user_id', 'role_bucket',
                                 name='uq_crm_team_member_bucket'),
        )
        op.create_index('ix_crm_contact_team_members_contact_id',
                         'crm_contact_team_members', ['contact_id'])
        op.create_index('ix_crm_contact_team_members_user_id',
                         'crm_contact_team_members', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_crm_contact_team_members_user_id', table_name='crm_contact_team_members')
    op.drop_index('ix_crm_contact_team_members_contact_id', table_name='crm_contact_team_members')
    op.drop_table('crm_contact_team_members')
