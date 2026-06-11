# routers/invoices.py
"""Sale Invoice — printable HTML with GST breakdown."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user
from models.user import User
from models.sales import Sale
from models.device import Device
from models.lot import Lot
from routers.settings import get_company_settings

router = APIRouter(prefix="/invoices", tags=["invoices"])


def _compute_gst(
    sale_price: float,
    company_state: str,
    customer_state: str = "Delhi",
    intra_rate: float = 18.0,
    inter_rate: float = 18.0,
) -> dict:
    """Back-calculate GST from inclusive price. Intra-state = CGST+SGST, inter-state = IGST.
    Rates are configurable via CostConfig (gst_rate_intra / gst_rate_inter); default 18%."""
    intra = (customer_state or "Delhi").strip().lower() == company_state.strip().lower()
    if intra:
        taxable = round(sale_price / (1 + intra_rate / 100), 2)
        gst_total = round(sale_price - taxable, 2)
        half = round(gst_total / 2, 2)
        return {
            "taxable": taxable,
            "cgst_rate": intra_rate / 2, "cgst": half,
            "sgst_rate": intra_rate / 2, "sgst": gst_total - half,
            "igst_rate": 0.0, "igst": 0.0,
            "gst_total": gst_total, "grand_total": sale_price, "intra_state": True,
        }
    taxable_inter = round(sale_price / (1 + inter_rate / 100), 2)
    igst = round(sale_price - taxable_inter, 2)
    return {
        "taxable": taxable_inter,
        "cgst_rate": 0.0, "cgst": 0.0,
        "sgst_rate": 0.0, "sgst": 0.0,
        "igst_rate": inter_rate, "igst": igst,
        "gst_total": igst, "grand_total": sale_price, "intra_state": False,
    }


async def _fetch_gst_rates(db: AsyncSession) -> tuple[float, float]:
    """Fetch GST rates from CostConfig; fall back to 18% if not configured."""
    from models.cost_config import CostConfig
    from sqlalchemy import select as _sel
    intra_row = (await db.execute(
        _sel(CostConfig).where(CostConfig.key == "gst_rate_intra")
    )).scalar_one_or_none()
    inter_row = (await db.execute(
        _sel(CostConfig).where(CostConfig.key == "gst_rate_inter")
    )).scalar_one_or_none()
    intra_pct = float(intra_row.value) if intra_row else 18.0
    inter_pct = float(inter_row.value) if inter_row else 18.0
    return intra_pct, inter_pct


@router.get("/print/{sale_id}", response_class=HTMLResponse)
async def print_invoice(
    request: Request,
    sale_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Sale, Device, Lot)
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Sale.id == sale_id)
    )
    row = result.first()
    if not row:
        return RedirectResponse(url="/sales?error=Sale+not+found", status_code=302)
    sale, device, lot = row

    company    = await get_company_settings(db)
    gst_intra_pct, gst_inter_pct = await _fetch_gst_rates(db)
    gst        = _compute_gst(
        float(sale.sale_price), company["state"],
        getattr(sale, "customer_state", None) or "Delhi",
        intra_rate=gst_intra_pct, inter_rate=gst_inter_pct,
    )
    invoice_no = getattr(sale, "invoice_no", None) or sale.sale_number

    return templates.TemplateResponse("invoices/print.html", {
        "request": request, "current_user": current_user,
        "sale": sale, "device": device, "lot": lot,
        "company": company, "invoice_no": invoice_no, "gst": gst,
    })


@router.get("/waybill/{sale_id}", response_class=HTMLResponse)
async def print_waybill(
    request: Request,
    sale_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Sale, Device, Lot)
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Sale.id == sale_id)
    )
    row = result.first()
    if not row:
        return RedirectResponse(url="/sales?error=Sale+not+found", status_code=302)
    sale, device, lot = row
    company    = await get_company_settings(db)
    invoice_no = getattr(sale, "invoice_no", None) or sale.sale_number
    return templates.TemplateResponse("invoices/waybill.html", {
        "request": request, "current_user": current_user,
        "sale": sale, "device": device, "lot": lot,
        "company": company, "invoice_no": invoice_no,
    })
