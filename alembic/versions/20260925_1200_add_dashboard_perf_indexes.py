"""add_dashboard_perf_indexes

Revision ID: 20260925_1200
Revises: 20260627_0001
Create Date: 2026-09-25 12:00:00

Adds indexes on columns the dashboard's Lot P&L and Stage Pipeline queries
join/filter/group on heavily (devices.lot_id/entity/grn_number,
stage_movements.device_id/to_stage, sales.device_id). These were previously
declared in an earlier migration (f991834630d1, add_missing_fk_indexes) but
never actually present on the live schema — confirmed via pg_indexes on both
production and local before writing this one. Wrapped with existence checks
the same way that migration was, so this is safe to run even if some of
these already exist.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260925_1200'
down_revision: Union[str, None] = '20260627_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    def index_exists(name: str) -> bool:
        result = conn.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :n"),
            {"n": name},
        )
        return result.fetchone() is not None

    if not index_exists("ix_devices_lot_id"):
        op.create_index("ix_devices_lot_id", "devices", ["lot_id"], unique=False)
    if not index_exists("ix_devices_entity"):
        op.create_index("ix_devices_entity", "devices", ["entity"], unique=False)
    if not index_exists("ix_devices_grn_number"):
        op.create_index("ix_devices_grn_number", "devices", ["grn_number"], unique=False)
    if not index_exists("ix_stage_movements_device_id"):
        op.create_index("ix_stage_movements_device_id", "stage_movements", ["device_id"], unique=False)
    if not index_exists("ix_stage_movements_to_stage"):
        op.create_index("ix_stage_movements_to_stage", "stage_movements", ["to_stage"], unique=False)
    if not index_exists("ix_sales_device_id"):
        op.create_index("ix_sales_device_id", "sales", ["device_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_devices_lot_id", table_name="devices")
    op.drop_index("ix_devices_entity", table_name="devices")
    op.drop_index("ix_devices_grn_number", table_name="devices")
    op.drop_index("ix_stage_movements_device_id", table_name="stage_movements")
    op.drop_index("ix_stage_movements_to_stage", table_name="stage_movements")
    op.drop_index("ix_sales_device_id", table_name="sales")
