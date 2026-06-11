"""Return approval workflow

Revision ID: 20260515_1000
Revises: 20260514_1000
Create Date: 2026-05-15
"""
from alembic import op
import sqlalchemy as sa

revision = '20260515_1000'
down_revision = '20260514_1000'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('returns', sa.Column('approval_status', sa.String(20), nullable=True, server_default='pending'))
    op.add_column('returns', sa.Column('approved_by', sa.String(50), nullable=True))
    op.add_column('returns', sa.Column('approved_at', sa.DateTime(), nullable=True))
    op.add_column('returns', sa.Column('rejection_reason', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('returns', 'rejection_reason')
    op.drop_column('returns', 'approved_at')
    op.drop_column('returns', 'approved_by')
    op.drop_column('returns', 'approval_status')
