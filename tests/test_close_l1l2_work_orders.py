"""Leaving L1/L2 must close the tag's open L1/L2 WorkOrders.

Regression (2026-10-07): the repair "Complete Job" panel, Scrap, Back to
Inventory and the IQC bulk stage move left the WorkOrder "pending", so WorkID
Status showed no Completed Date for it and under-counted an engineer's day.
"""
import asyncio
import inspect
import uuid

from routers import iqc, repair


class _RecordingDB:
    def __init__(self):
        self.stmts = []

    async def execute(self, stmt, *a, **k):
        self.stmts.append(stmt)


def test_helper_updates_open_l1l2_work_orders_only():
    db = _RecordingDB()
    did = uuid.uuid4()
    asyncio.run(repair._close_l1l2_work_orders(db, did))
    assert len(db.stmts) == 1
    sql = str(db.stmts[0].compile(compile_kwargs={"literal_binds": False}))
    assert sql.startswith("UPDATE work_orders SET")
    assert "status" in sql and "completed_at" in sql
    # open ones only, scoped to the device, matching both WorkID flavours
    assert "work_orders.status !=" in sql
    assert "work_orders.device_id =" in sql
    assert "work_orders.work_id LIKE" in sql and "work_orders.stage IN" in sql


def test_every_exit_path_calls_the_helper():
    src = inspect.getsource(repair)
    # scrap, back-to-inventory, side-panel Completed, generic completion
    assert src.count("await _close_l1l2_work_orders(db, device.id)") >= 4
    assert "_close_l1l2_work_orders" in inspect.getsource(iqc)


def test_l3_request_still_leaves_l1l2_work_order_open():
    # The tag comes back to L1/L2 after L3/L4 — that WorkID is still the
    # engineer's open job, so the L3/L4 request must not close it.
    assert "_close_l1l2_work_orders" not in inspect.getsource(repair.request_l3l4)
