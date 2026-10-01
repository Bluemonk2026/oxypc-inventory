"""audit_records_my_fields

Revision ID: 20261001_1000
Revises: 20260930_1200
Create Date: 2026-10-01 10:00:00

Physical Audits' grouping key changed from (Report Date, System Stage,
System Location) to (Report Date, My Stage, My Location, Category) — the
auditor's claimed stage/location plus the scanned device's category, not
the device's actual system stage/location (that comparison still happens
per tag on audit_record_items, unchanged).

Additive only: audit_records.system_stage/system_location_id are left in
place, unused by the ORM going forward rather than dropped — consistent
with this app's additive-only schema discipline. my_stage/my_location_id/
category are new columns on audit_records; category is new on
audit_record_items (snapshot of the device's category at audit time,
alongside the existing brand/model/serial snapshot fields).

In practice db_validator.py's missing-column check (ALTER TABLE ... ADD
COLUMN IF NOT EXISTS) already applies this on the next server restart, same
as every other column in this app's history — this migration exists to keep
Alembic history accurate for a fresh environment that runs `alembic upgrade`
directly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '20261001_1000'
down_revision: Union[str, None] = '20260930_1200'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    def column_exists(table: str, column: str) -> bool:
        result = conn.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        )
        return result.fetchone() is not None

    device_stage_enum = postgresql.ENUM(name='devicestage', create_type=False)

    if not column_exists("audit_records", "my_stage"):
        op.add_column('audit_records', sa.Column('my_stage', device_stage_enum, nullable=True))
        op.create_index('ix_audit_records_my_stage', 'audit_records', ['my_stage'])
    if not column_exists("audit_records", "my_location_id"):
        op.add_column('audit_records', sa.Column(
            'my_location_id', postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id'), nullable=True,
        ))
        op.create_index('ix_audit_records_my_location_id', 'audit_records', ['my_location_id'])
    if not column_exists("audit_records", "category"):
        op.add_column('audit_records', sa.Column('category', sa.String(100), nullable=True))
        op.create_index('ix_audit_records_category', 'audit_records', ['category'])

    # audit_records.system_stage was NOT NULL in the original migration (it
    # was the grouping key then); the ORM no longer populates it now that
    # my_stage is the grouping key, so every new INSERT would otherwise
    # violate that constraint. Relaxed rather than dropped — additive-only.
    op.alter_column('audit_records', 'system_stage', nullable=True)

    if not column_exists("audit_record_items", "category"):
        op.add_column('audit_record_items', sa.Column('category', sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column('audit_record_items', 'category')
    op.drop_index('ix_audit_records_category', table_name='audit_records')
    op.drop_column('audit_records', 'category')
    op.drop_index('ix_audit_records_my_location_id', table_name='audit_records')
    op.drop_column('audit_records', 'my_location_id')
    op.drop_index('ix_audit_records_my_stage', table_name='audit_records')
    op.drop_column('audit_records', 'my_stage')
