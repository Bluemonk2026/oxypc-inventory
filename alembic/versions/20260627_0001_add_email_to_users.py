"""add email to users

Revision ID: 20260627_0001
Revises: 20260626_1100
Create Date: 2026-06-27

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '20260627_0001'
down_revision: Union[str, None] = '20260626_1100'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('email', sa.String(150), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'email')
