"""add scrap_verified to devices

Revision ID: 20260626_0001
Revises: a1b2c3d4e5f6
Create Date: 2026-06-26 00:01:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '20260626_0001'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'devices',
        sa.Column('scrap_verified', sa.Boolean(), nullable=False, server_default=sa.text('false'))
    )


def downgrade() -> None:
    op.drop_column('devices', 'scrap_verified')
