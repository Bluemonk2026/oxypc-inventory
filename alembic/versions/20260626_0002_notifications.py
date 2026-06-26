"""add notifications table

Revision ID: 20260626_0002
Revises: b2c3d4e5f6a7
Create Date: 2026-06-26

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = '20260626_0002'
down_revision: Union[str, None] = ('20260626_0001', 'b2c3d4e5f6a7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('notification_type', sa.String(50), server_default='info'),
        sa.Column('barcode', sa.String(100), nullable=True),
        sa.Column('brand', sa.String(100), nullable=True),
        sa.Column('model', sa.String(200), nullable=True),
        sa.Column('stage', sa.String(100), nullable=True),
        sa.Column('is_read', sa.Boolean(), server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])
    op.create_index('ix_notifications_created_at', 'notifications', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_notifications_created_at', table_name='notifications')
    op.drop_index('ix_notifications_user_id', table_name='notifications')
    op.drop_table('notifications')
