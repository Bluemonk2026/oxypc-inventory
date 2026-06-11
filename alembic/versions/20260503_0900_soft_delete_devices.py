"""add is_active + deleted_at soft-delete columns to devices

Revision ID: 20260503_0900
Revises: 20260502_0800
Create Date: 2026-05-03 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = '20260503_0900'
down_revision = '20260502_0800'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('devices',
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('devices',
        sa.Column('deleted_at', sa.DateTime(), nullable=True))
    # Partial index (PostgreSQL only). On non-PG dialects this silently
    # degrades to a full index. All environments must use PostgreSQL.
    op.create_index(
        'ix_devices_is_active',
        'devices',
        ['is_active'],
        postgresql_where=sa.text('is_active = false')
    )


def downgrade() -> None:
    op.drop_index('ix_devices_is_active', table_name='devices')
    op.drop_column('devices', 'deleted_at')
    op.drop_column('devices', 'is_active')
