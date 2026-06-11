"""add repair_job_id to spare_parts_consumption

Revision ID: 20260501_0900
Revises: 20260430_0900
Create Date: 2026-05-01 09:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260501_0900'
down_revision = '20260430_0900'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'spare_parts_consumption',
        sa.Column('repair_job_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index(
        'ix_spare_parts_consumption_repair_job_id',
        'spare_parts_consumption',
        ['repair_job_id']
    )
    op.create_foreign_key(
        'fk_spc_repair_job_id',
        'spare_parts_consumption', 'repair_jobs',
        ['repair_job_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_spc_repair_job_id', 'spare_parts_consumption', type_='foreignkey')
    op.drop_index('ix_spare_parts_consumption_repair_job_id', table_name='spare_parts_consumption')
    op.drop_column('spare_parts_consumption', 'repair_job_id')
