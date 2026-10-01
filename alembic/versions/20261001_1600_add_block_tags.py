"""add_block_tags

Revision ID: 20261001_1600
Revises: 20261001_1000
Create Date: 2026-10-01 16:00:00

Block Tags: hold specific tags off the sellable market for a pending deal or
customer without actually selling them. New tables block_records (header:
Block ID, Date, Container, Location, Block For, Customer) and
block_record_items (one row per tag under a block, with status
blocked/done/released); new devices.is_blocked boolean, checked by
services/control_engine.validate_sale_allowed() before a sale is allowed.

In practice db_validator.py's missing-table/missing-column checks already
apply this on the next server restart, same as every other table/column in
this app's history — this migration exists to keep Alembic history accurate
for a fresh environment that runs `alembic upgrade` directly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '20261001_1600'
down_revision: Union[str, None] = '20261001_1000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    def table_exists(table: str) -> bool:
        result = conn.execute(
            sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
            {"t": table},
        )
        return result.fetchone() is not None

    def column_exists(table: str, column: str) -> bool:
        result = conn.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        )
        return result.fetchone() is not None

    unit_type_enum = postgresql.ENUM(name='unittype', create_type=False)
    zone_type_enum = postgresql.ENUM(name='zonetype', create_type=False)
    block_item_status_enum = postgresql.ENUM(
        'blocked', 'released', name='blockitemstatus',
    )

    if not table_exists("block_records"):
        block_item_status_enum.create(conn, checkfirst=True)
        op.create_table(
            'block_records',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column('block_id', sa.String(40), nullable=False, unique=True),
            sa.Column('block_date', sa.Date(), nullable=False),
            sa.Column('container', unit_type_enum, nullable=False),
            sa.Column('location_zone', zone_type_enum, nullable=True),
            sa.Column('block_for_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('customer_name', sa.String(150), nullable=True),
            sa.Column('created_by_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_block_records_block_id', 'block_records', ['block_id'])
        op.create_index('ix_block_records_block_date', 'block_records', ['block_date'])
        op.create_index('ix_block_records_location_zone', 'block_records', ['location_zone'])

    if not table_exists("block_record_items"):
        op.create_table(
            'block_record_items',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column('block_record_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('block_records.id', ondelete='CASCADE'), nullable=False),
            sa.Column('device_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('devices.id'), nullable=False),
            sa.Column('barcode', sa.String(100), nullable=False),
            sa.Column('lot_number', sa.String(50), nullable=True),
            sa.Column('model', sa.String(100), nullable=True),
            sa.Column('cpu', sa.String(100), nullable=True),
            sa.Column('ram_gb', sa.Integer(), nullable=True),
            sa.Column('storage_gb', sa.Integer(), nullable=True),
            sa.Column('status', block_item_status_enum, nullable=False, server_default='blocked'),
            sa.Column('status_changed_by_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('status_changed_at', sa.DateTime(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_block_record_items_block_record_id', 'block_record_items', ['block_record_id'])
        op.create_index('ix_block_record_items_device_id', 'block_record_items', ['device_id'])
        op.create_index('ix_block_record_items_status', 'block_record_items', ['status'])

    if not column_exists("devices", "is_blocked"):
        op.add_column('devices', sa.Column(
            'is_blocked', sa.Boolean(), nullable=False, server_default=sa.text('false'),
        ))


def downgrade() -> None:
    op.drop_column('devices', 'is_blocked')
    op.drop_table('block_record_items')
    op.drop_table('block_records')
    op.execute("DROP TYPE IF EXISTS blockitemstatus")
