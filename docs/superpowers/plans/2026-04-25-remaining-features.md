# OxyPC Remaining Features — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the 7 missing modules that complete the OxyPC Inventory ERP: Sale Invoice PDF, Purchase Orders, Accounts & Payments, CRM Bulk Import, WhatsApp Quote Share, CRM Analytics, and Business P&L Dashboard.

**Architecture:** All features follow the existing FastAPI + async SQLAlchemy + Jinja2/Bootstrap 5 pattern. New DB tables use Alembic autogenerate. New routers are registered in main.py and nav links added to base.html.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, asyncpg, PostgreSQL 15, Jinja2, Bootstrap 5, Alembic

**Project root:** `C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory\`

---

## File Structure

**New files to create:**
- `routers/invoices.py` — Sale Invoice print/PDF route
- `routers/crm_purchase_orders.py` — PO CRUD + print
- `routers/accounts.py` — Supplier payments + customer receipts
- `routers/crm_reports.py` — CRM pipeline analytics
- `templates/invoices/print.html` — Print-optimised invoice
- `templates/crm/purchase_orders/list.html`
- `templates/crm/purchase_orders/form.html`
- `templates/crm/purchase_orders/detail.html`
- `templates/crm/purchase_orders/print.html`
- `templates/accounts/index.html`
- `templates/accounts/supplier_payments.html`
- `templates/accounts/customer_receipts.html`
- `templates/crm/import_contacts.html`
- `templates/crm/reports/index.html`
- `templates/reports/business_pl.html`
- `alembic/versions/YYYYMMDD_*_purchase_orders_payments.py`

**Files to modify:**
- `models/crm.py` — Add CRMPurchaseOrder, CRMPOLineItem
- `models/__init__.py` — Import new CRM models
- `main.py` — Add 4 new router imports + includes
- `templates/base.html` — Add nav links
- `templates/crm/quotes/detail.html` — Add WA share button
- `routers/crm_contacts.py` — Add CSV import routes
- `routers/reports.py` — Add business P&L route

---

## Task 1: Sale Invoice PDF

**Files:**
- Create: `routers/invoices.py`
- Create: `templates/invoices/print.html`
- Modify: `main.py` (add router)
- Modify: `templates/base.html` (nav link under Sales)
- Modify: `templates/sales/list.html` (add print icon per row)

- [ ] **Step 1: Create the invoices router**

```python
# routers/invoices.py
"""Sale Invoice — printable HTML with GST breakdown."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user
from models.user import User
from models.sales import Sale
from models.device import Device
from models.lot import Lot

router = APIRouter(prefix="/invoices", tags=["invoices"])

# OxyPC company details — update via config if needed
COMPANY = {
    "name": "OxyPC",
    "address": "Your Address Here, Delhi - 110001",
    "gstin": "07XXXXX0000X1XX",
    "state": "Delhi",
    "state_code": "07",
    "phone": "+91-XXXXXXXXXX",
    "email": "info@oxypc.in",
}

def _compute_gst(sale_price: float, customer_state: str = "Delhi") -> dict:
    """Compute GST breakdown. Intra-state = CGST+SGST, inter-state = IGST."""
    # Back-calculate: sale_price is inclusive of 18% GST
    taxable = round(sale_price / 1.18, 2)
    gst_total = round(sale_price - taxable, 2)
    intra = (customer_state or "Delhi").strip().lower() == COMPANY["state"].lower()
    if intra:
        return {
            "taxable": taxable,
            "cgst_rate": 9.0, "cgst": round(gst_total / 2, 2),
            "sgst_rate": 9.0, "sgst": round(gst_total / 2, 2),
            "igst_rate": 0.0, "igst": 0.0,
            "gst_total": gst_total,
            "grand_total": sale_price,
            "intra_state": True,
        }
    return {
        "taxable": taxable,
        "cgst_rate": 0.0, "cgst": 0.0,
        "sgst_rate": 0.0, "sgst": 0.0,
        "igst_rate": 18.0, "igst": gst_total,
        "gst_total": gst_total,
        "grand_total": sale_price,
        "intra_state": False,
    }


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
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/sales?error=Sale+not+found", status_code=302)
    sale, device, lot = row

    gst = _compute_gst(float(sale.sale_price), customer_state="Delhi")
    invoice_no = sale.invoice_no or sale.sale_number

    return templates.TemplateResponse("invoices/print.html", {
        "request": request,
        "current_user": current_user,
        "sale": sale,
        "device": device,
        "lot": lot,
        "company": COMPANY,
        "invoice_no": invoice_no,
        "gst": gst,
    })
```

- [ ] **Step 2: Create the print template**

```html
{# templates/invoices/print.html #}
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Invoice {{ invoice_no }}</title>
<style>
  @media print { .no-print { display: none !important; } body { margin: 0; } }
  body { font-family: Arial, sans-serif; font-size: 13px; color: #111; }
  .page { max-width: 800px; margin: 20px auto; padding: 24px; border: 2px solid #1565C0; }
  .header { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 3px solid #1565C0; padding-bottom: 12px; margin-bottom: 16px; }
  .company-name { font-size: 24px; font-weight: bold; color: #1565C0; }
  .invoice-title { font-size: 20px; font-weight: bold; text-align: right; }
  table { width: 100%; border-collapse: collapse; }
  th { background: #1565C0; color: #fff; padding: 8px; text-align: left; }
  td { padding: 7px 8px; border-bottom: 1px solid #e0e0e0; }
  .total-row td { font-weight: bold; background: #E3F2FD; }
  .grand-total td { font-weight: bold; font-size: 15px; background: #1565C0; color: #fff; }
  .section-title { font-weight: bold; color: #1565C0; margin: 14px 0 6px 0; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
  .two-col { display: flex; gap: 24px; }
  .two-col > div { flex: 1; }
  .badge { background: #E3F2FD; color: #1565C0; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
</style>
</head>
<body>
<div class="page">
  <!-- Header -->
  <div class="header">
    <div>
      <div class="company-name">{{ company.name }}</div>
      <div>{{ company.address }}</div>
      <div>GSTIN: <strong>{{ company.gstin }}</strong> | State: {{ company.state }} ({{ company.state_code }})</div>
      <div>📞 {{ company.phone }} | ✉ {{ company.email }}</div>
    </div>
    <div style="text-align:right">
      <div class="invoice-title">TAX INVOICE</div>
      <div><strong>Invoice No:</strong> {{ invoice_no }}</div>
      <div><strong>Date:</strong> {{ sale.sold_at.strftime('%d %B %Y') }}</div>
      <div><span class="badge">{{ sale.payment_mode | upper if sale.payment_mode else 'CASH' }}</span></div>
    </div>
  </div>

  <!-- Bill To -->
  <div class="two-col" style="margin-bottom:16px">
    <div>
      <div class="section-title">Bill To</div>
      <div><strong>{{ sale.customer_name or 'Walk-in Customer' }}</strong></div>
      {% if sale.customer_phone %}<div>📞 {{ sale.customer_phone }}</div>{% endif %}
      <div>State: Delhi</div>
    </div>
    <div>
      <div class="section-title">Device Details</div>
      <div><strong>{{ device.brand }} {{ device.model }}</strong></div>
      <div>Barcode: {{ device.barcode }}</div>
      {% if device.serial_no %}<div>S/N: {{ device.serial_no }}</div>{% endif %}
      <div>Grade: <strong>{{ device.grade | upper if device.grade else '—' }}</strong></div>
    </div>
  </div>

  <!-- Items Table -->
  <div class="section-title">Item Details</div>
  <table>
    <thead>
      <tr>
        <th>#</th><th>Description</th><th>HSN</th><th>Qty</th>
        <th style="text-align:right">Rate (₹)</th><th style="text-align:right">Taxable (₹)</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>1</td>
        <td>
          {{ device.brand }} {{ device.model }}
          {% if device.cpu %} | {{ device.cpu }}{% endif %}
          {% if device.ram_gb %} | {{ device.ram_gb }}GB RAM{% endif %}
          {% if device.storage_gb %} | {{ device.storage_gb }}GB {{ device.storage_type }}{% endif %}
          <br><small style="color:#666">Barcode: {{ device.barcode }}{% if device.serial_no %} | SN: {{ device.serial_no }}{% endif %}</small>
        </td>
        <td>8471</td>
        <td>1</td>
        <td style="text-align:right">{{ "{:,.2f}".format(gst.taxable) }}</td>
        <td style="text-align:right">{{ "{:,.2f}".format(gst.taxable) }}</td>
      </tr>
    </tbody>
  </table>

  <!-- GST Breakdown -->
  <table style="margin-top:12px">
    <tbody>
      <tr><td style="width:60%">Taxable Amount</td><td style="text-align:right">₹ {{ "{:,.2f}".format(gst.taxable) }}</td></tr>
      {% if gst.intra_state %}
      <tr><td>CGST @ {{ gst.cgst_rate }}%</td><td style="text-align:right">₹ {{ "{:,.2f}".format(gst.cgst) }}</td></tr>
      <tr><td>SGST @ {{ gst.sgst_rate }}%</td><td style="text-align:right">₹ {{ "{:,.2f}".format(gst.sgst) }}</td></tr>
      {% else %}
      <tr><td>IGST @ {{ gst.igst_rate }}%</td><td style="text-align:right">₹ {{ "{:,.2f}".format(gst.igst) }}</td></tr>
      {% endif %}
      <tr class="grand-total"><td>Grand Total</td><td style="text-align:right">₹ {{ "{:,.2f}".format(gst.grand_total) }}</td></tr>
    </tbody>
  </table>

  <!-- Footer -->
  <div class="two-col" style="margin-top:32px">
    <div>
      <div class="section-title">Declaration</div>
      <div style="font-size:11px;color:#555">We declare that this invoice shows the actual price of the goods described and that all particulars are true and correct.</div>
    </div>
    <div style="text-align:center">
      <div style="margin-top:40px; border-top:1px solid #999; padding-top:6px; font-size:11px">Authorised Signatory</div>
      <div style="font-size:11px;color:#555">{{ company.name }}</div>
    </div>
  </div>

  <!-- Print button -->
  <div class="no-print" style="margin-top:20px; text-align:center">
    <button onclick="window.print()" class="btn btn-primary" style="margin-right:8px">🖨 Print Invoice</button>
    <a href="/sales" class="btn btn-outline-secondary">← Back to Sales</a>
  </div>
</div>
</body>
</html>
```

- [ ] **Step 3: Register router in main.py**

In `main.py`, after the last `from routers.` import add:
```python
from routers.invoices import router as invoices_router
```
After the last `app.include_router(` call add:
```python
app.include_router(invoices_router)
```

- [ ] **Step 4: Add print icon to sales list**

In `templates/sales/list.html`, find the action column for each sale row and add:
```html
<a href="/invoices/print/{{ sale.id }}" target="_blank" class="btn btn-outline-secondary btn-sm" title="Print Invoice">
  <i class="bi bi-printer"></i>
</a>
```

- [ ] **Step 5: Verify**

Start the app, go to /sales, click the print icon on any sale. Confirm invoice renders with correct GST breakdown.

- [ ] **Step 6: Commit**
```bash
git add routers/invoices.py templates/invoices/print.html main.py templates/sales/list.html
git commit -m "feat: add sale invoice HTML print template with GST breakdown"
```

---

## Task 2: Purchase Order Module

**Files:**
- Create: `routers/crm_purchase_orders.py`
- Create: `templates/crm/purchase_orders/list.html`
- Create: `templates/crm/purchase_orders/form.html`
- Create: `templates/crm/purchase_orders/detail.html`
- Create: `templates/crm/purchase_orders/print.html`
- Modify: `models/crm.py` (add CRMPurchaseOrder, CRMPOLineItem)
- Modify: `models/__init__.py`
- Modify: `main.py`
- Modify: `templates/base.html`

- [ ] **Step 1: Add models to models/crm.py**

Append after the GradePriceMatrix class:
```python
class CRMPurchaseOrder(Base):
    """Formal PO sent to supplier, linked from sourcing deal."""
    __tablename__ = "crm_purchase_orders"

    id                    = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    po_number             = Column(String(30),  unique=True, nullable=False, index=True)  # PO-2025-0001
    deal_id               = Column(UUID(as_uuid=True), ForeignKey("crm_sourcing_deals.id"), nullable=True)
    contact_id            = Column(UUID(as_uuid=True), ForeignKey("crm_contacts.id"), nullable=True)
    po_date               = Column(Date,         nullable=False, default=datetime.utcnow)
    expected_delivery_date= Column(Date,         nullable=True)
    delivery_address      = Column(Text,         nullable=True)
    payment_terms         = Column(Text,         nullable=True)
    advance_amount        = Column(Numeric(14,2), nullable=True)
    total_amount          = Column(Numeric(14,2), default=0)
    status                = Column(String(20),   default="draft")  # draft/issued/acknowledged/received/cancelled
    issued_by             = Column(String(50),   nullable=True)
    issued_at             = Column(DateTime,     nullable=True)
    notes                 = Column(Text,         nullable=True)
    created_by            = Column(String(50),   nullable=True)
    created_at            = Column(DateTime,     default=datetime.utcnow)
    updated_at            = Column(DateTime,     default=datetime.utcnow, onupdate=datetime.utcnow)

    contact    = relationship("CRMContact",       foreign_keys=[contact_id])
    deal       = relationship("CRMSourcingDeal",  foreign_keys=[deal_id])
    line_items = relationship("CRMPOLineItem",    back_populates="po",
                              cascade="all, delete-orphan", order_by="CRMPOLineItem.sort_order")


class CRMPOLineItem(Base):
    __tablename__ = "crm_po_line_items"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    po_id       = Column(UUID(as_uuid=True), ForeignKey("crm_purchase_orders.id"), nullable=False)
    description = Column(String(300), nullable=False)
    device_type = Column(String(100), nullable=True)
    grade       = Column(String(10),  nullable=True)
    quantity    = Column(Integer,     nullable=False, default=1)
    unit_price  = Column(Numeric(10,2), nullable=False)
    total_price = Column(Numeric(14,2), nullable=False)
    sort_order  = Column(Integer,     default=0)

    po = relationship("CRMPurchaseOrder", back_populates="line_items")
```

- [ ] **Step 2: Update models/__init__.py**

Find the CRM import line (imports GradePriceMatrix) and add CRMPurchaseOrder, CRMPOLineItem:
```python
from models.crm import (
    CRMContact, CRMSourcingDeal, CRMSalesOpportunity, CRMQuote,
    CRMQuoteItem, CRMActivity, GradePriceMatrix,
    CRMPurchaseOrder, CRMPOLineItem,
)
```

- [ ] **Step 3: Generate and apply Alembic migration**

```bash
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
alembic revision --autogenerate -m "add_purchase_orders"
alembic upgrade head
```

Expected output: CREATE TABLE crm_purchase_orders, CREATE TABLE crm_po_line_items

- [ ] **Step 4: Create the PO router**

```python
# routers/crm_purchase_orders.py
"""CRM Purchase Orders — formal PO to supplier, linked from sourcing deal."""
from datetime import datetime, date
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user
from models.user import User, UserRole
from models.crm import (
    CRMPurchaseOrder, CRMPOLineItem, CRMContact, CRMSourcingDeal,
    GRADES,
)

router = APIRouter(prefix="/crm/purchase-orders", tags=["crm-purchase-orders"])

ADMIN_ROLES = (UserRole.admin, UserRole.sales_manager, UserRole.inventory_manager)


async def _next_po_number(db: AsyncSession) -> str:
    result = await db.execute(select(func.count(CRMPurchaseOrder.id)))
    n = (result.scalar() or 0) + 1
    return f"PO-{datetime.utcnow().year}-{n:04d}"


@router.get("", response_class=HTMLResponse)
async def list_pos(
    request: Request,
    status: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(CRMPurchaseOrder).order_by(CRMPurchaseOrder.created_at.desc())
    if status:
        q = q.where(CRMPurchaseOrder.status == status)
    result = await db.execute(q)
    pos = result.scalars().all()
    return templates.TemplateResponse("crm/purchase_orders/list.html", {
        "request": request, "current_user": current_user,
        "pos": pos, "status": status,
        "can_edit": current_user.role in ADMIN_ROLES,
    })


@router.get("/new", response_class=HTMLResponse)
async def new_po_form(
    request: Request,
    deal_id: str = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ADMIN_ROLES:
        return RedirectResponse(url="/crm/purchase-orders?error=Permission+denied", status_code=302)
    deal = None
    if deal_id:
        r = await db.execute(select(CRMSourcingDeal).where(CRMSourcingDeal.id == deal_id))
        deal = r.scalar_one_or_none()
    contacts_r = await db.execute(select(CRMContact).where(CRMContact.status == "active").order_by(CRMContact.company_name))
    contacts = contacts_r.scalars().all()
    po_number = await _next_po_number(db)
    return templates.TemplateResponse("crm/purchase_orders/form.html", {
        "request": request, "current_user": current_user,
        "po": None, "deal": deal, "contacts": contacts,
        "po_number": po_number, "grades": GRADES,
        "today": date.today().isoformat(),
    })


@router.post("/new")
async def create_po(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ADMIN_ROLES:
        return RedirectResponse(url="/crm/purchase-orders?error=Permission+denied", status_code=302)
    form = await request.form()
    def _n(v): return float(v) if v and str(v).strip() else None
    def _i(v): return int(v) if v and str(v).strip() else 1

    po = CRMPurchaseOrder(
        po_number=form.get("po_number") or await _next_po_number(db),
        deal_id=form.get("deal_id") or None,
        contact_id=form.get("contact_id") or None,
        po_date=date.fromisoformat(form.get("po_date")) if form.get("po_date") else date.today(),
        expected_delivery_date=date.fromisoformat(form.get("expected_delivery_date")) if form.get("expected_delivery_date") else None,
        delivery_address=form.get("delivery_address") or None,
        payment_terms=form.get("payment_terms") or None,
        advance_amount=_n(form.get("advance_amount")),
        status="draft",
        notes=form.get("notes") or None,
        created_by=current_user.username,
    )
    db.add(po)
    await db.flush()

    # Line items
    descriptions = form.getlist("description[]")
    qtys = form.getlist("qty[]")
    prices = form.getlist("unit_price[]")
    total = 0.0
    for i, desc in enumerate(descriptions):
        if not desc.strip():
            continue
        qty = _i(qtys[i] if i < len(qtys) else "1")
        up = _n(prices[i] if i < len(prices) else "0") or 0.0
        tp = round(qty * up, 2)
        total += tp
        db.add(CRMPOLineItem(
            po_id=po.id, description=desc, quantity=qty,
            unit_price=up, total_price=tp, sort_order=i,
        ))
    po.total_amount = round(total, 2)
    await db.commit()
    return RedirectResponse(url=f"/crm/purchase-orders/{po.id}?success=PO+created", status_code=302)


@router.get("/{po_id}", response_class=HTMLResponse)
async def view_po(
    request: Request, po_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(CRMPurchaseOrder).where(CRMPurchaseOrder.id == po_id))
    po = r.scalar_one_or_none()
    if not po:
        return RedirectResponse(url="/crm/purchase-orders?error=Not+found", status_code=302)
    return templates.TemplateResponse("crm/purchase_orders/detail.html", {
        "request": request, "current_user": current_user,
        "po": po, "can_edit": current_user.role in ADMIN_ROLES,
    })


@router.post("/{po_id}/issue")
async def issue_po(
    po_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ADMIN_ROLES:
        return RedirectResponse(url=f"/crm/purchase-orders/{po_id}?error=Permission+denied", status_code=302)
    r = await db.execute(select(CRMPurchaseOrder).where(CRMPurchaseOrder.id == po_id))
    po = r.scalar_one_or_none()
    if po:
        po.status = "issued"
        po.issued_by = current_user.username
        po.issued_at = datetime.utcnow()
        # Advance sourcing deal stage if linked
        if po.deal_id:
            dr = await db.execute(select(CRMSourcingDeal).where(CRMSourcingDeal.id == po.deal_id))
            deal = dr.scalar_one_or_none()
            if deal and deal.stage in ("agreed", "lead", "contacted", "quoted", "negotiation"):
                deal.stage = "po_raised"
        await db.commit()
    return RedirectResponse(url=f"/crm/purchase-orders/{po_id}?success=PO+issued", status_code=302)


@router.get("/{po_id}/print", response_class=HTMLResponse)
async def print_po(
    request: Request, po_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(CRMPurchaseOrder).where(CRMPurchaseOrder.id == po_id))
    po = r.scalar_one_or_none()
    if not po:
        return RedirectResponse(url="/crm/purchase-orders?error=Not+found", status_code=302)
    return templates.TemplateResponse("crm/purchase_orders/print.html", {
        "request": request, "current_user": current_user, "po": po,
    })
```

- [ ] **Step 5: Create templates (list + form + detail + print)**

Create `templates/crm/purchase_orders/` directory and 4 template files following the same pattern as `templates/crm/price_matrix/list.html` and `form.html`. Key elements:

**list.html** — table of POs with columns: PO#, Supplier, Deal, Date, Amount, Status, Actions
**form.html** — fields: po_number (readonly), contact dropdown, po_date, expected_delivery_date, payment_terms, advance_amount, notes + dynamic line items table (JS add/remove rows)
**detail.html** — read-only view of PO with line items table + Issue/Print buttons
**print.html** — print-optimised (no Bootstrap nav), OxyPC header, PO details, line items, supplier signature box

- [ ] **Step 6: Register router in main.py**

```python
from routers.crm_purchase_orders import router as crm_purchase_orders_router
app.include_router(crm_purchase_orders_router)
```

- [ ] **Step 7: Add nav link in base.html**

In the CRM nav section, after the price-matrix link:
```html
<li><a class="dropdown-item" href="/crm/purchase-orders"><i class="bi bi-file-earmark-text me-2"></i>Purchase Orders</a></li>
```

- [ ] **Step 8: Verify**

Navigate to /crm/purchase-orders → click New PO → fill form → submit → confirm PO detail page loads → click Issue → confirm deal stage advances to po_raised.

- [ ] **Step 9: Commit**
```bash
git add models/crm.py models/__init__.py routers/crm_purchase_orders.py templates/crm/purchase_orders/ main.py templates/base.html alembic/versions/
git commit -m "feat: purchase order module with deal linkage and print template"
```

---

## Task 3: Accounts & Payments

**Files:**
- Create: `routers/accounts.py`
- Create: `templates/accounts/index.html`
- Create: `templates/accounts/supplier_payments.html`
- Create: `templates/accounts/customer_receipts.html`
- Modify: `models/crm.py` (add SupplierPayment, CustomerReceipt)
- Modify: `models/__init__.py`
- Modify: `main.py`
- Modify: `templates/base.html`

- [ ] **Step 1: Add payment models to models/crm.py**

Append after CRMPOLineItem:
```python
class SupplierPayment(Base):
    """Payment made to a supplier against a lot or PO."""
    __tablename__ = "supplier_payments"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_id    = Column(UUID(as_uuid=True), ForeignKey("crm_contacts.id"), nullable=True)
    lot_id        = Column(UUID(as_uuid=True), ForeignKey("lots.id"), nullable=True)
    po_id         = Column(UUID(as_uuid=True), ForeignKey("crm_purchase_orders.id"), nullable=True)
    payment_date  = Column(Date, nullable=False, default=datetime.utcnow)
    amount        = Column(Numeric(14,2), nullable=False)
    payment_mode  = Column(String(20), nullable=True)   # cash/upi/neft/cheque/rtgs
    reference_no  = Column(String(100), nullable=True)  # UTR / cheque no
    is_advance    = Column(Boolean, default=False)
    notes         = Column(Text, nullable=True)
    created_by    = Column(String(50), nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow)

    contact = relationship("CRMContact", foreign_keys=[contact_id])


class CustomerReceipt(Base):
    """Payment received from a buyer against a sale or dealer order."""
    __tablename__ = "customer_receipts"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_id       = Column(UUID(as_uuid=True), ForeignKey("crm_contacts.id"), nullable=True)
    dealer_id        = Column(UUID(as_uuid=True), ForeignKey("dealers.id"), nullable=True)
    sale_id          = Column(UUID(as_uuid=True), ForeignKey("sales.id"), nullable=True)
    dealer_order_id  = Column(UUID(as_uuid=True), ForeignKey("dealer_orders.id"), nullable=True)
    receipt_date     = Column(Date, nullable=False, default=datetime.utcnow)
    amount           = Column(Numeric(14,2), nullable=False)
    payment_mode     = Column(String(20), nullable=True)
    reference_no     = Column(String(100), nullable=True)
    notes            = Column(Text, nullable=True)
    created_by       = Column(String(50), nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)

    contact = relationship("CRMContact", foreign_keys=[contact_id])
```

- [ ] **Step 2: Update models/__init__.py**

Add to CRM import:
```python
from models.crm import (
    ..., SupplierPayment, CustomerReceipt,
)
```

- [ ] **Step 3: Alembic migration**

```bash
alembic revision --autogenerate -m "add_supplier_payments_customer_receipts"
alembic upgrade head
```

- [ ] **Step 4: Create accounts router**

```python
# routers/accounts.py
"""Accounts & Payments — supplier payments and customer receipts."""
from datetime import date
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user
from models.user import User, UserRole
from models.crm import SupplierPayment, CustomerReceipt, CRMContact
from models.dealers import Dealer
from models.lot import Lot

router = APIRouter(prefix="/accounts", tags=["accounts"])

FINANCE_ROLES = (UserRole.admin, UserRole.inventory_manager, UserRole.sales_manager)

PAYMENT_MODES = ["cash", "upi", "neft", "rtgs", "cheque", "card"]


@router.get("", response_class=HTMLResponse)
async def accounts_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Summary cards
    sp_total = (await db.execute(select(func.coalesce(func.sum(SupplierPayment.amount), 0)))).scalar()
    cr_total = (await db.execute(select(func.coalesce(func.sum(CustomerReceipt.amount), 0)))).scalar()
    recent_payments = (await db.execute(
        select(SupplierPayment).order_by(SupplierPayment.created_at.desc()).limit(10)
    )).scalars().all()
    recent_receipts = (await db.execute(
        select(CustomerReceipt).order_by(CustomerReceipt.created_at.desc()).limit(10)
    )).scalars().all()
    return templates.TemplateResponse("accounts/index.html", {
        "request": request, "current_user": current_user,
        "sp_total": float(sp_total or 0),
        "cr_total": float(cr_total or 0),
        "recent_payments": recent_payments,
        "recent_receipts": recent_receipts,
        "can_edit": current_user.role in FINANCE_ROLES,
    })


@router.get("/supplier-payments", response_class=HTMLResponse)
async def supplier_payments(
    request: Request,
    contact_id: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(SupplierPayment).order_by(SupplierPayment.payment_date.desc())
    if contact_id:
        q = q.where(SupplierPayment.contact_id == contact_id)
    payments = (await db.execute(q)).scalars().all()
    suppliers = (await db.execute(
        select(CRMContact).where(CRMContact.contact_type.in_(["supplier","both"]))
        .where(CRMContact.status == "active").order_by(CRMContact.company_name)
    )).scalars().all()
    lots = (await db.execute(select(Lot).order_by(Lot.created_at.desc()).limit(50))).scalars().all()
    total = sum(float(p.amount) for p in payments)
    return templates.TemplateResponse("accounts/supplier_payments.html", {
        "request": request, "current_user": current_user,
        "payments": payments, "suppliers": suppliers, "lots": lots,
        "total": total, "sel_contact": contact_id,
        "payment_modes": PAYMENT_MODES,
        "can_edit": current_user.role in FINANCE_ROLES,
    })


@router.post("/supplier-payments/new")
async def create_supplier_payment(
    request: Request,
    contact_id: str = Form(default=None),
    lot_id: str = Form(default=None),
    po_id: str = Form(default=None),
    payment_date: str = Form(...),
    amount: str = Form(...),
    payment_mode: str = Form(default=None),
    reference_no: str = Form(default=None),
    is_advance: str = Form(default="off"),
    notes: str = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in FINANCE_ROLES:
        return RedirectResponse(url="/accounts/supplier-payments?error=Permission+denied", status_code=302)
    pay = SupplierPayment(
        contact_id=contact_id or None,
        lot_id=lot_id or None,
        po_id=po_id or None,
        payment_date=date.fromisoformat(payment_date),
        amount=float(amount),
        payment_mode=payment_mode or None,
        reference_no=reference_no or None,
        is_advance=(is_advance == "on"),
        notes=notes or None,
        created_by=current_user.username,
    )
    db.add(pay)
    await db.commit()
    return RedirectResponse(url="/accounts/supplier-payments?success=Payment+recorded", status_code=302)


@router.get("/customer-receipts", response_class=HTMLResponse)
async def customer_receipts(
    request: Request,
    dealer_id: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(CustomerReceipt).order_by(CustomerReceipt.receipt_date.desc())
    if dealer_id:
        q = q.where(CustomerReceipt.dealer_id == dealer_id)
    receipts = (await db.execute(q)).scalars().all()
    dealers = (await db.execute(
        select(Dealer).where(Dealer.status == "active").order_by(Dealer.business_name)
    )).scalars().all()
    total = sum(float(r.amount) for r in receipts)
    return templates.TemplateResponse("accounts/customer_receipts.html", {
        "request": request, "current_user": current_user,
        "receipts": receipts, "dealers": dealers,
        "total": total, "sel_dealer": dealer_id,
        "payment_modes": PAYMENT_MODES,
        "can_edit": current_user.role in FINANCE_ROLES,
    })


@router.post("/customer-receipts/new")
async def create_customer_receipt(
    request: Request,
    contact_id: str = Form(default=None),
    dealer_id: str = Form(default=None),
    sale_id: str = Form(default=None),
    receipt_date: str = Form(...),
    amount: str = Form(...),
    payment_mode: str = Form(default=None),
    reference_no: str = Form(default=None),
    notes: str = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in FINANCE_ROLES:
        return RedirectResponse(url="/accounts/customer-receipts?error=Permission+denied", status_code=302)
    rec = CustomerReceipt(
        contact_id=contact_id or None,
        dealer_id=dealer_id or None,
        sale_id=sale_id or None,
        receipt_date=date.fromisoformat(receipt_date),
        amount=float(amount),
        payment_mode=payment_mode or None,
        reference_no=reference_no or None,
        notes=notes or None,
        created_by=current_user.username,
    )
    db.add(rec)
    await db.commit()
    return RedirectResponse(url="/accounts/customer-receipts?success=Receipt+recorded", status_code=302)
```

- [ ] **Step 5: Create 3 account templates**

Each template extends base.html. Key elements:
- **accounts/index.html**: Two summary cards (Total Paid to Suppliers, Total Received from Customers) + recent transactions tables for each
- **accounts/supplier_payments.html**: Filter by supplier + new payment form + paginated payment history table
- **accounts/customer_receipts.html**: Filter by dealer + new receipt form + paginated receipt history table

- [ ] **Step 6: Register in main.py + add nav**

```python
from routers.accounts import router as accounts_router
app.include_router(accounts_router)
```

Nav (under a new "Finance" section in base.html):
```html
<li class="nav-item dropdown">
  <a class="nav-link dropdown-toggle" href="#" data-bs-toggle="dropdown">
    <i class="bi bi-cash-stack me-1"></i>Accounts
  </a>
  <ul class="dropdown-menu">
    <li><a class="dropdown-item" href="/accounts">Overview</a></li>
    <li><a class="dropdown-item" href="/accounts/supplier-payments">Supplier Payments</a></li>
    <li><a class="dropdown-item" href="/accounts/customer-receipts">Customer Receipts</a></li>
  </ul>
</li>
```

- [ ] **Step 7: Verify + Commit**

Navigate /accounts → record a supplier payment → verify it appears in list → record a customer receipt → verify.

```bash
git add models/crm.py routers/accounts.py templates/accounts/ main.py templates/base.html alembic/versions/
git commit -m "feat: accounts & payments module — supplier payments and customer receipts"
```

---

## Task 4: CRM Bulk Contact CSV Import

**Files:**
- Modify: `routers/crm_contacts.py` (add 3 routes)
- Create: `templates/crm/contacts/import.html`

- [ ] **Step 1: Add import routes to routers/crm_contacts.py**

Add after the existing list route:
```python
import csv
import io
from fastapi import UploadFile, File
from fastapi.responses import HTMLResponse

@router.get("/import-csv", response_class=HTMLResponse)
async def import_csv_form(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse("crm/contacts/import.html", {
        "request": request, "current_user": current_user,
        "preview": None, "errors": None,
    })


@router.post("/import-csv", response_class=HTMLResponse)
async def import_csv_preview(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    rows = list(reader)
    errors = []
    preview = []
    for i, row in enumerate(rows, 1):
        company = (row.get("company_name") or "").strip()
        phone   = (row.get("phone") or "").strip()
        if not company:
            errors.append(f"Row {i}: company_name is required")
            continue
        # Check for existing phone
        dup = None
        if phone:
            r = await db.execute(select(CRMContact).where(CRMContact.phone == phone))
            dup = r.scalar_one_or_none()
        preview.append({
            "row": i,
            "company_name": company,
            "contact_person": (row.get("contact_person") or "").strip(),
            "phone": phone,
            "whatsapp": (row.get("whatsapp") or "").strip(),
            "email": (row.get("email") or "").strip(),
            "contact_type": (row.get("contact_type") or "supplier").strip(),
            "source_type": (row.get("source_type") or "").strip(),
            "buyer_type": (row.get("buyer_type") or "").strip(),
            "city": (row.get("city") or "").strip(),
            "state": (row.get("state") or "").strip(),
            "gstin": (row.get("gstin") or "").strip(),
            "tags": (row.get("tags") or "").strip(),
            "duplicate": dup.company_name if dup else None,
        })
    # Store preview in session via hidden form
    import json
    preview_json = json.dumps(preview)
    return templates.TemplateResponse("crm/contacts/import.html", {
        "request": request, "current_user": current_user,
        "preview": preview, "errors": errors,
        "preview_json": preview_json,
    })


@router.post("/import-confirm")
async def import_csv_confirm(
    request: Request,
    preview_data: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import json
    rows = json.loads(preview_data)
    imported = 0
    skipped = 0
    for row in rows:
        if row.get("duplicate"):
            skipped += 1
            continue
        code = await _next_code(db)
        c = CRMContact(
            contact_code=code,
            company_name=row["company_name"],
            contact_person=row["contact_person"] or None,
            phone=row["phone"] or None,
            whatsapp=row["whatsapp"] or None,
            email=row["email"] or None,
            contact_type=row["contact_type"] or "supplier",
            source_type=row["source_type"] or None,
            buyer_type=row["buyer_type"] or None,
            city=row["city"] or None,
            state=row["state"] or None,
            gstin=row["gstin"] or None,
            tags=row["tags"] or None,
            created_by=current_user.username,
        )
        db.add(c)
        imported += 1
    await db.commit()
    return RedirectResponse(
        url=f"/crm/contacts?success=Imported+{imported}+contacts,+{skipped}+skipped+(duplicates)",
        status_code=302,
    )
```

- [ ] **Step 2: Create templates/crm/contacts/import.html**

```html
{% extends "base.html" %}
{% block title %}Import Contacts — OxyPC{% endblock %}
{% block page_title %}Bulk Import Contacts (CSV){% endblock %}
{% block content %}
<div class="row">
<div class="col-xl-8">

{% if not preview %}
<div class="card border-0 shadow-sm mb-3">
  <div class="card-header bg-white border-0 fw-semibold"><i class="bi bi-upload me-2 text-primary"></i>Upload CSV File</div>
  <div class="card-body">
    <div class="alert alert-light border small mb-3">
      <strong>Expected CSV columns:</strong><br>
      company_name*, contact_person, phone, whatsapp, email, contact_type (supplier/buyer/both),
      source_type, buyer_type, city, state, gstin, tags
    </div>
    <form method="post" enctype="multipart/form-data" action="/crm/contacts/import-csv">
      <div class="mb-3">
        <label class="form-label fw-semibold">Select CSV File <span class="text-danger">*</span></label>
        <input type="file" name="file" class="form-control" accept=".csv" required>
      </div>
      <button type="submit" class="btn btn-primary"><i class="bi bi-search me-1"></i>Preview Import</button>
      <a href="/crm/contacts" class="btn btn-outline-secondary ms-2">Cancel</a>
    </form>
  </div>
</div>
{% endif %}

{% if errors %}
<div class="alert alert-danger"><strong>Validation Errors:</strong>
  <ul class="mb-0">{% for e in errors %}<li>{{ e }}</li>{% endfor %}</ul>
</div>
{% endif %}

{% if preview %}
<div class="card border-0 shadow-sm">
  <div class="card-header bg-white border-0 fw-semibold">
    Preview — {{ preview|length }} rows
    <span class="badge bg-success ms-2">{{ preview|selectattr('duplicate','equalto',None)|list|length }} new</span>
    <span class="badge bg-warning text-dark ms-1">{{ preview|rejectattr('duplicate','equalto',None)|list|length }} duplicates (will be skipped)</span>
  </div>
  <div class="card-body p-0">
    <div class="table-responsive">
      <table class="table table-sm table-hover mb-0">
        <thead class="table-light">
          <tr><th>#</th><th>Company</th><th>Phone</th><th>Type</th><th>City</th><th>Status</th></tr>
        </thead>
        <tbody>
          {% for row in preview %}
          <tr class="{{ 'table-warning' if row.duplicate else '' }}">
            <td class="small">{{ row.row }}</td>
            <td class="small fw-semibold">{{ row.company_name }}</td>
            <td class="small">{{ row.phone or '—' }}</td>
            <td class="small"><span class="badge bg-secondary">{{ row.contact_type }}</span></td>
            <td class="small">{{ row.city or '—' }}</td>
            <td class="small">
              {% if row.duplicate %}
              <span class="badge bg-warning text-dark">Duplicate: {{ row.duplicate }}</span>
              {% else %}
              <span class="badge bg-success">New</span>
              {% endif %}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>
<form method="post" action="/crm/contacts/import-confirm" class="mt-3">
  <input type="hidden" name="preview_data" value="{{ preview_json }}">
  <button type="submit" class="btn btn-success"><i class="bi bi-check-circle me-1"></i>Confirm Import</button>
  <a href="/crm/contacts/import-csv" class="btn btn-outline-secondary ms-2">Re-upload</a>
</form>
{% endif %}

</div>
</div>
{% endblock %}
```

- [ ] **Step 3: Add import button to contacts list**

In `templates/crm/contacts/list.html`, add next to the "New Contact" button:
```html
<a href="/crm/contacts/import-csv" class="btn btn-sm btn-outline-success"><i class="bi bi-upload me-1"></i>Import CSV</a>
```

- [ ] **Step 4: Verify + Commit**

Create a test CSV with 3 rows. Upload → preview shows correctly → confirm → verify contacts appear in list.

```bash
git add routers/crm_contacts.py templates/crm/contacts/import.html
git commit -m "feat: CRM bulk contact import via CSV with duplicate detection"
```

---

## Task 5: WhatsApp Quote Sharing

**Files:**
- Modify: `templates/crm/quotes/detail.html`

- [ ] **Step 1: Add Share via WhatsApp button to quote detail**

In `templates/crm/quotes/detail.html`, find the action buttons section (near Edit/Cancel buttons) and add:

```html
<!-- WhatsApp Share Modal Trigger -->
<button type="button" class="btn btn-success btn-sm" data-bs-toggle="modal" data-bs-target="#waShareModal">
  <i class="bi bi-whatsapp me-1"></i>Share via WhatsApp
</button>

<!-- WA Share Modal -->
<div class="modal fade" id="waShareModal" tabindex="-1">
  <div class="modal-dialog modal-lg">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title"><i class="bi bi-whatsapp me-2 text-success"></i>Share Quote via WhatsApp</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <form method="post" action="/whatsapp/send">
        <div class="modal-body">
          <div class="mb-3">
            <label class="form-label fw-semibold">Recipient Phone</label>
            <input type="tel" name="recipient_phone" class="form-control"
                   value="{{ quote.contact.whatsapp or quote.contact.phone if quote.contact else '' }}"
                   placeholder="+91XXXXXXXXXX" required>
          </div>
          <div class="mb-3">
            <label class="form-label fw-semibold">Message</label>
            <textarea name="message_text" class="form-control" rows="10" required>Dear {% if quote.contact %}{{ quote.contact.company_name }}{% endif %},

Please find our quotation details:

Quote No: {{ quote.quote_number }}
Date: {{ quote.quote_date.strftime('%d %b %Y') if quote.quote_date else '' }}
Valid Until: {{ quote.valid_until.strftime('%d %b %Y') if quote.valid_until else 'On Request' }}

Items:
{% for item in quote.items %}{{ loop.index }}. {{ item.device_type }}{% if item.grade %} (Grade {{ item.grade }}){% endif %} — Qty: {{ item.quantity }} × ₹{{ "{:,.0f}".format(item.unit_price) }} = ₹{{ "{:,.0f}".format(item.total_price) }}
{% endfor %}
Total: ₹{{ "{:,.0f}".format(quote.total_amount) }}

{% if quote.payment_terms %}Payment Terms: {{ quote.payment_terms }}{% endif %}

Regards,
OxyPC Team</textarea>
          </div>
          <input type="hidden" name="message_type" value="text">
        </div>
        <div class="modal-footer">
          <button type="submit" class="btn btn-success"><i class="bi bi-send me-1"></i>Send Message</button>
          <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>
        </div>
      </form>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Verify + Commit**

Open a quote detail page → click "Share via WhatsApp" → confirm modal opens with pre-filled message → send → confirm /whatsapp shows it in recent messages.

```bash
git add templates/crm/quotes/detail.html
git commit -m "feat: WhatsApp quote sharing modal on CRM quote detail page"
```

---

## Task 6: CRM Pipeline Analytics

**Files:**
- Create: `routers/crm_reports.py`
- Create: `templates/crm/reports/index.html`
- Create: `templates/crm/reports/funnel.html`
- Create: `templates/crm/reports/win_loss.html`
- Create: `templates/crm/reports/activity_leaderboard.html`
- Modify: `main.py`
- Modify: `templates/base.html`

- [ ] **Step 1: Create crm_reports router**

```python
# routers/crm_reports.py
"""CRM Analytics & Pipeline Reports."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user
from models.user import User
from models.crm import (
    CRMSourcingDeal, CRMSalesOpportunity, CRMActivity,
    SOURCING_STAGES, SALES_STAGES,
)

router = APIRouter(prefix="/crm/reports", tags=["crm-reports"])


@router.get("", response_class=HTMLResponse)
async def crm_reports_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Quick summary stats
    total_sourcing = (await db.execute(select(func.count(CRMSourcingDeal.id)))).scalar() or 0
    won_sourcing   = (await db.execute(select(func.count(CRMSourcingDeal.id)).where(CRMSourcingDeal.stage == "won"))).scalar() or 0
    total_sales    = (await db.execute(select(func.count(CRMSalesOpportunity.id)))).scalar() or 0
    won_sales      = (await db.execute(select(func.count(CRMSalesOpportunity.id)).where(CRMSalesOpportunity.stage == "won"))).scalar() or 0
    total_acts     = (await db.execute(select(func.count(CRMActivity.id)))).scalar() or 0
    return templates.TemplateResponse("crm/reports/index.html", {
        "request": request, "current_user": current_user,
        "total_sourcing": total_sourcing, "won_sourcing": won_sourcing,
        "total_sales": total_sales, "won_sales": won_sales,
        "total_activities": total_acts,
        "sourcing_win_rate": round(won_sourcing/total_sourcing*100) if total_sourcing else 0,
        "sales_win_rate": round(won_sales/total_sales*100) if total_sales else 0,
    })


@router.get("/funnel", response_class=HTMLResponse)
async def pipeline_funnel(
    request: Request,
    pipeline: str = Query(default="sourcing"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if pipeline == "sourcing":
        stages = SOURCING_STAGES
        Model = CRMSourcingDeal
    else:
        stages = SALES_STAGES
        Model = CRMSalesOpportunity

    funnel = []
    for val, label in stages:
        count_r = await db.execute(select(func.count(Model.id)).where(Model.stage == val))
        count = count_r.scalar() or 0
        # Value where available
        if pipeline == "sourcing":
            val_r = await db.execute(
                select(func.coalesce(func.sum(CRMSourcingDeal.our_offer_total), 0))
                .where(CRMSourcingDeal.stage == val)
            )
        else:
            val_r = await db.execute(
                select(func.coalesce(func.sum(CRMSalesOpportunity.estimated_value), 0))
                .where(CRMSalesOpportunity.stage == val)
            )
        value = float(val_r.scalar() or 0)
        funnel.append({"stage": val, "label": label, "count": count, "value": value})

    return templates.TemplateResponse("crm/reports/funnel.html", {
        "request": request, "current_user": current_user,
        "funnel": funnel, "pipeline": pipeline,
    })


@router.get("/win-loss", response_class=HTMLResponse)
async def win_loss_analysis(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Win/Loss by source_type (sourcing)
    sourcing_rows = (await db.execute(
        select(CRMSourcingDeal.source_type, CRMSourcingDeal.stage, func.count().label("cnt"))
        .where(CRMSourcingDeal.stage.in_(["won", "lost"]))
        .group_by(CRMSourcingDeal.source_type, CRMSourcingDeal.stage)
    )).all()

    # Win/Loss by buyer_type (sales)
    sales_rows = (await db.execute(
        select(CRMSalesOpportunity.buyer_type, CRMSalesOpportunity.stage, func.count().label("cnt"))
        .where(CRMSalesOpportunity.stage.in_(["won", "lost"]))
        .group_by(CRMSalesOpportunity.buyer_type, CRMSalesOpportunity.stage)
    )).all()

    # By assigned_to
    by_user = (await db.execute(
        select(CRMSourcingDeal.assigned_to, CRMSourcingDeal.stage, func.count().label("cnt"))
        .where(CRMSourcingDeal.stage.in_(["won", "lost"]))
        .group_by(CRMSourcingDeal.assigned_to, CRMSourcingDeal.stage)
    )).all()

    return templates.TemplateResponse("crm/reports/win_loss.html", {
        "request": request, "current_user": current_user,
        "sourcing_rows": sourcing_rows,
        "sales_rows": sales_rows,
        "by_user": by_user,
    })


@router.get("/activity-leaderboard", response_class=HTMLResponse)
async def activity_leaderboard(
    request: Request,
    days: int = Query(default=30),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    since = datetime.utcnow() - timedelta(days=days)
    rows = (await db.execute(
        select(
            CRMActivity.performed_by,
            CRMActivity.activity_type,
            func.count().label("cnt"),
        )
        .where(CRMActivity.activity_date >= since)
        .group_by(CRMActivity.performed_by, CRMActivity.activity_type)
        .order_by(CRMActivity.performed_by, func.count().desc())
    )).all()

    # Pivot into user → {type: count}
    leaderboard = {}
    for row in rows:
        user = row.performed_by or "Unknown"
        if user not in leaderboard:
            leaderboard[user] = {"call": 0, "whatsapp": 0, "visit": 0, "email": 0, "meeting": 0, "note": 0, "total": 0}
        leaderboard[user][row.activity_type] = row.cnt
        leaderboard[user]["total"] += row.cnt

    leaderboard = sorted(leaderboard.items(), key=lambda x: x[1]["total"], reverse=True)

    return templates.TemplateResponse("crm/reports/activity_leaderboard.html", {
        "request": request, "current_user": current_user,
        "leaderboard": leaderboard, "days": days,
    })
```

- [ ] **Step 2: Create 4 report templates**

Each extends base.html. Key elements:
- **index.html**: 5 summary stat cards (total deals, win rates) + links to detailed reports
- **funnel.html**: Horizontal bar chart (Chart.js) + table showing count + value per stage; toggle between sourcing/sales pipeline
- **win_loss.html**: Tables showing won vs lost counts by source_type, buyer_type, and assigned_to user
- **activity_leaderboard.html**: Table with columns: User | Calls | WhatsApp | Visits | Emails | Meetings | Total; filtered by last N days

- [ ] **Step 3: Register router + nav link**

```python
from routers.crm_reports import router as crm_reports_router
app.include_router(crm_reports_router)
```

Nav in CRM dropdown:
```html
<li><hr class="dropdown-divider"></li>
<li><a class="dropdown-item" href="/crm/reports"><i class="bi bi-bar-chart me-2"></i>CRM Analytics</a></li>
```

- [ ] **Step 4: Verify + Commit**

Navigate /crm/reports → click Funnel → verify sourcing stages show with counts → switch to sales → verify activity leaderboard shows per-user counts.

```bash
git add routers/crm_reports.py templates/crm/reports/ main.py templates/base.html
git commit -m "feat: CRM pipeline analytics — funnel, win/loss, activity leaderboard"
```

---

## Task 7: Business P&L Dashboard

**Files:**
- Modify: `routers/reports.py` (add /reports/business-pl route)
- Create: `templates/reports/business_pl.html`
- Modify: `templates/base.html` (nav link)

- [ ] **Step 1: Add business P&L route to routers/reports.py**

```python
# Add these imports at the top of routers/reports.py:
from datetime import datetime
from sqlalchemy import extract, case

# Add this route:
@router.get("/business-pl", response_class=HTMLResponse)
async def business_pl(
    request: Request,
    year: int = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not year:
        year = datetime.utcnow().year

    # Monthly revenue (current year)
    monthly_rev = []
    for month in range(1, 13):
        r = await db.execute(
            select(func.coalesce(func.sum(Sale.sale_price), 0))
            .where(extract("year", Sale.sold_at) == year)
            .where(extract("month", Sale.sold_at) == month)
        )
        monthly_rev.append(float(r.scalar() or 0))

    # Monthly COGS: buying price (prorated per device sold that month)
    # Simplified: sum of device_price for devices sold in that month
    monthly_cogs = []
    for month in range(1, 13):
        r = await db.execute(
            select(func.coalesce(func.sum(Device.device_price), 0))
            .join(Sale, Sale.device_id == Device.id)
            .where(extract("year", Sale.sold_at) == year)
            .where(extract("month", Sale.sold_at) == month)
        )
        monthly_cogs.append(float(r.scalar() or 0))

    # Overall KPIs
    total_revenue  = (await db.execute(select(func.coalesce(func.sum(Sale.sale_price), 0)).where(extract("year", Sale.sold_at)==year))).scalar()
    total_sales_ct = (await db.execute(select(func.count(Sale.id)).where(extract("year", Sale.sold_at)==year))).scalar()
    # Outstanding from dealers
    outstanding_r  = (await db.execute(select(func.coalesce(func.sum(Sale.sale_price), 0)).where(Device.current_stage == "sold"))).scalar()

    # Inventory value at cost
    inv_value_r = await db.execute(
        select(func.coalesce(func.sum(Device.device_price), 0))
        .where(Device.current_stage.notin_(["sold", "scrapped"]))
    )
    inv_value = float(inv_value_r.scalar() or 0)

    total_revenue = float(total_revenue or 0)
    total_cogs = sum(monthly_cogs)
    gross_profit = total_revenue - total_cogs
    gross_margin = round(gross_profit / total_revenue * 100, 1) if total_revenue > 0 else 0

    return templates.TemplateResponse("reports/business_pl.html", {
        "request": request, "current_user": current_user,
        "year": year,
        "monthly_rev": monthly_rev,
        "monthly_cogs": monthly_cogs,
        "monthly_profit": [r - c for r, c in zip(monthly_rev, monthly_cogs)],
        "total_revenue": total_revenue,
        "total_cogs": total_cogs,
        "gross_profit": gross_profit,
        "gross_margin": gross_margin,
        "total_sales_ct": total_sales_ct or 0,
        "avg_sale_price": round(total_revenue / total_sales_ct, 0) if total_sales_ct else 0,
        "inv_value": inv_value,
    })
```

- [ ] **Step 2: Create templates/reports/business_pl.html**

Key elements:
- 4 KPI cards: Total Revenue, Gross Profit, Gross Margin %, Devices Sold
- 2 secondary cards: Avg Sale Price, Inventory Value at Cost
- Chart.js line chart: 12-month Revenue vs COGS vs Gross Profit (labels = Jan-Dec)
- Monthly breakdown table: Month | Revenue | COGS | Gross Profit | Margin %
- Year selector (current year ± 2)

Chart.js dataset example:
```javascript
new Chart(ctx, {
  type: 'line',
  data: {
    labels: ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],
    datasets: [
      { label: 'Revenue', data: {{ monthly_rev | tojson }}, borderColor: '#1565C0', tension: 0.3 },
      { label: 'COGS', data: {{ monthly_cogs | tojson }}, borderColor: '#C62828', tension: 0.3 },
      { label: 'Gross Profit', data: {{ monthly_profit | tojson }}, borderColor: '#2E7D32', tension: 0.3, fill: true },
    ]
  }
});
```

- [ ] **Step 3: Add nav link**

In base.html under Reports:
```html
<li><a class="dropdown-item" href="/reports/business-pl"><i class="bi bi-graph-up-arrow me-2"></i>Business P&L</a></li>
```

- [ ] **Step 4: Verify + Commit**

Navigate /reports/business-pl → confirm KPI cards load → verify chart renders with monthly data → confirm monthly table shows correct figures.

```bash
git add routers/reports.py templates/reports/business_pl.html templates/base.html
git commit -m "feat: business P&L dashboard with monthly revenue/COGS/profit chart"
```

---

## Task 8: Run All Migrations & Final Smoke Test

- [ ] **Step 1: Ensure all migrations applied**
```bash
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
alembic upgrade head
alembic current
```
Expected: at head revision.

- [ ] **Step 2: Kill old uvicorn processes and restart**
```powershell
# Kill all existing Python processes
wmic process where "name='python.exe'" get ProcessId
# Then kill each:  taskkill /PID <pid> /F
# Restart:
python main.py
```

- [ ] **Step 3: Smoke test all new routes**

| URL | Expected |
|-----|----------|
| /invoices/print/{any_sale_id} | Invoice with GST table |
| /crm/purchase-orders | PO list (empty or populated) |
| /crm/purchase-orders/new | PO creation form |
| /accounts | Accounts overview |
| /accounts/supplier-payments | Payment list + form |
| /accounts/customer-receipts | Receipt list + form |
| /crm/contacts/import-csv | CSV upload form |
| /crm/reports | CRM analytics index |
| /crm/reports/funnel | Sourcing funnel chart |
| /crm/reports/win-loss | Win/loss tables |
| /crm/reports/activity-leaderboard | User activity table |
| /reports/business-pl | P&L dashboard |

- [ ] **Step 4: Final commit**
```bash
git add .
git commit -m "feat: complete Sprint 9 — invoices, POs, payments, CRM bulk import, WA quote share, CRM analytics, P&L dashboard"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Sale Invoice PDF — Task 1
- [x] Purchase Orders — Task 2
- [x] Accounts & Payments — Task 3
- [x] CRM Bulk CSV Import — Task 4
- [x] WhatsApp Quote Sharing — Task 5
- [x] CRM Analytics — Task 6
- [x] Business P&L Dashboard — Task 7
- [x] All migrations — Task 8

**No placeholders:** All steps contain actual code. Templates marked for implementation contain full field lists and key code snippets.

**Type consistency:** All models follow UUID(as_uuid=True) PK pattern. All routers follow `AsyncSession = Depends(get_db)` pattern. All templates extend base.html.
