"""add_physical_audits

Revision ID: 20260930_1200
Revises: 20260925_1400
Create Date: 2026-09-30 12:00:00

Adds audit_records + audit_record_items — the new "Physical Audits" feature
(Report Date x System Stage x System Location tag audits), deliberately
separate from the older InventoryAudit/AuditScanItem tables (the zone/scan-
batch "Physical Audit" tool under Inventory Locations, relabelled "Zone
Audit" in the sidebar).

Both new stage columns reuse the existing Postgres `devicestage` enum type
(already created for devices.current_stage) via create_type=False — they
must NOT attempt to recreate it.

In practice this app's tables get auto-created by
db_validator.fix_missing_tables() on the next server restart, same as every
other table in this app's history — this migration exists to keep Alembic
history accurate for a fresh environment that runs `alembic upgrade`
directly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '20260930_1200'
down_revision: Union[str, None] = '20260925_1400'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    def table_exists(name: str) -> bool:
        result = conn.execute(
            sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :n"),
            {"n": name},
        )
        return result.fetchone() is not None

    device_stage_enum = postgresql.ENUM(name='devicestage', create_type=False)

    if not table_exists("audit_records"):
        op.create_table(
            'audit_records',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('report_date', sa.Date(), nullable=False),
            sa.Column('system_stage', device_stage_enum, nullable=False),
            sa.Column('system_location_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('storage_locations.id'), nullable=True),
            sa.Column('current_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('physical_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        )
        op.create_index('ix_audit_records_report_date', 'audit_records', ['report_date'])
        op.create_index('ix_audit_records_system_stage', 'audit_records', ['system_stage'])
        op.create_index('ix_audit_records_system_location_id', 'audit_records', ['system_location_id'])

    if not table_exists("audit_record_items"):
        op.create_table(
            'audit_record_items',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('audit_record_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('audit_records.id', ondelete='CASCADE'), nullable=False),
            sa.Column('device_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('devices.id'), nullable=False),
            sa.Column('barcode', sa.String(100), nullable=False),
            sa.Column('lot_number', sa.String(50), nullable=True),
            sa.Column('brand', sa.String(50), nullable=True),
            sa.Column('model', sa.String(100), nullable=True),
            sa.Column('serial_no', sa.String(100), nullable=True),
            sa.Column('system_stage', device_stage_enum, nullable=False),
            sa.Column('system_location_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('storage_locations.id'), nullable=True),
            sa.Column('my_stage', device_stage_enum, nullable=False),
            sa.Column('my_location_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('storage_locations.id'), nullable=True),
            sa.Column('assigned_by_user_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('users.id'), nullable=True),
            sa.Column('assigned_to_user_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('users.id'), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('audited_by_user_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        )
        op.create_index('ix_audit_record_items_audit_record_id', 'audit_record_items', ['audit_record_id'])
        op.create_index('ix_audit_record_items_device_id', 'audit_record_items', ['device_id'])


def downgrade() -> None:
    op.drop_index('ix_audit_record_items_device_id', table_name='audit_record_items')
    op.drop_index('ix_audit_record_items_audit_record_id', table_name='audit_record_items')
    op.drop_table('audit_record_items')
    op.drop_index('ix_audit_records_system_location_id', table_name='audit_records')
    op.drop_index('ix_audit_records_system_stage', table_name='audit_records')
    op.drop_index('ix_audit_records_report_date', table_name='audit_records')
    op.drop_table('audit_records')
