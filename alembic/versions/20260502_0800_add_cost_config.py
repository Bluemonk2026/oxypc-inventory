"""add cost_config table

Revision ID: 20260502_0800
Revises: 20260501_0900
Create Date: 2026-05-02 08:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '20260502_0800'
down_revision = '20260501_0900'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cost_config',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('key', sa.String(50), nullable=False, unique=True),
        sa.Column('value', sa.Numeric(10, 2), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('updated_by', sa.String(50), nullable=True),
        sa.Column('updated_at', sa.DateTime, nullable=True),
    )
    op.create_index('ix_cost_config_key', 'cost_config', ['key'])


def downgrade():
    op.drop_index('ix_cost_config_key', table_name='cost_config')
    op.drop_table('cost_config')
