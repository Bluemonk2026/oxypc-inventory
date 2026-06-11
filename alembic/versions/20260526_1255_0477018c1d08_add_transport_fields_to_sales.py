"""add transport fields to sales

Revision ID: 0477018c1d08
Revises: 9a94e00f614b
Create Date: 2026-05-26 12:55:15.837606

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0477018c1d08'
down_revision: Union[str, None] = '9a94e00f614b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add transport and payment reference columns to sales table
    op.add_column('sales', sa.Column('payment_reference', sa.String(100), nullable=True))
    op.add_column('sales', sa.Column('transport_mode', sa.String(30), nullable=True))
    op.add_column('sales', sa.Column('transport_via', sa.String(100), nullable=True))
    op.add_column('sales', sa.Column('tracking_number', sa.String(100), nullable=True))
    op.add_column('sales', sa.Column('dispatch_date', sa.DateTime(), nullable=True))
    op.add_column('sales', sa.Column('delivery_status', sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column('sales', 'delivery_status')
    op.drop_column('sales', 'dispatch_date')
    op.drop_column('sales', 'tracking_number')
    op.drop_column('sales', 'transport_via')
    op.drop_column('sales', 'transport_mode')
    op.drop_column('sales', 'payment_reference')
