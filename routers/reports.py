from templates_config import templates
import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import extract, select, func
from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement, STAGE_LABELS
from models.engines import RepairAttempt
from models.lot import Lot
from models.sales import Sale
from models.spare_parts import SparePartConsumption
from auth.dependencies import get_current_user, require_roles

# Maximum rows returned by any CSV export endpoint — prevents OOM on large datasets
MAX_EXPORT_ROWS = 5_000

# Financial reports — restricted to management/senior roles only
_REPORT_ROLES = require_roles(
    UserRole.inventory_manager,
    UserRole.qc_inspector,
    UserRole.sales,
)

# Receivables — sales management + inventory; admin always granted by require_roles()
_require_receivables = require_roles(
    UserRole.sales_manager,
    UserRole.inventory_manager,
)
router = APIRouter(
    prefix="/reports",
    tags=["reports"],
    dependencies=[Depends(_REPORT_ROLES)],
)


@router.get("/lot-pl", response_class=HTMLResponse)
async def lot_pl_report(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    lots_result = await db.execute(select(Lot).order_by(Lot.created_at.desc()))
    lots = lots_result.scalars().all()

    # ── Batch aggregation queries (replaces N×4 sequential queries) ──────────

    # Revenue per lot: SUM(sale_price) via devices JOIN sales
    rev_rows = await db.execute(
        select(Device.lot_id, func.coalesce(func.sum(Sale.sale_price), 0).label("revenue"))
        .join(Sale, Sale.device_id == Device.id)
        .group_by(Device.lot_id)
    )
    rev_by_lot = {str(r.lot_id): float(r.revenue) for r in rev_rows}

    # Parts cost per lot: SUM(spare_parts_consumption.total_cost) WHERE lot_id IS NOT NULL
    parts_rows = await db.execute(
        select(SparePartConsumption.lot_id, func.coalesce(func.sum(SparePartConsumption.total_cost), 0).label("parts"))
        .where(SparePartConsumption.lot_id.isnot(None))
        .group_by(SparePartConsumption.lot_id)
    )
    parts_by_lot = {str(r.lot_id): float(r.parts) for r in parts_rows}

    # Labour cost per lot: SUM(repair_attempts.cost) joined via devices
    labour_rows = await db.execute(
        select(Device.lot_id, func.coalesce(func.sum(RepairAttempt.cost), 0).label("labour"))
        .join(RepairAttempt, RepairAttempt.device_id == Device.id)
        .group_by(Device.lot_id)
    )
    labour_by_lot = {str(r.lot_id): float(r.labour) for r in labour_rows}

    # Sold count per lot
    sold_rows = await db.execute(
        select(Device.lot_id, func.count(Device.id).label("sold"))
        .where(Device.current_stage == DeviceStage.sold)
        .group_by(Device.lot_id)
    )
    sold_by_lot = {str(r.lot_id): r.sold for r in sold_rows}

    # Total device count per lot
    count_rows = await db.execute(
        select(Device.lot_id, func.count(Device.id).label("cnt"))
        .group_by(Device.lot_id)
    )
    count_by_lot = {str(r.lot_id): r.cnt for r in count_rows}

    lot_pl = []
    for lot in lots:
        lid     = str(lot.id)
        revenue = rev_by_lot.get(lid, 0.0)
        parts   = parts_by_lot.get(lid, 0.0)
        labour  = labour_by_lot.get(lid, 0.0)
        buying  = float(lot.buying_price or 0)
        total_cost = buying + parts + labour
        profit  = revenue - total_cost
        margin  = round(profit / revenue * 100, 1) if revenue > 0 else 0
        lot_pl.append({
            "lot_number":   lot.lot_number,
            "supplier":     lot.supplier_name,
            "purchase_date":lot.purchase_date,
            "qty":          lot.qty,
            "devices":      count_by_lot.get(lid, 0),
            "sold":         sold_by_lot.get(lid, 0),
            "buying_price": buying,
            "parts_cost":   parts,
            "labour_cost":  labour,
            "total_cost":   total_cost,
            "revenue":      revenue,
            "profit":       profit,
            "margin":       margin,
            "lot_id":       lid,
        })
    return templates.TemplateResponse("reports/lot_pl.html", {
        "request": request, "lot_pl": lot_pl, "current_user": current_user
    })


@router.get("/stage-movement", response_class=HTMLResponse)
async def stage_movement_report(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(
        select(StageMovement, Device.barcode, Device.brand, Device.model)
        .join(Device, StageMovement.device_id == Device.id)
        .order_by(StageMovement.moved_at.desc())
        .limit(500)
    )
    movements = result.all()
    return templates.TemplateResponse("reports/stage_movement.html", {
        "request": request, "movements": movements, "current_user": current_user
    })


@router.get("/sales", response_class=HTMLResponse)
async def sales_report(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Default: last 90 days; override with ?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD
    default_from = (datetime.now() - timedelta(days=90)).date()
    from_date = request.query_params.get("from_date", str(default_from))
    to_date = request.query_params.get("to_date", str(datetime.now().date()))

    result = await db.execute(
        select(Sale, Device.barcode, Device.brand, Device.model, Device.grade, Lot.lot_number)
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Sale.sold_at >= from_date, Sale.sold_at <= to_date)
        .order_by(Sale.sold_at.desc())
        .limit(1000)
    )
    sales = result.all()
    total = sum(float(s.Sale.sale_price or 0) for s in sales)
    return templates.TemplateResponse("reports/sales_report.html", {
        "request": request, "sales": sales, "total": total, "current_user": current_user,
        "from_date": from_date, "to_date": to_date,
    })


@router.get("/export/lot-pl")
async def export_lot_pl(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    lots_result = await db.execute(
        select(Lot).order_by(Lot.created_at.desc()).limit(MAX_EXPORT_ROWS)
    )
    lots = lots_result.scalars().all()

    rev_rows = await db.execute(
        select(Device.lot_id, func.coalesce(func.sum(Sale.sale_price), 0).label("revenue"))
        .join(Sale, Sale.device_id == Device.id).group_by(Device.lot_id)
    )
    rev_by_lot = {str(r.lot_id): float(r.revenue) for r in rev_rows}

    parts_rows = await db.execute(
        select(SparePartConsumption.lot_id, func.coalesce(func.sum(SparePartConsumption.total_cost), 0).label("parts"))
        .where(SparePartConsumption.lot_id.isnot(None)).group_by(SparePartConsumption.lot_id)
    )
    parts_by_lot = {str(r.lot_id): float(r.parts) for r in parts_rows}

    labour_rows = await db.execute(
        select(Device.lot_id, func.coalesce(func.sum(RepairAttempt.cost), 0).label("labour"))
        .join(RepairAttempt, RepairAttempt.device_id == Device.id).group_by(Device.lot_id)
    )
    labour_by_lot = {str(r.lot_id): float(r.labour) for r in labour_rows}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Lot#", "Supplier", "Date", "Qty", "Buying Price", "Parts Cost", "Labour Cost", "Total Cost", "Revenue", "Profit", "Margin%"])
    for lot in lots:
        lid = str(lot.id)
        revenue = rev_by_lot.get(lid, 0.0)
        parts   = parts_by_lot.get(lid, 0.0)
        labour  = labour_by_lot.get(lid, 0.0)
        buying  = float(lot.buying_price or 0)
        total   = buying + parts + labour
        profit  = revenue - total
        margin  = round(profit / revenue * 100, 1) if revenue > 0 else 0
        writer.writerow([lot.lot_number, lot.supplier_name, lot.purchase_date.strftime("%d-%m-%Y"),
                         lot.qty, buying, parts, labour, total, revenue, profit, margin])
    if len(lots) == MAX_EXPORT_ROWS:
        writer.writerow(["# TRUNCATED", f"Export capped at {MAX_EXPORT_ROWS} rows", "", "", "", "", "", "", "", "", ""])
    output.seek(0)
    return StreamingResponse(io.BytesIO(output.getvalue().encode()), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=lot_pl.csv"})


@router.get("/export/sales")
async def export_sales(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(
        select(Sale, Device.barcode, Device.brand, Device.model, Lot.lot_number)
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
        .order_by(Sale.sold_at.desc())
        .limit(MAX_EXPORT_ROWS)
    )
    sales = result.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Sale#", "Date", "Barcode", "Brand", "Model", "Lot", "Price", "Customer", "Phone", "Payment", "Sold By"])
    for row in sales:
        s = row.Sale
        writer.writerow([s.sale_number, s.sold_at.strftime("%d-%m-%Y"), row.barcode,
                         row.brand, row.model, row.lot_number, float(s.sale_price or 0),
                         s.customer_name, s.customer_phone, s.payment_mode, s.sold_by])
    if len(sales) == MAX_EXPORT_ROWS:
        writer.writerow(["# TRUNCATED", f"Export capped at {MAX_EXPORT_ROWS} rows", "", "", "", "", "", "", "", "", ""])
    output.seek(0)
    return StreamingResponse(io.BytesIO(output.getvalue().encode()), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=sales.csv"})


@router.get("/business-pl", response_class=HTMLResponse)
async def business_pl(
    request: Request,
    year: int = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not year:
        year = app_now().year

    # ── Revenue per month (single GROUP BY query) ────────────────────────────
    rev_result = await db.execute(
        select(
            extract("month", Sale.sold_at).label("month"),
            func.coalesce(func.sum(Sale.sale_price), 0).label("revenue"),
        )
        .where(extract("year", Sale.sold_at) == year)
        .group_by(extract("month", Sale.sold_at))
    )
    rev_by_month = {int(r.month): float(r.revenue) for r in rev_result}
    monthly_rev = [rev_by_month.get(m, 0.0) for m in range(1, 13)]

    # ── Device buying-price COGS per month (single GROUP BY query) ──────────
    cogs_result = await db.execute(
        select(
            extract("month", Sale.sold_at).label("month"),
            func.coalesce(func.sum(Device.device_price), 0).label("device_cogs"),
        )
        .join(Device, Sale.device_id == Device.id)
        .where(extract("year", Sale.sold_at) == year)
        .group_by(extract("month", Sale.sold_at))
    )
    cogs_by_month = {int(r.month): float(r.device_cogs) for r in cogs_result}
    monthly_device_cogs = [cogs_by_month.get(m, 0.0) for m in range(1, 13)]

    # ── Repair parts COGS per month (single GROUP BY query) ─────────────────
    # Join path: SparePartConsumption.device_id → Device.id → Sale.device_id
    parts_result = await db.execute(
        select(
            extract("month", Sale.sold_at).label("month"),
            func.coalesce(func.sum(SparePartConsumption.total_cost), 0).label("parts_cost"),
        )
        .join(Device, SparePartConsumption.device_id == Device.id)
        .join(Sale, Sale.device_id == Device.id)
        .where(SparePartConsumption.device_id.isnot(None))
        .where(extract("year", Sale.sold_at) == year)
        .group_by(extract("month", Sale.sold_at))
    )
    parts_by_month = {int(r.month): float(r.parts_cost) for r in parts_result}
    monthly_parts_cogs = [parts_by_month.get(m, 0.0) for m in range(1, 13)]

    monthly_cogs = [d + p for d, p in zip(monthly_device_cogs, monthly_parts_cogs)]

    # ── Year totals ──────────────────────────────────────────────────────────
    total_revenue = float((await db.execute(
        select(func.coalesce(func.sum(Sale.sale_price), 0))
        .where(extract("year", Sale.sold_at) == year)
    )).scalar() or 0)
    total_sales_ct = (await db.execute(
        select(func.count(Sale.id))
        .where(extract("year", Sale.sold_at) == year)
    )).scalar() or 0
    inv_value = float((await db.execute(
        select(func.coalesce(func.sum(Device.device_price), 0))
        .where(Device.current_stage.notin_(["sold", "scrapped"]))
    )).scalar() or 0)

    total_cogs        = sum(monthly_cogs)
    total_device_cogs = sum(monthly_device_cogs)
    total_parts_cogs  = sum(monthly_parts_cogs)
    gross_profit      = total_revenue - total_cogs
    gross_margin      = round(gross_profit / total_revenue * 100, 1) if total_revenue > 0 else 0

    return templates.TemplateResponse("reports/business_pl.html", {
        "request": request, "current_user": current_user,
        "year": year,
        "monthly_rev":          monthly_rev,
        "monthly_device_cogs":  monthly_device_cogs,
        "monthly_parts_cogs":   monthly_parts_cogs,
        "monthly_cogs":         monthly_cogs,
        "monthly_profit":       [r - c for r, c in zip(monthly_rev, monthly_cogs)],
        "total_revenue":        total_revenue,
        "total_cogs":           total_cogs,
        "total_device_cogs":    total_device_cogs,
        "total_parts_cogs":     total_parts_cogs,
        "gross_profit":         gross_profit,
        "gross_margin":         gross_margin,
        "total_sales_ct":       total_sales_ct,
        "avg_sale_price":       round(total_revenue / total_sales_ct, 0) if total_sales_ct else 0,
        "inv_value":            inv_value,
    })


@router.get("/stock-aging", response_class=HTMLResponse)
async def stock_aging_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    EXCLUDED_VALUES = ["sold", "scrapped", "returned"]
    result = await db.execute(
        select(Device)
        .where(Device.current_stage.notin_(EXCLUDED_VALUES))
        .order_by(Device.current_stage, Device.created_at)
    )
    devices = result.scalars().all()

    now = app_now()
    BRACKETS = [
        ("0–7 days",   0,   7),
        ("8–30 days",  8,  30),
        ("31–60 days", 31, 60),
        ("61–90 days", 61, 90),
        ("90+ days",   91, 9999),
    ]
    bracket_labels = [b[0] for b in BRACKETS]

    stage_data     = defaultdict(lambda: {b[0]: {"count": 0, "cost": 0.0} for b in BRACKETS})
    stage_totals   = defaultdict(lambda: {"count": 0, "cost": 0.0})
    bracket_totals = {b[0]: {"count": 0, "cost": 0.0} for b in BRACKETS}
    grand          = {"count": 0, "cost": 0.0}
    aged_list      = []

    for dev in devices:
        age   = (now - dev.created_at).days
        cost  = float(dev.device_price or 0)
        blabel = BRACKETS[-1][0]
        for label, lo, hi in BRACKETS:
            if lo <= age <= hi:
                blabel = label
                break

        try:
            slabel = STAGE_LABELS.get(DeviceStage(dev.current_stage), str(dev.current_stage))
        except ValueError:
            slabel = str(dev.current_stage)

        stage_data[slabel][blabel]["count"]    += 1
        stage_data[slabel][blabel]["cost"]     += cost
        stage_totals[slabel]["count"]          += 1
        stage_totals[slabel]["cost"]           += cost
        bracket_totals[blabel]["count"]        += 1
        bracket_totals[blabel]["cost"]         += cost
        grand["count"] += 1
        grand["cost"]  += cost
        aged_list.append({
            "barcode": dev.barcode,
            "brand":   dev.brand or "—",
            "model":   dev.model or "—",
            "stage":   slabel,
            "age":     age,
            "cost":    cost,
            "grade":   dev.grade or "—",
        })

    aged_list.sort(key=lambda x: x["age"], reverse=True)

    return templates.TemplateResponse("reports/stock_aging.html", {
        "request":        request,
        "current_user":   current_user,
        "stage_data":     dict(stage_data),
        "stage_totals":   dict(stage_totals),
        "bracket_totals": bracket_totals,
        "brackets":       bracket_labels,
        "grand":          grand,
        "oldest_devices": aged_list[:50],
    })


@router.get("/receivables", response_class=HTMLResponse)
async def receivables_report(
    request: Request,
    export: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_receivables),
):
    """Dealer receivables ageing — outstanding orders bucketed by days overdue."""
    from decimal import Decimal
    from models.dealers import Dealer, DealerOrder

    OUTSTANDING = ("pending", "confirmed", "delivered")
    now = app_now()

    rows_result = await db.execute(
        select(DealerOrder, Dealer)
        .join(Dealer, DealerOrder.dealer_id == Dealer.id)
        .where(DealerOrder.due_amount > 0, DealerOrder.status.in_(OUTSTANDING))
        .order_by(Dealer.business_name, DealerOrder.order_date)
    )
    rows = rows_result.all()

    def _bucket(order):
        if not order.payment_due_date:
            return "current"
        days = (now - order.payment_due_date).days
        if days <= 0:
            return "current"
        if days <= 30:
            return "d30"
        if days <= 60:
            return "d60"
        if days <= 90:
            return "d90"
        return "d90plus"

    ageing = []
    totals = {k: Decimal("0") for k in ("current", "d30", "d60", "d90", "d90plus")}
    for order, dealer in rows:
        b = _bucket(order)
        due = order.due_amount or Decimal("0")
        ageing.append({"order": order, "dealer": dealer, "bucket": b, "due": due})
        totals[b] += due
    totals["grand"] = sum(totals.values())

    if export == "csv":
        def _gen():
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["Dealer", "Order #", "Order Date", "Due Date", "Bucket", "Due Amount"])
            for r in ageing:
                dealer_name = r["dealer"].business_name or f"{r['dealer'].first_name or ''} {r['dealer'].last_name or ''}".strip()
                w.writerow([
                    dealer_name,
                    r["order"].order_number,
                    r["order"].order_date.strftime("%d-%m-%Y"),
                    r["order"].payment_due_date.strftime("%d-%m-%Y") if r["order"].payment_due_date else "",
                    r["bucket"],
                    float(r["due"]),
                ])
            yield buf.getvalue().encode("utf-8-sig")
        return StreamingResponse(
            _gen(),
            media_type="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": f"attachment; filename=receivables_{now.strftime('%Y%m%d')}.csv"},
        )

    return templates.TemplateResponse("reports/receivables.html", {
        "request": request,
        "current_user": current_user,
        "ageing": ageing,
        "totals": totals,
        "as_of": now,
    })


@router.get("/overdue", response_class=HTMLResponse)
async def overdue_report(
    request: Request,
    stage: str = Query(default=""),
    min_days: int = Query(default=3, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = app_now()
    cutoff = now - timedelta(days=min_days)

    filters = [
        Device.current_stage.notin_([DeviceStage.sold, DeviceStage.scrapped]),
        Device.updated_at <= cutoff,
    ]
    if stage:
        try:
            filters.append(Device.current_stage == DeviceStage(stage))
        except ValueError:
            pass

    stmt = (
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id, isouter=True)
        .where(*filters)
        .order_by(Device.updated_at.asc())
        .limit(500)
    )

    result = await db.execute(stmt)
    rows = []
    for device, lot_number in result.all():
        days = (now - device.updated_at).days if device.updated_at else 0
        rows.append({
            "barcode":    device.barcode,
            "brand":      device.brand or "",
            "model":      device.model or "",
            "stage":      device.current_stage.value if device.current_stage else "",
            "days":       days,
            "lot_number": lot_number or "",
            "updated_at": device.updated_at,
        })

    return templates.TemplateResponse("reports/overdue.html", {
        "request": request,
        "rows": rows,
        "stage": stage,
        "min_days": min_days,
        "all_stages": [s for s in DeviceStage if s not in (DeviceStage.sold, DeviceStage.scrapped)],
        "current_user": current_user,
    })


@router.get("/overdue/csv")
async def overdue_csv(
    stage: str = Query(default=""),
    min_days: int = Query(default=3, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = app_now()
    cutoff = now - timedelta(days=min_days)

    filters = [
        Device.current_stage.notin_([DeviceStage.sold, DeviceStage.scrapped]),
        Device.updated_at <= cutoff,
    ]
    if stage:
        try:
            filters.append(Device.current_stage == DeviceStage(stage))
        except ValueError:
            pass

    stmt = (
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id, isouter=True)
        .where(*filters)
        .order_by(Device.updated_at.asc())
    )

    result = await db.execute(stmt.limit(MAX_EXPORT_ROWS))
    rows_all = result.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Barcode", "Brand", "Model", "Stage", "Days in Stage", "Lot Number", "Last Updated"])
    for device, lot_number in rows_all:
        days = (now - device.updated_at).days if device.updated_at else 0
        writer.writerow([
            device.barcode,
            device.brand or "",
            device.model or "",
            device.current_stage.value if device.current_stage else "",
            days,
            lot_number or "",
            device.updated_at.strftime("%Y-%m-%d") if device.updated_at else "",
        ])
    if len(rows_all) == MAX_EXPORT_ROWS:
        writer.writerow(["# TRUNCATED", f"Export capped at {MAX_EXPORT_ROWS} rows", "", "", "", "", ""])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=overdue_devices.csv"},
    )
