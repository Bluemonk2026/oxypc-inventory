"""add_device_touch_type_and_flag

Revision ID: 20261012_1000
Revises: 20261007_1000
Create Date: 2026-10-12 10:00:00

devices.touch_type            Touch / Non-Touch, set on the Final QC form.
devices.flag_*                Inventory Manager "Flag Items" (urgent at inventory).

Additive, nullable (flag_active defaults false). As with every other column in this
app, db_validator.py adds them on the next server restart; this migration keeps
Alembic history accurate for a fresh environment that runs `alembic upgrade`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20261012_1000'
down_revision: Union[str, None] = '20261007_1000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = [
    ("touch_type", sa.String(12), None),
    ("flag_active", sa.Boolean(), sa.text("false")),
    ("flag_authorized_by", sa.String(100), None),
    ("flag_request_date", sa.Date(), None),
    ("flag_target_date", sa.Date(), None),
    ("flag_reason", sa.Text(), None),
]


def upgrade() -> None:
    conn = op.get_bind()
    have = {r[0] for r in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'devices'")).fetchall()}
    for name, type_, default in _COLUMNS:
        if name in have:
            continue
        if name == "flag_active":
            op.add_column("devices", sa.Column(name, type_, nullable=False, server_default=default))
        else:
            op.add_column("devices", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _t, _d in reversed(_COLUMNS):
        op.drop_column("devices", name)
