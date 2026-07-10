import logging
import time as _time
from templates_config import templates
from datetime import datetime, date
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
from models.crm import CRMActivity, CRMContact, CRMPurchaseOrder, CRMSourcingDeal
from models.parts_grn import PartsGRN, PartsGRNLineItem
from models.part_request import PartSourcingRequest
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

# ── 30-second aggregate cache (stage counts + category counts) ────────────────
# These two GROUP-BY queries are the dashboard's most expensive and identical
# for every logged-in user. Cache the result for 30 s to avoid hammering the DB
# on every page refresh.
_AGG_CACHE: dict = {"stage": None, "cat": None, "ts": 0.0}
_AGG_TTL = 30  # seconds


async def _count(db: AsyncSession, *filters) -> int:
    result = await db.execute(select(func.count(Device.id)).where(*filters))
    return result.scalar() or 0


@router.get("/", response_class=HTMLResponse)
async def home(current_user: User = Depends(get_current_user)):
    """Application home page — Inventory Search, for every user.
    no-store so browsers never cache this redirect across deploys/logins."""
    resp = RedirectResponse(url="/devices", status_code=302)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    stage_filter: str = Query(default=""),
    pl_from: str = Query(default=""),
    pl_to: str = Query(default=""),
):
    today = app_now().date()

    # ── Stage + category counts (cached 30 s) ────────────────────────────────
    _now = _time.monotonic()
    if _AGG_CACHE["ts"] and (_now - _AGG_CACHE["ts"]) < _AGG_TTL and _AGG_CACHE["stage"]:
        stage_counts = _AGG_CACHE["stage"]
        category_counts = _AGG_CACHE["cat"]
    else:
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

        _AGG_CACHE.update({"stage": stage_counts, "cat": category_counts, "ts": _now})

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

    # ── Financial totals ───────────────────────────────────────────────────────
    month_revenue = 0.0
    total_revenue = 0.0
    total_investment = 0.0
    total_parts_cost = 0.0
    total_labour_cost = 0.0
    total_cosmetic_cost = 0.0
    overall_profit = 0.0
    try:
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

    # ── Admin analytics: 12 stat cards + 5 weekly/pie charts ──────────────────
    # Only computed for admin (the section is admin-gated in the template) —
    # skips the extra query load for every other role's dashboard render.
    admin_analytics: dict = {}
    admin_charts: dict = {}
    if current_user.role == UserRole.admin:
        try:
            def _week_key(dt):
                if not dt:
                    return None
                iso = dt.isocalendar()
                return f"{iso[0]}-W{iso[1]:02d}"

            def _last_n_week_keys(n=8):
                from datetime import timedelta
                keys = []
                d = today
                seen = set()
                while len(seen) < n:
                    k = _week_key(datetime(d.year, d.month, d.day))
                    if k not in seen:
                        seen.add(k)
                        keys.append(k)
                    d -= timedelta(days=7)
                return list(reversed(keys))

            week_labels = _last_n_week_keys(8)

            def _weekly_series(rows, date_getter, value_getter=lambda r: 1):
                buckets = {wk: 0 for wk in week_labels}
                for r in rows:
                    wk = _week_key(date_getter(r))
                    if wk in buckets:
                        buckets[wk] += value_getter(r)
                return [buckets[wk] for wk in week_labels]

            # a. Total Products (To be Sold / Mark Sold)
            admin_analytics["products_to_be_sold"] = stage_counts.get(DeviceStage.ready_to_sale.value, 0)
            admin_analytics["products_sold"] = stage_counts.get(DeviceStage.sold.value, 0)

            # b. Total Stock (In Stock / Sold / Returned)
            admin_analytics["stock_in_stock"] = stage_counts.get(DeviceStage.stock_in.value, 0)
            admin_analytics["stock_sold"] = stage_counts.get(DeviceStage.sold.value, 0)
            admin_analytics["stock_returned"] = stage_counts.get(DeviceStage.returned.value, 0)

            # c. Stage Products (IQC / Inventory / Production / Final IQC)
            admin_analytics["stage_iqc"] = stage_counts.get(DeviceStage.iqc.value, 0)
            admin_analytics["stage_inventory"] = stage_counts.get(DeviceStage.stock_in.value, 0)
            admin_analytics["stage_production"] = stage_counts.get(DeviceStage.trc_production.value, 0)
            admin_analytics["stage_final_iqc"] = stage_counts.get(DeviceStage.final_qc.value, 0)

            # d. Total GRN (in Plan / in TRC)
            grn_status_rows = (await db.execute(
                select(PartsGRN.status, func.count(PartsGRN.id)).group_by(PartsGRN.status)
            )).all()
            grn_status_counts = {s: c for s, c in grn_status_rows}
            admin_analytics["grn_in_plan"] = grn_status_counts.get("in_plan", 0)
            admin_analytics["grn_in_trc"] = grn_status_counts.get("in_trc", 0)

            # e. Total Parts (In Stock / Out of Stock / Consumed / As New vs As Harvest)
            admin_analytics["parts_in_stock"] = (await db.execute(
                select(func.count(SparePart.id)).where(SparePart.qty_in_stock > SparePart.min_stock_alert)
            )).scalar() or 0
            admin_analytics["parts_out_of_stock"] = (await db.execute(
                select(func.count(SparePart.id)).where(SparePart.qty_in_stock <= SparePart.min_stock_alert)
            )).scalar() or 0
            admin_analytics["parts_consumed"] = (await db.execute(
                select(func.coalesce(func.sum(SparePartConsumption.qty_used), 0))
            )).scalar() or 0
            harvest_rows = (await db.execute(
                select(PartsGRNLineItem.is_harvest, func.count(PartsGRNLineItem.id)).group_by(PartsGRNLineItem.is_harvest)
            )).all()
            harvest_counts = {bool(h): c for h, c in harvest_rows}
            admin_analytics["parts_as_new"] = harvest_counts.get(False, 0)
            admin_analytics["parts_as_harvest"] = harvest_counts.get(True, 0)

            # f. Total Dealers (Interested / Not Interested / Followup) — call-outcome
            # counts across all logged calls (approximation: not de-duped per dealer's
            # latest outcome, since that would need a window-function query).
            outcome_rows = (await db.execute(
                select(DealerCall.call_outcome, func.count(DealerCall.id)).group_by(DealerCall.call_outcome)
            )).all()
            outcome_counts = {o: c for o, c in outcome_rows}
            admin_analytics["dealers_interested"] = outcome_counts.get("interested", 0)
            admin_analytics["dealers_not_interested"] = outcome_counts.get("not_interested", 0)
            admin_analytics["dealers_followup"] = outcome_counts.get("followup", 0)

            # g. Total Accounts (Buyer / Seller / Both) — CRMContact.contact_type
            contact_rows = (await db.execute(
                select(CRMContact.contact_type, func.count(CRMContact.id)).group_by(CRMContact.contact_type)
            )).all()
            contact_counts = {t: c for t, c in contact_rows}
            admin_analytics["accounts_buyer"] = contact_counts.get("buyer", 0)
            admin_analytics["accounts_seller"] = contact_counts.get("supplier", 0)
            admin_analytics["accounts_both"] = contact_counts.get("both", 0)

            # h. Total PO (Generated / Closed) — issued/acknowledged vs received/cancelled
            po_status_rows = (await db.execute(
                select(CRMPurchaseOrder.status, func.count(CRMPurchaseOrder.id)).group_by(CRMPurchaseOrder.status)
            )).all()
            po_status_counts = {s: c for s, c in po_status_rows}
            admin_analytics["po_generated"] = po_status_counts.get("issued", 0) + po_status_counts.get("acknowledged", 0)
            admin_analytics["po_closed"] = po_status_counts.get("received", 0) + po_status_counts.get("cancelled", 0)

            # i. Total Source Request (Part / Products)
            admin_analytics["source_request_parts"] = (await db.execute(
                select(func.count(PartSourcingRequest.id))
            )).scalar() or 0
            admin_analytics["source_request_products"] = (await db.execute(
                select(func.count(CRMSourcingDeal.id))
            )).scalar() or 0

            # j. Total Sales (Procurement / Telecaller / Showroom)
            channel_rows = (await db.execute(
                select(Sale.sale_channel, func.count(Sale.id)).group_by(Sale.sale_channel)
            )).all()
            channel_counts = {c: n for c, n in channel_rows}
            admin_analytics["sales_procurement"] = channel_counts.get("procurement", 0)
            admin_analytics["sales_telecaller"] = channel_counts.get("telecaller", 0)
            admin_analytics["sales_showroom"] = channel_counts.get("showroom", 0)

            # k. Total Product Profits — reuses the financials already computed above
            admin_analytics["product_buying"] = total_investment
            admin_analytics["product_sale"] = total_revenue
            admin_analytics["product_profit_pct"] = round((overall_profit / total_revenue * 100), 1) if total_revenue > 0 else 0

            # l. Total Parts Profits — buying value from GRN line items vs used cost
            parts_buying_result = await db.execute(
                select(func.coalesce(func.sum(PartsGRNLineItem.price * PartsGRNLineItem.physical_qty), 0))
            )
            parts_buying = float(parts_buying_result.scalar() or 0)
            admin_analytics["parts_buying"] = parts_buying
            admin_analytics["parts_used"] = total_parts_cost
            admin_analytics["parts_profit_pct"] = round(((parts_buying - total_parts_cost) / parts_buying * 100), 1) if parts_buying > 0 else 0

            # ── Charts ─────────────────────────────────────────────────────────
            admin_charts["week_labels"] = week_labels

            # a. Weekly: Products in IQC / GRN / In Stock (via StageMovement into that stage)
            sm_rows = (await db.execute(
                select(StageMovement.to_stage, StageMovement.moved_at)
                .where(StageMovement.to_stage.in_([DeviceStage.iqc, DeviceStage.grn, DeviceStage.stock_in]))
            )).all()
            admin_charts["products_iqc_weekly"] = _weekly_series([r for r in sm_rows if r[0] == DeviceStage.iqc], lambda r: r[1])
            admin_charts["products_grn_weekly"] = _weekly_series([r for r in sm_rows if r[0] == DeviceStage.grn], lambda r: r[1])
            admin_charts["products_stock_weekly"] = _weekly_series([r for r in sm_rows if r[0] == DeviceStage.stock_in], lambda r: r[1])

            # a2. Weekly: Spare Parts in Sourcing Request / GRN / Harvest
            psr_rows = (await db.execute(select(PartSourcingRequest.created_at))).scalars().all()
            admin_charts["parts_sourcing_weekly"] = _weekly_series(psr_rows, lambda r: r)
            grn_li_rows = (await db.execute(select(PartsGRNLineItem.is_harvest, PartsGRNLineItem.created_at))).all()
            admin_charts["parts_grn_weekly"] = _weekly_series([r for r in grn_li_rows if not r[0]], lambda r: r[1])
            admin_charts["parts_harvest_weekly"] = _weekly_series([r for r in grn_li_rows if r[0]], lambda r: r[1])

            # b. Pie: stage distribution
            admin_charts["stage_pie_labels"] = ["IQC", "Inventory", "Production", "L1", "L2", "L3", "Stress Test", "Final QC"]
            admin_charts["stage_pie_values"] = [
                stage_counts.get(DeviceStage.iqc.value, 0),
                stage_counts.get(DeviceStage.stock_in.value, 0),
                stage_counts.get(DeviceStage.trc_production.value, 0),
                stage_counts.get(DeviceStage.l1.value, 0),
                stage_counts.get(DeviceStage.l2.value, 0),
                stage_counts.get(DeviceStage.l3.value, 0),
                stage_counts.get(DeviceStage.qc_check.value, 0),
                stage_counts.get(DeviceStage.final_qc.value, 0),
            ]

            # c. Weekly: Sales Price — Ready to Sale (moved-in value proxy via count) vs Product Sold (₹)
            rts_rows = (await db.execute(
                select(StageMovement.moved_at).where(StageMovement.to_stage == DeviceStage.ready_to_sale)
            )).scalars().all()
            admin_charts["ready_to_sale_weekly"] = _weekly_series(rts_rows, lambda r: r)
            sold_rows = (await db.execute(select(Sale.sold_at, Sale.sale_price))).all()
            admin_charts["product_sold_price_weekly"] = _weekly_series(sold_rows, lambda r: r[0], lambda r: float(r[1] or 0))

            # d. Weekly: Parts Price — As New vs As Harvest
            grn_li_price_rows = (await db.execute(
                select(PartsGRNLineItem.is_harvest, PartsGRNLineItem.created_at, PartsGRNLineItem.price)
            )).all()
            admin_charts["parts_new_price_weekly"] = _weekly_series(
                [r for r in grn_li_price_rows if not r[0]], lambda r: r[1], lambda r: float(r[2] or 0))
            admin_charts["parts_harvest_price_weekly"] = _weekly_series(
                [r for r in grn_li_price_rows if r[0]], lambda r: r[1], lambda r: float(r[2] or 0))

            # e. Weekly: Sourcing Price — Buyer PO (DealerOrder, dealers buying from
            # OxyPC) vs Seller PO (CRMPurchaseOrder, OxyPC buying from suppliers)
            buyer_po_rows = (await db.execute(select(DealerOrder.order_date, DealerOrder.total_amount))).all()
            admin_charts["buyer_po_weekly"] = _weekly_series(buyer_po_rows, lambda r: r[0], lambda r: float(r[1] or 0))
            seller_po_rows = (await db.execute(select(CRMPurchaseOrder.created_at, CRMPurchaseOrder.total_amount))).all()
            admin_charts["seller_po_weekly"] = _weekly_series(seller_po_rows, lambda r: r[0], lambda r: float(r[1] or 0))
        except Exception:
            _log.exception("admin_analytics failed")

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
        "month_revenue": month_revenue,
        "total_revenue": total_revenue,
        "total_investment": total_investment,
        "total_parts_cost": total_parts_cost,
        "total_labour_cost": total_labour_cost,
        "total_cosmetic_cost": total_cosmetic_cost,
        "overall_profit": overall_profit,
        "admin_analytics": admin_analytics,
        "admin_charts": admin_charts,
        "today": today,
        "location_gap_count": location_gap_count,
        "location_in_hand_count": location_in_hand_count,
        "location_never_count": location_never_count,
        "today_followups": today_followups,
    })
