"""add_missing_fk_indexes

Revision ID: f991834630d1
Revises: eea7c1db1ab0
Create Date: 2026-04-26 09:40:19.231067

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f991834630d1'
down_revision: Union[str, None] = 'eea7c1db1ab0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # These indexes make FK joins fast — each module queries independently
    # without waiting on full table scans.
    # Each create_index is wrapped to skip gracefully if the index already exists.
    conn = op.get_bind()

    def index_exists(name: str) -> bool:
        result = conn.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :n"),
            {"n": name},
        )
        return result.fetchone() is not None

    if not index_exists("ix_devices_lot_id"):
        op.create_index("ix_devices_lot_id", "devices", ["lot_id"], unique=False)
    if not index_exists("ix_spare_parts_consumption_device_id"):
        op.create_index("ix_spare_parts_consumption_device_id", "spare_parts_consumption", ["device_id"], unique=False)
    if not index_exists("ix_spare_parts_consumption_lot_id"):
        op.create_index("ix_spare_parts_consumption_lot_id", "spare_parts_consumption", ["lot_id"], unique=False)
    if not index_exists("ix_stage_movements_device_id"):
        op.create_index("ix_stage_movements_device_id", "stage_movements", ["device_id"], unique=False)
    if not index_exists("ix_sales_device_id"):
        op.create_index("ix_sales_device_id", "sales", ["device_id"], unique=False)
    if not index_exists("ix_sales_sold_at"):
        op.create_index("ix_sales_sold_at", "sales", ["sold_at"], unique=False)
    if not index_exists("ix_dealer_orders_dealer_id"):
        op.create_index("ix_dealer_orders_dealer_id", "dealer_orders", ["dealer_id"], unique=False)
    if not index_exists("ix_customer_receipts_dealer_id"):
        op.create_index("ix_customer_receipts_dealer_id", "customer_receipts", ["dealer_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_devices_lot_id", table_name="devices")
    op.drop_index("ix_spare_parts_consumption_device_id", table_name="spare_parts_consumption")
    op.drop_index("ix_spare_parts_consumption_lot_id", table_name="spare_parts_consumption")
    op.drop_index("ix_stage_movements_device_id", table_name="stage_movements")
    op.drop_index("ix_sales_device_id", table_name="sales")
    op.drop_index("ix_sales_sold_at", table_name="sales")
    op.drop_index("ix_dealer_orders_dealer_id", table_name="dealer_orders")
    op.drop_index("ix_customer_receipts_dealer_id", table_name="customer_receipts")
