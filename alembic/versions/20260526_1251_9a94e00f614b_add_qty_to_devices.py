"""add qty to devices

Revision ID: 9a94e00f614b
Revises: 20260515_1000
Create Date: 2026-05-26 12:51:35.852643

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9a94e00f614b'
down_revision: Union[str, None] = '20260515_1000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add qty column to devices table (units this record covers, default 1)
    op.add_column('devices', sa.Column('qty', sa.Integer(), server_default='1', nullable=True))


def downgrade() -> None:
    op.drop_column('devices', 'qty')
