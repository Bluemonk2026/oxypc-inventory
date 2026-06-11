"""add_composite_indexes_sprint18

Revision ID: b62e6ba33486
Revises: f991834630d1
Create Date: 2026-04-27 18:11:12.442904

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b62e6ba33486'
down_revision: Union[str, None] = 'f991834630d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_devices_stage_subcategory", "devices",
                    ["current_stage", "sub_category"], unique=False)
    op.create_index("ix_device_loc_logs_device_logged", "device_location_logs",
                    ["device_id", "logged_at"], unique=False)
    op.create_index("ix_repair_jobs_device_stage_status", "repair_jobs",
                    ["device_id", "stage", "status"], unique=False)
    op.create_index("ix_stage_movements_device_moved", "stage_movements",
                    ["device_id", "moved_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_stage_movements_device_moved", table_name="stage_movements")
    op.drop_index("ix_repair_jobs_device_stage_status", table_name="repair_jobs")
    op.drop_index("ix_device_loc_logs_device_logged", table_name="device_location_logs")
    op.drop_index("ix_devices_stage_subcategory", table_name="devices")
