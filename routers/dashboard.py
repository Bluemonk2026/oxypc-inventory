import logging
from templates_config import templates
from datetime import datetime, date
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement
from models.engines import RepairAttempt
from models.lot import Lot
from models.sales import Sale
from models.spare_parts import SparePart, SparePartConsumption
from models.dealers import DealerOrder, DealerCreditNote, DealerCall
from models.crm import CRMActivity
from models.cost_config import CostConfig
from auth.dependencies import get_current_user
from routers.inventory_location import _gap_devices

_log = logging.getLogger("oxypc.dashboard")

router = APIRouter(tags=["dashboard"])

CATEGORIES = ["Laptop", "Desktop", "TFT"]
KEY_STAGES = [
    DeviceStage.iqc,
    DeviceStage.stock_in,
    DeviceStage.l1,
    DeviceStage.l2,
    DeviceStage.l3,
    DeviceStage.qc_check,
    DeviceStage.ready_to_sale,
    DeviceStage.sold,
]

_OUTSTANDING_STATUSES = ("pending", "confirmed", "delivered")


async def _count(db: AsyncSession, *filters) -> int:
    result = await db.execute(select(func.count(Device.id)).where(*filters))
    return result.scalar() or 0


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    stage_filter: str = Query(default=""),
    pl_from: str = Query(default=""),
    pl_to: str = Query(default=""),
):
    today = app_now().date()

    # ── Stage counts (GROUP BY — null-guarded) ────────────────────────────────
    try:
        stage_result = await db.execute(
            select(Device.current_stage, func.count(Device.id))
            .group_by(Device.current_stage)
        )
        stage_counts = {
            row[0].value: row[1]
            for row in stage_result.fetchall()
            if row[0] is not None
        }
        for stage in DeviceStage:
            stage_counts.setdefault(stage.value, 0)
    except Exception:
        _log.exception("stage_counts failed")
        stage_counts = {stage.value: 0 for stage in DeviceStage}

    # ── Category × stage (GROUP BY — null-guarded) ────────────────────────────
    try:
        cat_stage_result = await db.execute(
            select(Device.sub_category, Device.current_stage, func.count(Device.id))
            .group_by(Device.sub_category, Device.current_stage)
        )
        category_counts: dict = {cat: {"total": 0} for cat in CATEGORIES}
        for sub_cat, stage, cnt in cat_stage_result.fetchall():
            if sub_cat in category_counts and stage is not None:
                category_counts[sub_cat]["total"] += cnt
                category_counts[sub_cat][stage.value] = cnt
    except Exception:
        _log.exception("category_counts failed")
        category_counts = {cat: {"total": 0} for cat in CATEGORIES}

    total_devices = sum(stage_counts.values())
    laptops_available = category_counts.get("Laptop", {}).get("ready_to_sale", 0)
    desktops_available = category_counts.get("Desktop", {}).get("ready_to_sale", 0)
    tft_available = category_counts.get("TFT", {}).get("ready_to_sale", 0)
    all_available = stage_counts.get("ready_to_sale", 0)

    # ── Role-based user queue ─────────────────────────────────────────────────
    role = current_user.role
    user_queue: dict = {}

    try:
        if role == UserRole.iqc_inspector:
            user_queue["iqc_pending"] = stage_counts.get(DeviceStage.iqc.value, 0)

        elif role == UserRole.l1_engineer:
            user_queue["l1_count"] = stage_counts.get(DeviceStage.l1.value, 0)

        elif role == UserRole.l2_engineer:
            user_queue["l2_count"] = stage_counts.get(DeviceStage.l2.value, 0)

        elif role == UserRole.l3_engineer:
            user_queue["l3_count"] = stage_counts.get(DeviceStage.l3.value, 0)

        elif role == UserRole.qc_inspector:
            user_queue["qc_pending"] = stage_counts.get(DeviceStage.qc_check.value, 0)

        elif role in (UserRole.sales, UserRole.sales_manager, UserRole.telecaller):
            user_queue["ready_to_sale"] = stage_counts.get(DeviceStage.ready_to_sale.value, 0)
            ts_result = await db.execute(
                select(func.count(Sale.id)).where(func.date(Sale.sold_at) == today)
            )
            user_queue["today_sales"] = ts_result.scalar() or 0
            mr_result = await db.execute(
                select(func.coalesce(func.sum(Sale.sale_price), 0)).where(
                    func.date(Sale.sold_at) >= date(today.year, today.month, 1)
                )
            )
            user_queue["month_revenue"] = float(mr_result.scalar() or 0)

            # Dealer outstanding for sales roles
            out_res = await db.execute(
                select(func.coalesce(func.sum(DealerOrder.due_amount), 0))
                .where(DealerOrder.status.in_(_OUTSTANDING_STATUSES))
            )
            user_queue["dealer_outstanding_total"] = float(out_res.scalar() or 0)

            overdue_res = await db.execute(
                select(func.count(DealerOrder.id))
                .where(
                    DealerOrder.due_amount > 0,
                    DealerOrder.payment_due_date.isnot(None),
                    DealerOrder.payment_due_date < app_now(),
                )
            )
            user_queue["dealer_overdue_count"] = int(overdue_res.scalar() or 0)

        elif role == UserRole.spare_parts_manager:
            ls_result = await db.execute(
                select(func.count(SparePart.id)).where(SparePart.qty_in_stock <= SparePart.min_stock_alert)
            )
            user_queue["low_stock_count"] = ls_result.scalar() or 0
            pv_result = await db.execute(
                select(func.coalesce(func.sum(SparePart.qty_in_stock * SparePart.unit_price), 0))
            )
            user_queue["total_parts_value"] = float(pv_result.scalar() or 0)
            tc_result = await db.execute(
                select(func.coalesce(func.sum(SparePartConsumption.qty_used), 0)).where(
                    func.date(SparePartConsumption.used_at) == today
                )
            )
            user_queue["today_consumption"] = int(tc_result.scalar() or 0)

        elif role == UserRole.inventory_manager:
            user_queue["stock_in_count"] = stage_counts.get(DeviceStage.stock_in.value, 0)
            lot_res = await db.execute(select(func.count(Lot.id)))
            user_queue["lot_count"] = lot_res.scalar() or 0

        elif role == UserRole.admin:
            user_queue["iqc_pending"]    = stage_counts.get(DeviceStage.iqc.value, 0)
            user_queue["l1_count"]       = stage_counts.get(DeviceStage.l1.value, 0)
            user_queue["l2_count"]       = stage_counts.get(DeviceStage.l2.value, 0)
            user_queue["l3_count"]       = stage_counts.get(DeviceStage.l3.value, 0)
            user_queue["qc_pending"]     = stage_counts.get(DeviceStage.qc_check.value, 0)
            user_queue["ready_to_sale"]  = stage_counts.get(DeviceStage.ready_to_sale.value, 0)
            ts_result = await db.execute(
                select(func.count(Sale.id)).where(func.date(Sale.sold_at) == today)
            )
            user_queue["today_sales"] = ts_result.scalar() or 0
            mr_result = await db.execute(
                select(func.coalesce(func.sum(Sale.sale_price), 0)).where(
                    func.date(Sale.sold_at) >= date(today.year, today.month, 1)
                )
            )
            user_queue["month_revenue"] = float(mr_result.scalar() or 0)
            ls_result = await db.execute(
                select(func.count(SparePart.id)).where(SparePart.qty_in_stock <= SparePart.min_stock_alert)
            )
            user_queue["low_stock_count"] = ls_result.scalar() or 0
            user_queue["stock_in_count"] = stage_counts.get(DeviceStage.stock_in.value, 0)
            lot_res = await db.execute(select(func.count(Lot.id)))
            user_queue["lot_count"] = lot_res.scalar() or 0

            # Dealer financial KPIs
            out_res = await db.execute(
                select(func.coalesce(func.sum(DealerOrder.due_amount), 0))
                .where(DealerOrder.status.in_(_OUTSTANDING_STATUSES))
            )
            user_queue["dealer_outstanding_total"] = float(out_res.scalar() or 0)

            overdue_res = await db.execute(
                select(func.count(DealerOrder.id))
                .where(
                    DealerOrder.due_amount > 0,
                    DealerOrder.payment_due_date.isnot(None),
                    DealerOrder.payment_due_date < app_now(),
                )
            )
            user_queue["dealer_overdue_count"] = int(overdue_res.scalar() or 0)

            cn_res = await db.execute(
                select(func.count(DealerCreditNote.id))
                .where(DealerCreditNote.created_at >= datetime(today.year, today.month, 1))
            )
            user_queue["dealer_credit_notes_month"] = int(cn_res.scalar() or 0)

    except Exception:
        _log.exception("user_queue failed for role=%s", role)
        # user_queue keeps whatever populated before the exception

    # ── Chart data: category × stage breakdown ────────────────────────────────
    chart_stages = ["iqc", "l1", "l2", "l3", "qc_check", "ready_to_sale", "sold"]
    chart_data: dict = {}
    for cat in CATEGORIES:
        chart_data[cat] = [category_counts[cat].get(s, 0) for s in chart_stages]

    # ── Lot P&L (4 batch queries) ─────────────────────────────────────────────
    lot_pl: list = []
    try:
        lots_result = await db.execute(select(Lot).order_by(Lot.created_at.desc()))
        lots = lots_result.scalars().all()

        # Load cost config rates (fallbacks when actual costs not recorded)
        _cfg_result = await db.execute(select(CostConfig))
        _cfg = {r.key: float(r.value) for r in _cfg_result.scalars().all()}
        repair_labour_rate = _cfg.get("repair_labour_rate", 150.0)
        cosmetic_rate      = _cfg.get("cosmetic_rate", 50.0)

        # Batch 1: device count per lot
        lot_device_counts = dict((await db.execute(
            select(Device.lot_id, func.count(Device.id)).group_by(Device.lot_id)
        )).fetchall())

        # Batch 2: revenue per lot (join through Device)
        lot_revenue = dict((await db.execute(
            select(Device.lot_id, func.coalesce(func.sum(Sale.sale_price), 0))
            .join(Sale, Sale.device_id == Device.id)
            .group_by(Device.lot_id)
        )).fetchall())

        # Batch 3: parts cost per lot
        lot_parts_cost = dict((await db.execute(
            select(SparePartConsumption.lot_id, func.coalesce(func.sum(SparePartConsumption.total_cost), 0))
            .where(SparePartConsumption.lot_id.isnot(None))
            .group_by(SparePartConsumption.lot_id)
        )).fetchall())

        # Batch 4: sold device count per lot
        lot_sold_counts = dict((await db.execute(
            select(Device.lot_id, func.count(Device.id))
            .where(Device.current_stage == DeviceStage.sold)
            .group_by(Device.lot_id)
        )).fetchall())

        # Batch 5: labour cost per lot (repair attempt costs via devices)
        lot_labour_cost = dict((await db.execute(
            select(Device.lot_id, func.coalesce(func.sum(RepairAttempt.cost), 0))
            .join(RepairAttempt, RepairAttempt.device_id == Device.id)
            .group_by(Device.lot_id)
        )).fetchall())

        # Batch 6: repair attempt count per lot (for labour rate fallback)
        lot_attempt_count = dict((await db.execute(
            select(Device.lot_id, func.count(RepairAttempt.id))
            .join(RepairAttempt, RepairAttempt.device_id == Device.id)
            .group_by(Device.lot_id)
        )).fetchall())

        # Batch 7: cosmetic rework count per lot (devices that entered cleaning stage)
        lot_cosmetic_count = dict((await db.execute(
            select(Device.lot_id, func.count(StageMovement.id))
            .join(StageMovement, StageMovement.device_id == Device.id)
            .where(StageMovement.to_stage == DeviceStage.cleaning)
            .group_by(Device.lot_id)
        )).fetchall())

        for lot in lots:
            revenue      = float(lot_revenue.get(lot.id, 0) or 0)
            parts_cost   = float(lot_parts_cost.get(lot.id, 0) or 0)
            buying       = float(lot.buying_price or 0)

            # Labour: use actual costs if recorded; otherwise rate × attempt count
            labour_actual  = float(lot_labour_cost.get(lot.id, 0) or 0)
            attempt_count  = int(lot_attempt_count.get(lot.id, 0) or 0)
            labour_cost    = labour_actual if labour_actual > 0 else (attempt_count * repair_labour_rate)

            # Cosmetic rework: count of cleaning-stage movements × rate
            cosmetic_count = int(lot_cosmetic_count.get(lot.id, 0) or 0)
            cosmetic_cost  = cosmetic_count * cosmetic_rate

            total_cost = buying + parts_cost + labour_cost + cosmetic_cost
            profit     = revenue - total_cost
            margin     = (profit / revenue * 100) if revenue > 0 else 0
            lot_pl.append({
                "lot_number": lot.lot_number,
                "supplier": lot.supplier_name,
                "qty": lot.qty,
                "devices_count": lot_device_counts.get(lot.id, 0),
                "devices_sold": lot_sold_counts.get(lot.id, 0),
                "buying_price": buying,
                "parts_cost": parts_cost,
                "labour_cost": labour_cost,
                "cosmetic_cost": cosmetic_cost,
                "total_cost": total_cost,
                "revenue": revenue,
                "profit": profit,
                "margin": round(margin, 1),
                "lot_id": str(lot.id),
            })
    except Exception:
        _log.exception("lot_pl failed")

    # ── Low stock + financial totals ──────────────────────────────────────────
    low_stock: list = []
    month_revenue = 0.0
    total_revenue = 0.0
    total_investment = 0.0
    total_parts_cost = 0.0
    total_labour_cost = 0.0
    total_cosmetic_cost = 0.0
    overall_profit = 0.0
    try:
        low_stock_result = await db.execute(
            select(SparePart).where(SparePart.qty_in_stock <= SparePart.min_stock_alert)
        )
        low_stock = low_stock_result.scalars().all()

        month_revenue_result = await db.execute(
            select(func.coalesce(func.sum(Sale.sale_price), 0))
            .where(func.date(Sale.sold_at) >= date(today.year, today.month, 1))
        )
        month_revenue = float(month_revenue_result.scalar() or 0)

        total_revenue_result = await db.execute(select(func.coalesce(func.sum(Sale.sale_price), 0)))
        total_revenue = float(total_revenue_result.scalar() or 0)

        total_investment_result = await db.execute(select(func.coalesce(func.sum(Lot.buying_price), 0)))
        total_investment = float(total_investment_result.scalar() or 0)

        total_parts_cost_result = await db.execute(
            select(func.coalesce(func.sum(SparePartConsumption.total_cost), 0))
        )
        total_parts_cost = float(total_parts_cost_result.scalar() or 0)

        total_labour_cost_result = await db.execute(
            select(func.coalesce(func.sum(RepairAttempt.cost), 0))
        )
        total_labour_cost = float(total_labour_cost_result.scalar() or 0)

        total_cosmetic_cost = sum(r["cosmetic_cost"] for r in lot_pl)
        overall_profit = total_revenue - total_investment - total_parts_cost - total_labour_cost - total_cosmetic_cost
    except Exception:
        _log.exception("financials failed")

    # ── Apply stage filter to stage_counts display ───────────────────────────
    if stage_filter:
        filtered_stage_counts = {stage_filter: stage_counts.get(stage_filter, 0)}
    else:
        filtered_stage_counts = stage_counts

    # ── Apply date-range filter to lot_pl ────────────────────────────────────
    try:
        if pl_from:
            _pf = datetime.strptime(pl_from, "%Y-%m-%d")
            lot_pl = [r for r in lot_pl
                      if r.get("purchase_date") and r["purchase_date"] >= _pf]
        if pl_to:
            _pt = datetime.strptime(pl_to, "%Y-%m-%d")
            lot_pl = [r for r in lot_pl
                      if r.get("purchase_date") and r["purchase_date"] <= _pt]
    except Exception:
        pass

    # ── Location gap count for dashboard badge ────────────────────────────────
    try:
        gap_ids, gap_in_hand, gap_never = await _gap_devices(db)
        location_gap_count = len(gap_ids)
        location_in_hand_count = len(gap_in_hand)
        location_never_count = len(gap_never)
    except Exception:
        location_gap_count = 0
        location_in_hand_count = 0
        location_never_count = 0

    # ── Recent stage movements ────────────────────────────────────────────────
    recent_movements: list = []
    try:
        recent_movements_result = await db.execute(
            select(StageMovement, Device.barcode, Device.brand, Device.model)
            .join(Device, StageMovement.device_id == Device.id)
            .order_by(StageMovement.moved_at.desc())
            .limit(10)
        )
        recent_movements = recent_movements_result.all()
    except Exception:
        _log.exception("recent_movements failed")

    # ── My Work Queue — actual devices in the user's active stages ───────────
    ROLE_STAGE_MAP = {
        "l1_engineer":       [DeviceStage.l1],
        "l2_engineer":       [DeviceStage.l2],
        "l3_engineer":       [DeviceStage.l3],
        "qc_inspector":      [DeviceStage.qc_check, DeviceStage.final_qc],
        "inventory_manager": [DeviceStage.grn, DeviceStage.iqc, DeviceStage.stock_in],
        "sales":             [DeviceStage.ready_to_sale],
        "sales_manager":     [DeviceStage.ready_to_sale, DeviceStage.sold],
    }
    role_val = current_user.role.value if current_user.role else ""
    wq_stages = ROLE_STAGE_MAP.get(role_val, [])
    if current_user.role and current_user.role.value == "admin":
        wq_stages = list(DeviceStage)

    work_queue_devices = []
    if wq_stages:
        try:
            wq_result = await db.execute(
                select(Device)
                .where(Device.current_stage.in_(wq_stages))
                .order_by(Device.updated_at.asc())
                .limit(15)
            )
            work_queue_devices = wq_result.scalars().all()
        except Exception:
            _log.exception("work_queue_devices failed for role=%s", role_val)

    # ── Today's follow-ups (dealer calls + CRM activities due today) ──────────
    try:
        dealer_followup_count = (await db.execute(
            select(func.count(DealerCall.id))
            .where(
                DealerCall.next_followup_date.isnot(None),
                func.date(DealerCall.next_followup_date) <= today,
            )
        )).scalar() or 0
        crm_followup_count = (await db.execute(
            select(func.count(CRMActivity.id))
            .where(
                CRMActivity.next_followup.isnot(None),
                CRMActivity.followup_done == False,
                func.date(CRMActivity.next_followup) <= today,
            )
        )).scalar() or 0
        today_followups = dealer_followup_count + crm_followup_count
    except Exception:
        today_followups = 0

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "current_user": current_user,
        "now": app_now(),
        "work_queue_devices": work_queue_devices,
        "stage_counts": filtered_stage_counts,
        "stage_filter": stage_filter,
        "pl_from": pl_from,
        "pl_to": pl_to,
        "all_stages": list(DeviceStage),
        "category_counts": category_counts,
        "total_devices": total_devices,
        "laptops_available": laptops_available,
        "desktops_available": desktops_available,
        "tft_available": tft_available,
        "all_available": all_available,
        "user_queue": user_queue,
        "chart_stages": chart_stages,
        "chart_data": chart_data,
        "lot_pl": lot_pl,
        "low_stock": low_stock,
        "month_revenue": month_revenue,
        "total_revenue": total_revenue,
        "total_investment": total_investment,
        "total_parts_cost": total_parts_cost,
        "total_labour_cost": total_labour_cost,
        "total_cosmetic_cost": total_cosmetic_cost,
        "overall_profit": overall_profit,
        "recent_movements": recent_movements,
        "today": today,
        "location_gap_count": location_gap_count,
        "location_in_hand_count": location_in_hand_count,
        "location_never_count": location_never_count,
        "today_followups": today_followups,
    })
