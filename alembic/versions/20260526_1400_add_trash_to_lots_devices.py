"""add is_trashed to lots and devices

Revision ID: a1b2c3d4e5f6
Revises: 0477018c1d08
Create Date: 2026-05-26 14:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '0477018c1d08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('lots', sa.Column('is_trashed', sa.Boolean(), nullable=False,
                                    server_default=sa.text('false')))
    op.add_column('lots', sa.Column('trashed_at', sa.DateTime(), nullable=True))
    op.add_column('devices', sa.Column('is_trashed', sa.Boolean(), nullable=False,
                                       server_default=sa.text('false')))
    op.add_column('devices', sa.Column('trashed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('devices', 'trashed_at')
    op.drop_column('devices', 'is_trashed')
    op.drop_column('lots', 'trashed_at')
    op.drop_column('lots', 'is_trashed')
