"""add_as_is_lot_prices

Revision ID: 20261007_1000
Revises: 20261001_1600
Create Date: 2026-10-07 10:00:00

Manual Min/Max Selling Price override for a Ready to Sale As-Is Lot, one row
per (lot, sub-lot). The As-Is table's Min Selling Price is otherwise computed
(Lot Price + As-Is margin from Cost Config). Stored separately from
devices.min_selling_price because it is a lot-level total, not a per-tag price.

As with every other table in this app, db_validator.py creates it on the next
server restart; this migration keeps Alembic history accurate for a fresh
environment that runs `alembic upgrade` directly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '20261007_1000'
down_revision: Union[str, None] = '20261001_1600'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
        {"t": "as_is_lot_prices"},
    ).fetchone()
    if exists:
        return
    op.create_table(
        "as_is_lot_prices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("lots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sub_lot_number", sa.String(50), nullable=False),
        sa.Column("min_selling_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("max_selling_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("updated_by", sa.String(50), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("lot_id", "sub_lot_number", name="uq_as_is_lot_prices_lot_sublot"),
    )
    op.create_index("ix_as_is_lot_prices_lot_id", "as_is_lot_prices", ["lot_id"])


def downgrade() -> None:
    op.drop_index("ix_as_is_lot_prices_lot_id", table_name="as_is_lot_prices")
    op.drop_table("as_is_lot_prices")
