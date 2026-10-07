"""Close a tag's open WorkOrders when the tag is handed to someone else.

WorkID Status shows one row per WorkOrder, and a row only gets a Completed Date
once its WorkOrder is closed. Reassigning a tag (Change Engineer, Assign /
Bulk Assign to L1/L2, bucket / Final-QC-fail assignment) creates a NEW WorkOrder
for the new engineer but used to leave the previous engineer's one "pending"
forever, so that engineer's row never got a Completed Date (found 2026-10-07).

Call this just before adding the new WorkOrder: the previous assignee's WorkID
completes at this moment, and the new assignee's WorkID starts at the same
moment, so the hand-over reads as a clean timeline.
"""
import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models.work_order import WorkOrder
from utils.timezone import app_now


async def close_open_work_orders(db: AsyncSession, device_id: uuid.UUID, at=None) -> int:
    """Mark every open (non-"asgn") WorkOrder of the device completed at `at`
    (default now). Returns how many were closed.

    "asgn" rows are /transfers' plain assignment bookkeeping, not pipeline work,
    and are left alone (the WorkID Status page hides them)."""
    result = await db.execute(
        update(WorkOrder)
        .where(WorkOrder.device_id == device_id,
               WorkOrder.status != "completed",
               WorkOrder.stage != "asgn")
        .values(status="completed", completed_at=at or app_now())
    )
    return result.rowcount or 0
