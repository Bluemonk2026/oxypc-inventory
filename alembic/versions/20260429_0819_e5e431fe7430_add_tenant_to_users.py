"""add_tenant_to_users

Revision ID: e5e431fe7430
Revises: b62e6ba33486
Create Date: 2026-04-29 08:19:44.097557

Adds `tenant` column to `users` table.
All existing users are backfilled to "oxypc_internal".
This is a forward-looking SaaS hook — when multi-tenancy is introduced,
each customer's users will carry a distinct tenant identifier so their
data can be isolated at the schema/DB layer without touching this column.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5e431fe7430'
down_revision: Union[str, None] = 'b62e6ba33486'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add tenant column — nullable so it doesn't break existing rows mid-migration
    op.add_column('users', sa.Column('tenant', sa.String(length=50), nullable=True))

    # Backfill all existing users to the internal tenant
    op.execute("UPDATE users SET tenant = 'oxypc_internal' WHERE tenant IS NULL")

    # Index for fast tenant-scoped queries (used heavily when multi-tenancy is active)
    op.create_index(op.f('ix_users_tenant'), 'users', ['tenant'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_users_tenant'), table_name='users')
    op.drop_column('users', 'tenant')
