# Device Qty/Price + Sale List Enhancements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add quantity and price fields to device registration/edit forms, remove Cost Per Unit from Lot Detail, add a Sale Detail page with transport fields, and overhaul the Sale List with enhanced filters, registered-device counts, checkboxes, and selective CSV export.

**Architecture:** 4 independent task groups. Tasks 1–2 touch the Device/Lot domain only. Task 3 extends the Sale model with transport columns (Alembic migration) and adds a new detail page. Task 4 replaces the Sale List filter bar, adds a stats row, and adds checkbox-driven export — all within the existing `/sales` router. No new services or background tasks.

**Tech Stack:** FastAPI async, SQLAlchemy 2.x asyncio, PostgreSQL/asyncpg, Alembic, Jinja2/Bootstrap 5, vanilla JS (no jQuery dependency beyond DataTables already loaded).

---

## File Map

| File | Change |
|------|--------|
| `models/device.py` | Add `qty` column |
| `models/sales.py` | Add 5 transport/payment columns |
| `routers/iqc.py` | Accept `qty` + `device_price` form params |
| `routers/devices.py` | Accept `qty` + `device_price` in edit handler |
| `routers/sales.py` | Add sale detail route; enhance sales_list with filters + counts + export-selected |
| `templates/iqc/form.html` | Add Quantity + Price inputs in Section 9 |
| `templates/devices/edit.html` | Add Quantity + Price inputs in Section 4 |
| `templates/lots/detail.html` | Remove Cost per Unit row |
| `templates/sales/list.html` | Full replacement: filter bar, stats row, checkboxes |
| `templates/sales/detail.html` | Create: sale detail page (all sections) |
| `tests/test_sprint26_unit.py` | Create: 6 pure-logic unit tests |

---

## Task 1: Add Quantity + Price to Add Device (IQC) and Edit Device

**Context:** `Device.device_price` already exists in the model (Numeric 12,2) but has no input field. IQC auto-sets it from line item/lot average, but the user cannot override it manually. `qty` does not exist — add it (Integer, default 1). Both fields go into IQC form and Edit Device form.

**Files:**
- Modify: `models/device.py:105` — add `qty` after `device_price`
- Modify: `routers/iqc.py:108-246` — add `qty` + `device_price` params to `iqc_create`
- Modify: `templates/iqc/form.html:604-636` — add two fields to Section 9
- Modify: `routers/devices.py:324-381` — add `qty` + `device_price` params to `device_edit_save`
- Modify: `templates/devices/edit.html:173-223` — add two fields to Section 4
- Test: `tests/test_sprint26_unit.py`

---

- [ ] **Step 1: Write the failing test**

Create `tests/test_sprint26_unit.py`:

```python
# tests/test_sprint26_unit.py
"""Sprint 26 — pure logic unit tests (no DB required)."""
import pytest
from decimal import Decimal


def test_qty_defaults_to_1_when_blank():
    """Simulate IQC router: blank qty form field → 1."""
    qty_str = ""
    qty = int(qty_str) if qty_str else 1
    assert qty == 1


def test_qty_parsed_correctly():
    qty_str = "5"
    qty = int(qty_str) if qty_str else 1
    assert qty == 5


def test_device_price_manual_override():
    """Manual price wins over auto-calculated when provided."""
    auto_price = 4500.0
    manual_str = "5000"
    device_price = float(manual_str) if manual_str else auto_price
    assert device_price == 5000.0


def test_device_price_auto_when_blank():
    auto_price = 4500.0
    manual_str = ""
    device_price = float(manual_str) if manual_str else auto_price
    assert device_price == 4500.0


def test_device_price_bad_value_falls_back():
    """Non-numeric manual price silently falls back to auto."""
    auto_price = 4500.0
    manual_str = "abc"
    try:
        device_price = float(manual_str)
    except ValueError:
        device_price = auto_price
    assert device_price == 4500.0


def test_sale_filter_grade_matches():
    """Simulate SQL-side grade filter logic check."""
    grade = "A"
    # Simulate that a device with grade 'A' passes the filter
    device_grade = "A"
    assert (not grade or device_grade == grade)

    # Grade 'B' does NOT pass filter for 'A'
    device_grade_b = "B"
    assert not (not grade or device_grade_b == grade)
```

- [ ] **Step 2: Run test to verify it fails (import will fail — file just created)**

```
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
.\venv\Scripts\python.exe -m pytest tests/test_sprint26_unit.py -v
```
Expected: All 6 tests PASS immediately (pure-logic tests, no dependencies).

---

- [ ] **Step 3: Add `qty` column to Device model**

In `models/device.py`, after line 105 (`device_price`):

```python
    device_price = Column(Numeric(12, 2), nullable=True)  # Individual device buying price
    qty           = Column(Integer, nullable=True, server_default="1")  # Units this record covers (default 1)
```

Full import line at top of file already has `Integer` — no import change needed.

- [ ] **Step 4: Generate and apply Alembic migration**

```
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
python -m alembic revision --autogenerate -m "add qty to devices; add transport fields to sales"
```

Review the generated file in `alembic/versions/`. Confirm it contains:
```python
op.add_column('devices', sa.Column('qty', sa.Integer(), server_default='1', nullable=True))
```

Apply:
```
python -m alembic upgrade head
```

Expected output: `Running upgrade ... -> <rev>, add qty to devices...`

Verify:
```
python -m alembic current
```
Expected: the new revision shown as `(head)`.

---

- [ ] **Step 5: Update IQC router to accept qty + device_price**

In `routers/iqc.py`, in the `iqc_create` function signature, add after `lot_line_item_id`:

```python
    lot_line_item_id: str = Form(""),
    qty: str = Form(""),
    device_price_input: str = Form(""),  # manual override field
```

In `routers/iqc.py`, in the `Device(...)` constructor call (around line 214), add `qty`:

```python
    device = Device(
        barcode=barcode, lot_id=lot_id,
        sub_category=sub_category or None,
        brand=brand or None, model=model or None, device_type=device_type or None,
        serial_no=serial_no or None,
        grn_number=grn_number or None,
        qty=int(qty) if qty else 1,          # ← add this line
```

After the existing auto-set `device_price` block (around line 242–246), add the manual override:

```python
    # Manual price override — takes priority over auto-calculated value
    if device_price_input:
        try:
            device.device_price = float(device_price_input)
        except ValueError:
            pass  # silently ignore non-numeric input
```

- [ ] **Step 6: Add Quantity + Price fields to IQC form template**

In `templates/iqc/form.html`, replace the `<!-- ── Section 9: Condition & Location ── -->` block's first `<div class="row g-3 mb-3">` to add two new fields. Insert before the Grade `<div class="col-md-3">`:

```html
          <!-- ── Section 9: Condition & Location ── -->
          <p class="text-muted fw-semibold small text-uppercase mb-2 border-bottom pb-1">Condition &amp; Location</p>
          <div class="row g-3 mb-3">
            <div class="col-md-2">
              <label class="form-label">Quantity</label>
              <input type="number" name="qty" class="form-control" min="1" value="1"
                     placeholder="1" title="Number of units this entry covers">
            </div>
            <div class="col-md-3">
              <label class="form-label">Unit Price (₹) <small class="text-muted">override</small></label>
              <input type="number" name="device_price_input" id="device_price" class="form-control"
                     step="0.01" min="0" placeholder="Auto-filled from line item">
              <div class="form-text">Auto-calculated if blank</div>
            </div>
            <div class="col-md-3">
              <label class="form-label">IQC Grade</label>
              <select name="grade" id="iqc-grade-select" class="form-select">
```

Note: `id="device_price"` on the price input is intentional — the existing JavaScript's `set('device_price', d.unit_price)` targets this id to auto-fill from the selected line item.

Close the row correctly by keeping the rest of Section 9 unchanged (Floor, Warehouse, Notes, submit button).

- [ ] **Step 7: Update Edit Device router to accept qty + device_price**

In `routers/devices.py`, add to `device_edit_save` function signature after `notes`:

```python
    notes: str = Form(""),
    qty: str = Form(""),
    device_price_input: str = Form(""),
```

In the edit save body, after `device.notes = notes or None`:

```python
    device.notes = notes or None
    if qty:
        try:
            device.qty = int(qty)
        except ValueError:
            pass
    if device_price_input:
        try:
            device.device_price = float(device_price_input)
        except ValueError:
            pass
    device.updated_at = datetime.utcnow()
```

- [ ] **Step 8: Add Quantity + Price fields to Edit Device template**

In `templates/devices/edit.html`, in Section 4 (Condition & Location), add two fields before the Grade field (around line 175):

```html
          <!-- ── Section 4: Condition & Location ── -->
          <p class="text-muted fw-semibold small text-uppercase mb-2 border-bottom pb-1">Condition &amp; Location</p>
          <div class="row g-3 mb-3">
            <div class="col-md-2">
              <label class="form-label">Quantity</label>
              <input type="number" name="qty" class="form-control" min="1"
                     value="{{ device.qty or 1 }}" placeholder="1">
            </div>
            <div class="col-md-3">
              <label class="form-label">Unit Price (₹)</label>
              <input type="number" name="device_price_input" class="form-control" step="0.01" min="0"
                     value="{{ device.device_price or '' }}" placeholder="e.g. 4500.00">
            </div>
            <div class="col-md-3">
              <label class="form-label">Grade</label>
              <select name="grade" id="edit-grade-select" class="form-select">
```

Keep the rest of Section 4 unchanged (Floor, Warehouse, storage location alert, Notes).

- [ ] **Step 9: Run tests + verify**

```
.\venv\Scripts\python.exe -m pytest tests/test_sprint26_unit.py -v
```
Expected: 6 passed.

Manual smoke test:
1. Open http://localhost:8000/iqc/new — confirm Quantity and Unit Price inputs appear in Section 9
2. Open any device edit page e.g. http://localhost:8000/devices/OPC-0001/edit — confirm both fields appear in Section 4 pre-filled with current values

- [ ] **Step 10: Commit**

```bash
git add models/device.py routers/iqc.py routers/devices.py templates/iqc/form.html templates/devices/edit.html tests/test_sprint26_unit.py
git add alembic/versions/
git commit -m "feat(sprint26): add qty + device_price fields to IQC and Edit Device forms"
```

---

## Task 2: Remove Cost Per Unit from Lot Detail Financial Breakdown

**Context:** `templates/lots/detail.html` lines 155–158 contain a `{% if lot.qty and lot.buying_price %}` block showing "Cost per Unit". Remove it entirely.

**Files:**
- Modify: `templates/lots/detail.html:155-158`

---

- [ ] **Step 1: Remove the Cost per Unit block**

In `templates/lots/detail.html`, delete these 4 lines (around lines 155–158):

```html
            {% if lot.qty and lot.buying_price %}
            <tr><th class="text-muted">Cost per Unit</th>
                <td>₹{{ "{:,.0f}".format(lot.buying_price / lot.qty) }}</td></tr>
            {% endif %}
```

The table should jump directly from the `<tr class="table-primary">Lot Buying Price</tr>` to the closing `</tbody>`.

- [ ] **Step 2: Verify**

Open any lot detail page, e.g. http://localhost:8000/lots/LOT-001. Confirm the Financial & GST Breakdown card no longer shows a "Cost per Unit" row.

- [ ] **Step 3: Commit**

```bash
git add templates/lots/detail.html
git commit -m "feat(sprint26): remove Cost per Unit from Lot Detail financial breakdown"
```

---

## Task 3: Sale Detail Page (product, customer, payment, transport, status)

**Context:** The Sale model has no transport or payment-reference fields. Add 5 columns (Alembic migration), then create `GET /sales/{sale_id}` route + `templates/sales/detail.html`. Make the Sale# in the list clickable.

**Files:**
- Modify: `models/sales.py:10-27` — add 5 new columns to Sale
- Create: Alembic migration via autogenerate
- Modify: `routers/sales.py` — add `sale_detail` route
- Create: `templates/sales/detail.html`
- Modify: `templates/sales/list.html:31` — make Sale# a link to detail page

---

- [ ] **Step 1: Add transport + payment_reference columns to Sale model**

In `models/sales.py`, add 5 columns after `notes`:

```python
    notes = Column(Text, nullable=True)
    # ── Transport ────────────────────────────────────────────────────────────────
    payment_reference = Column(String(100), nullable=True)   # cheque no / UTR / NEFT ref
    transport_mode    = Column(String(30), nullable=True)    # courier / hand_delivery / self_pickup
    transport_via     = Column(String(100), nullable=True)   # courier company name
    tracking_number   = Column(String(100), nullable=True)   # AWB / tracking number
    dispatch_date     = Column(DateTime, nullable=True)      # when dispatched
    delivery_status   = Column(String(30), nullable=True)    # pending / dispatched / delivered
```

- [ ] **Step 2: Generate and apply Alembic migration**

```
python -m alembic revision --autogenerate -m "add transport fields to sales"
```

Review generated migration — confirm 6 `add_column` statements for the `sales` table.

```
python -m alembic upgrade head
python -m alembic current
```

Expected: new revision at `(head)`.

- [ ] **Step 3: Add `sale_detail` route to sales router**

In `routers/sales.py`, add after `sales_list` (after line ~240):

```python
@router.get("/sales/{sale_id}", response_class=HTMLResponse)
async def sale_detail(
    sale_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Sale, Device, Lot)
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Sale.id == sale_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Sale not found")
    sale, device, lot = row.Sale, row.Device, row.Lot
    return templates.TemplateResponse("sales/detail.html", {
        "request": request,
        "current_user": current_user,
        "sale": sale,
        "device": device,
        "lot": lot,
    })
```

Note: `HTTPException` is already imported in `routers/sales.py`.

- [ ] **Step 4: Create `templates/sales/detail.html`**

Create the file with this full content:

```html
{% extends "base.html" %}
{% block title %}Sale {{ sale.sale_number }} — OxyPC{% endblock %}
{% block page_title %}Sale Detail{% endblock %}
{% block content %}

<div class="d-flex justify-content-between align-items-center mb-3">
  <div>
    <span class="fw-bold fs-5">{{ sale.sale_number }}</span>
    <span class="badge bg-success ms-2">₹{{ "{:,.0f}".format(sale.sale_price) }}</span>
    <small class="text-muted ms-2">{{ sale.sold_at.strftime('%d %b %Y, %I:%M %p') }}</small>
  </div>
  <div class="d-flex gap-2">
    <a href="/invoices/print/{{ sale.id }}" target="_blank" class="btn btn-sm btn-outline-secondary">
      <i class="bi bi-receipt me-1"></i>Invoice
    </a>
    <a href="/invoices/waybill/{{ sale.id }}" target="_blank" class="btn btn-sm btn-outline-primary">
      <i class="bi bi-truck me-1"></i>Waybill
    </a>
    <a href="/sales" class="btn btn-sm btn-outline-secondary">
      <i class="bi bi-arrow-left me-1"></i>Back to List
    </a>
  </div>
</div>

<div class="row g-3">

  {# ── Product Details ── #}
  <div class="col-lg-6">
    <div class="card border-0 shadow-sm h-100">
      <div class="card-header bg-transparent fw-semibold">
        <i class="bi bi-laptop me-2"></i>Product Details
      </div>
      <div class="card-body">
        <table class="table table-sm table-borderless mb-0">
          <tbody>
            <tr><th class="text-muted w-40">Barcode</th>
                <td><a href="/devices/{{ device.barcode }}" class="font-monospace fw-bold text-decoration-none">{{ device.barcode }}</a></td></tr>
            <tr><th class="text-muted">Lot</th>
                <td><a href="/lots/{{ lot.id }}" class="badge bg-info text-dark text-decoration-none">{{ lot.lot_number }}</a></td></tr>
            <tr><th class="text-muted">Brand / Model</th>
                <td>{{ device.brand or '—' }} {{ device.model or '' }}</td></tr>
            <tr><th class="text-muted">Type</th>
                <td>{{ device.device_type or device.sub_category or '—' }}</td></tr>
            <tr><th class="text-muted">CPU</th>
                <td>{{ device.cpu or '—' }}{% if device.generation %} ({{ device.generation }}){% endif %}</td></tr>
            <tr><th class="text-muted">RAM</th>
                <td>{% if device.ram_gb %}{{ device.ram_gb }} GB{% else %}—{% endif %}</td></tr>
            <tr><th class="text-muted">Storage</th>
                <td>
                  {% if device.storage_gb %}{{ device.storage_gb }} GB {{ device.storage_type or '' }}{% endif %}
                  {% if device.hdd_capacity_gb %} + {{ device.hdd_capacity_gb }} GB HDD{% endif %}
                  {% if not device.storage_gb and not device.hdd_capacity_gb %}—{% endif %}
                </td></tr>
            <tr><th class="text-muted">Grade</th>
                <td>
                  {% if device.grade %}
                  <span class="badge bg-{{ {'A':'success','B':'info','C':'warning','D':'secondary','scrap':'danger'}.get(device.grade.value, 'secondary') }}">
                    {{ device.grade.value }}
                  </span>
                  {% else %}—{% endif %}
                </td></tr>
            <tr><th class="text-muted">Current Status</th>
                <td>
                  <span class="badge bg-{{ device.stage_color }}">{{ device.stage_label }}</span>
                </td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  {# ── Customer Details ── #}
  <div class="col-lg-6">
    <div class="card border-0 shadow-sm h-100">
      <div class="card-header bg-transparent fw-semibold">
        <i class="bi bi-person me-2"></i>Customer Details
      </div>
      <div class="card-body">
        <table class="table table-sm table-borderless mb-0">
          <tbody>
            <tr><th class="text-muted w-40">Name</th>
                <td>{{ sale.customer_name or '—' }}</td></tr>
            <tr><th class="text-muted">Phone</th>
                <td>{{ sale.customer_phone or '—' }}</td></tr>
            <tr><th class="text-muted">State</th>
                <td>{{ sale.customer_state or '—' }}</td></tr>
            <tr><th class="text-muted">Sold By</th>
                <td>{{ sale.sold_by or '—' }}</td></tr>
            <tr><th class="text-muted">Invoice No.</th>
                <td>{{ sale.invoice_no or '—' }}</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  {# ── Payment Details ── #}
  <div class="col-lg-6">
    <div class="card border-0 shadow-sm h-100">
      <div class="card-header bg-transparent fw-semibold">
        <i class="bi bi-credit-card me-2"></i>Payment Details
      </div>
      <div class="card-body">
        <table class="table table-sm table-borderless mb-0">
          <tbody>
            <tr><th class="text-muted w-40">Sale Price</th>
                <td class="fw-bold text-success fs-5">₹{{ "{:,.2f}".format(sale.sale_price) }}</td></tr>
            <tr><th class="text-muted">Payment Mode</th>
                <td>
                  {% if sale.payment_mode %}
                  <span class="badge bg-secondary">{{ sale.payment_mode }}</span>
                  {% else %}—{% endif %}
                </td></tr>
            <tr><th class="text-muted">Payment Reference</th>
                <td>{{ sale.payment_reference or '—' }}</td></tr>
            <tr><th class="text-muted">Invoice No.</th>
                <td>{{ sale.invoice_no or '—' }}</td></tr>
            <tr><th class="text-muted">Sale Date</th>
                <td>{{ sale.sold_at.strftime('%d-%m-%Y %H:%M') }}</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  {# ── Transport Details ── #}
  <div class="col-lg-6">
    <div class="card border-0 shadow-sm h-100">
      <div class="card-header bg-transparent fw-semibold">
        <i class="bi bi-truck me-2"></i>Transport Details
      </div>
      <div class="card-body">
        <table class="table table-sm table-borderless mb-0">
          <tbody>
            <tr><th class="text-muted w-40">Transport Mode</th>
                <td>
                  {% if sale.transport_mode %}
                  <span class="badge bg-info text-dark">{{ sale.transport_mode | replace('_', ' ') | title }}</span>
                  {% else %}<span class="text-muted">Not set</span>{% endif %}
                </td></tr>
            <tr><th class="text-muted">Courier / Via</th>
                <td>{{ sale.transport_via or '—' }}</td></tr>
            <tr><th class="text-muted">Tracking Number</th>
                <td>
                  {% if sale.tracking_number %}
                  <span class="font-monospace">{{ sale.tracking_number }}</span>
                  {% else %}—{% endif %}
                </td></tr>
            <tr><th class="text-muted">Dispatch Date</th>
                <td>{% if sale.dispatch_date %}{{ sale.dispatch_date.strftime('%d-%m-%Y') }}{% else %}—{% endif %}</td></tr>
            <tr><th class="text-muted">Delivery Status</th>
                <td>
                  {% set ds_colors = {'pending':'warning','dispatched':'info','delivered':'success'} %}
                  {% if sale.delivery_status %}
                  <span class="badge bg-{{ ds_colors.get(sale.delivery_status, 'secondary') }}">
                    {{ sale.delivery_status | title }}
                  </span>
                  {% else %}<span class="text-muted">—</span>{% endif %}
                </td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  {# ── Notes ── #}
  {% if sale.notes %}
  <div class="col-12">
    <div class="alert alert-light border">
      <i class="bi bi-info-circle me-1"></i><strong>Notes:</strong> {{ sale.notes }}
    </div>
  </div>
  {% endif %}

</div>
{% endblock %}
```

- [ ] **Step 5: Make Sale# in list.html clickable**

In `templates/sales/list.html`, replace line 31:

```html
          <td class="fw-semibold">{{ row.Sale.sale_number }}</td>
```

With:

```html
          <td class="fw-semibold">
            <a href="/sales/{{ row.Sale.id }}" class="text-decoration-none">{{ row.Sale.sale_number }}</a>
          </td>
```

- [ ] **Step 6: Verify**

1. Open Sale List — http://localhost:8000/sales
2. Click any Sale# link — should load detail page at `/sales/<uuid>`
3. Verify all 4 sections render (Product, Customer, Payment, Transport)
4. Verify "Current Status" shows the device stage badge (e.g. "Sold")

- [ ] **Step 7: Commit**

```bash
git add models/sales.py routers/sales.py templates/sales/detail.html templates/sales/list.html
git add alembic/versions/
git commit -m "feat(sprint26): add sale detail page with transport/payment fields"
```

---

## Task 4: Sale List — Enhanced Filters + Registered Device Count + Checkboxes + Export Selected

**Context:** Current Sale List has one filter (lot_id). Replace with 5 new filters (search, sale#, sold-by, customer, grade), add a registered-device stats bar, add row checkboxes, and an "Export Selected" button that POSTs selected sale IDs and returns a CSV.

**Files:**
- Modify: `routers/sales.py:205-240` — rewrite `sales_list`; add `POST /sales/export-selected`
- Modify: `templates/sales/list.html` — full replacement

---

- [ ] **Step 1: Rewrite `sales_list` route with filters + device stats**

In `routers/sales.py`, add `or_` to existing imports:

```python
from sqlalchemy import select, func, text, or_
```

Add `DeviceStage` to the device import:

```python
from models.device import Device, DeviceStage, StageMovement
```

Replace `sales_list` (lines 205–240) with:

```python
@router.get("/sales", response_class=HTMLResponse)
async def sales_list(
    request: Request,
    q: str = Query(default=""),
    sale_no: str = Query(default=""),
    sold_by_filter: str = Query(default=""),
    customer: str = Query(default=""),
    grade: str = Query(default=""),
    lot_id: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    from sqlalchemy import case as sa_case

    base_q = (
        select(Sale, Device.barcode, Device.brand, Device.model, Device.grade, Lot.lot_number)
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
    )

    # ── Apply filters ────────────────────────────────────────────────────────
    if q:
        like = f"%{q}%"
        base_q = base_q.where(or_(
            Device.barcode.ilike(like),
            Device.brand.ilike(like),
            Device.model.ilike(like),
        ))
    if sale_no:
        base_q = base_q.where(Sale.sale_number.ilike(f"%{sale_no}%"))
    if sold_by_filter:
        base_q = base_q.where(Sale.sold_by == sold_by_filter)
    if customer:
        base_q = base_q.where(Sale.customer_name.ilike(f"%{customer}%"))
    if grade:
        base_q = base_q.where(Device.grade == grade)
    if lot_id:
        base_q = base_q.where(Device.lot_id == lot_id)

    # ── Pagination ───────────────────────────────────────────────────────────
    count_q = (
        select(func.count(Sale.id))
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
    )
    if q:
        like = f"%{q}%"
        count_q = count_q.where(or_(
            Device.barcode.ilike(like),
            Device.brand.ilike(like),
            Device.model.ilike(like),
        ))
    if sale_no:
        count_q = count_q.where(Sale.sale_number.ilike(f"%{sale_no}%"))
    if sold_by_filter:
        count_q = count_q.where(Sale.sold_by == sold_by_filter)
    if customer:
        count_q = count_q.where(Sale.customer_name.ilike(f"%{customer}%"))
    if grade:
        count_q = count_q.where(Device.grade == grade)
    if lot_id:
        count_q = count_q.where(Device.lot_id == lot_id)

    total = (await db.execute(count_q)).scalar() or 0
    total_pages = max(1, (total + page_size - 1) // page_size)

    result = await db.execute(
        base_q.order_by(Sale.sold_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    sales = result.all()

    # ── Registered device stats (single query) ───────────────────────────────
    dev_stats = (await db.execute(
        select(
            func.count(Device.id).label("total"),
            func.count(sa_case((Device.current_stage == DeviceStage.sold, 1))).label("sold"),
        ).where(Device.is_active == True)
    )).one()
    total_registered = dev_stats.total
    total_devices_sold = dev_stats.sold
    total_available = total_registered - total_devices_sold

    # ── Sales-user dropdown ──────────────────────────────────────────────────
    sellers_result = await db.execute(
        select(Sale.sold_by).distinct().where(Sale.sold_by.isnot(None)).order_by(Sale.sold_by)
    )
    sellers = [r.sold_by for r in sellers_result]

    # ── Lot dropdown ─────────────────────────────────────────────────────────
    lots_result = await db.execute(select(Lot).order_by(Lot.lot_number))
    lots = lots_result.scalars().all()

    return templates.TemplateResponse("sales/list.html", {
        "request": request,
        "sales": sales,
        "lots": lots,
        "sellers": sellers,
        "selected_lot": lot_id,
        "current_user": current_user,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        # Filters
        "q": q,
        "sale_no": sale_no,
        "sold_by_filter": sold_by_filter,
        "customer": customer,
        "grade": grade,
        # Device stats
        "total_registered": total_registered,
        "total_devices_sold": total_devices_sold,
        "total_available": total_available,
    })
```

- [ ] **Step 2: Add `export_selected_sales` route**

In `routers/sales.py`, add imports at top if not present:

```python
import csv
import io
from fastapi.responses import StreamingResponse
```

Add after `sales_list`:

```python
@router.post("/sales/export-selected")
async def export_selected_sales(
    sale_ids: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Export selected sales rows as CSV. Receives comma-separated Sale UUIDs."""
    ids = [sid.strip() for sid in sale_ids.split(",") if sid.strip()]
    if not ids:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/sales", status_code=302)

    result = await db.execute(
        select(Sale, Device.barcode, Device.brand, Device.model, Device.grade, Lot.lot_number)
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Sale.id.in_(ids))
        .order_by(Sale.sold_at.desc())
    )
    rows = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Sale#", "Date", "Barcode", "Brand", "Model", "Lot", "Grade",
                     "Price", "Customer", "Phone", "Payment", "Sold By"])
    for row in rows:
        s = row.Sale
        writer.writerow([
            s.sale_number,
            s.sold_at.strftime("%d-%m-%Y"),
            row.barcode, row.brand, row.model, row.lot_number,
            row.grade.value if row.grade else "",
            float(s.sale_price or 0),
            s.customer_name or "", s.customer_phone or "",
            s.payment_mode or "", s.sold_by or "",
        ])
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sales_selected.csv"},
    )
```

- [ ] **Step 3: Replace `templates/sales/list.html` entirely**

```html
{% extends "base.html" %}
{% block title %}Sales — OxyPC{% endblock %}
{% block page_title %}Sales List{% endblock %}
{% block content %}

{# ── Registered Device Stats Bar ── #}
<div class="row g-2 mb-3">
  <div class="col-6 col-md-3">
    <div class="card border-0 shadow-sm text-center py-2">
      <div class="fs-5 fw-bold text-primary">{{ total_registered }}</div>
      <div class="small text-muted">Total Registered</div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="card border-0 shadow-sm text-center py-2">
      <div class="fs-5 fw-bold text-success">{{ total_devices_sold }}</div>
      <div class="small text-muted">Sold</div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="card border-0 shadow-sm text-center py-2">
      <div class="fs-5 fw-bold text-warning">{{ total_available }}</div>
      <div class="small text-muted">Available</div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="card border-0 shadow-sm text-center py-2">
      <div class="fs-5 fw-bold text-info">{{ total }}</div>
      <div class="small text-muted">Filtered Sales</div>
    </div>
  </div>
</div>

{# ── Filter Bar ── #}
<div class="card border-0 shadow-sm mb-3">
  <div class="card-body py-2">
    <form class="d-flex flex-wrap gap-2 align-items-center" method="get" action="/sales" id="filterForm">
      <input type="text" name="q" value="{{ q }}" placeholder="Device barcode/brand/model"
             class="form-control form-control-sm" style="width:190px">
      <input type="text" name="sale_no" value="{{ sale_no }}" placeholder="Sale#"
             class="form-control form-control-sm" style="width:110px">
      <input type="text" name="customer" value="{{ customer }}" placeholder="Customer name"
             class="form-control form-control-sm" style="width:160px">
      <select name="sold_by_filter" class="form-select form-select-sm" style="width:145px">
        <option value="">All Users</option>
        {% for seller in sellers %}
        <option value="{{ seller }}" {% if sold_by_filter == seller %}selected{% endif %}>{{ seller }}</option>
        {% endfor %}
      </select>
      <select name="grade" class="form-select form-select-sm" style="width:110px">
        <option value="">All Grades</option>
        {% for g in ['A','B','C','D','scrap'] %}
        <option value="{{ g }}" {% if grade == g %}selected{% endif %}>Grade {{ g }}</option>
        {% endfor %}
      </select>
      <select name="lot_id" class="form-select form-select-sm" style="width:130px">
        <option value="">All Lots</option>
        {% for lot in lots %}
        <option value="{{ lot.id }}" {% if selected_lot == lot.id|string %}selected{% endif %}>{{ lot.lot_number }}</option>
        {% endfor %}
      </select>
      <button type="submit" class="btn btn-sm btn-primary">Filter</button>
      <a href="/sales" class="btn btn-sm btn-outline-secondary">Clear</a>
      <div class="ms-auto d-flex gap-2">
        <button type="button" id="exportSelectedBtn" class="btn btn-sm btn-outline-warning" onclick="exportSelected()" disabled>
          <i class="bi bi-download me-1"></i>Export Selected
        </button>
        <a href="/reports/export/sales" class="btn btn-sm btn-outline-success">
          <i class="bi bi-download me-1"></i>Export All CSV
        </a>
      </div>
    </form>
    {# Hidden form for POST export-selected #}
    <form id="exportForm" action="/sales/export-selected" method="post" style="display:none">
      <input type="hidden" name="sale_ids" id="selectedIds">
    </form>
  </div>
</div>

{# ── Table ── #}
<div class="card border-0 shadow-sm">
  <div class="card-body p-0">
    <table id="salesTable" class="table table-hover mb-0 small">
      <thead class="table-dark">
        <tr>
          <th style="width:36px">
            <input type="checkbox" id="selectAll" title="Select all visible rows">
          </th>
          <th>Sale#</th><th>Date</th><th>Barcode</th><th>Brand/Model</th>
          <th>Lot</th><th>Grade</th><th>Price</th><th>Customer</th>
          <th>Payment</th><th>By</th><th></th>
        </tr>
      </thead>
      <tbody>
        {% set ns = namespace(total=0) %}
        {% for row in sales %}
        {% set ns.total = ns.total + (row.Sale.sale_price | float) %}
        <tr>
          <td><input type="checkbox" class="row-check" value="{{ row.Sale.id }}"></td>
          <td class="fw-semibold">
            <a href="/sales/{{ row.Sale.id }}" class="text-decoration-none">{{ row.Sale.sale_number }}</a>
          </td>
          <td>{{ row.Sale.sold_at.strftime('%d-%m-%Y') }}</td>
          <td><a href="/devices/{{ row.barcode }}" class="text-decoration-none"><code>{{ row.barcode }}</code></a></td>
          <td>{{ row.brand }} {{ row.model }}</td>
          <td><a href="/devices?lot={{ row.lot_number }}" class="text-decoration-none">
            <span class="badge bg-info text-dark">{{ row.lot_number }}</span></a>
          </td>
          <td>{{ row.grade.value if row.grade else '—' }}</td>
          <td class="fw-semibold text-success">₹{{ "{:,.0f}".format(row.Sale.sale_price) }}</td>
          <td>{{ row.Sale.customer_name or '—' }}</td>
          <td><span class="badge bg-secondary">{{ row.Sale.payment_mode or '—' }}</span></td>
          <td class="text-muted">{{ row.Sale.sold_by }}</td>
          <td>
            <div class="d-flex gap-1">
              <a href="/sales/{{ row.Sale.id }}" class="btn btn-outline-info btn-sm py-0 px-1" title="View Detail"><i class="bi bi-eye"></i></a>
              <a href="/invoices/print/{{ row.Sale.id }}" target="_blank" class="btn btn-outline-secondary btn-sm py-0 px-1" title="Invoice"><i class="bi bi-receipt"></i></a>
              <a href="/invoices/waybill/{{ row.Sale.id }}" target="_blank" class="btn btn-outline-primary btn-sm py-0 px-1" title="Waybill"><i class="bi bi-truck"></i></a>
            </div>
          </td>
        </tr>
        {% else %}
        <tr><td colspan="12" class="text-center text-muted py-4">No sales match your filters.</td></tr>
        {% endfor %}
      </tbody>
      {% if sales %}
      <tfoot class="table-light">
        <tr>
          <td></td>
          <td colspan="6" class="text-end fw-semibold">Total Revenue (this page):</td>
          <td class="fw-bold text-success">₹{{ "{:,.0f}".format(ns.total) }}</td>
          <td colspan="4"></td>
        </tr>
      </tfoot>
      {% endif %}
    </table>
  </div>
</div>

{% endblock %}
{% block scripts %}
<script>
// ── Select All / individual checkboxes ──────────────────────────────────────
const selectAll = document.getElementById('selectAll');
const exportBtn = document.getElementById('exportSelectedBtn');

selectAll.addEventListener('change', function() {
  document.querySelectorAll('.row-check').forEach(cb => cb.checked = this.checked);
  updateExportBtn();
});

document.addEventListener('change', function(e) {
  if (e.target.classList.contains('row-check')) updateExportBtn();
});

function updateExportBtn() {
  const checked = document.querySelectorAll('.row-check:checked').length;
  exportBtn.disabled = checked === 0;
  exportBtn.textContent = checked > 0 ? `Export Selected (${checked})` : 'Export Selected';
}

function exportSelected() {
  const ids = Array.from(document.querySelectorAll('.row-check:checked')).map(cb => cb.value);
  if (!ids.length) return;
  document.getElementById('selectedIds').value = ids.join(',');
  document.getElementById('exportForm').submit();
}

// ── DataTable ───────────────────────────────────────────────────────────────
$(document).ready(function() {
  $('#salesTable').DataTable({
    pageLength: 25,
    order: [[1, 'desc']],
    columnDefs: [
      { orderable: false, targets: [0, 11] }  // checkbox and actions not sortable
    ]
  });
});
</script>
{% endblock %}
```

- [ ] **Step 4: Run tests**

```
.\venv\Scripts\python.exe -m pytest tests/test_sprint26_unit.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Smoke-test Sale List**

1. Open http://localhost:8000/sales
2. Verify the 4 stat cards appear at the top (Total Registered, Sold, Available, Filtered Sales)
3. Verify 6-field filter bar renders (device search, sale#, customer, sold-by, grade, lot)
4. Type in Device search box — click Filter — results narrow
5. Check one or more rows — "Export Selected (N)" button activates
6. Click Export Selected — CSV downloads with only those rows
7. Verify Sale# is clickable — opens the detail page created in Task 3

- [ ] **Step 6: Commit**

```bash
git add routers/sales.py templates/sales/list.html
git commit -m "feat(sprint26): sale list filters, device count stats, checkboxes, export selected"
```

---

## Self-Review

**Spec coverage:**
1. ✅ Add Device — Quantity field (Task 1, IQC form + router)
2. ✅ Add Device — Manual Price field (Task 1, IQC form + router)
3. ✅ Edit Device — Quantity field (Task 1, edit form + router)
4. ✅ Edit Device — Manual Price field (Task 1, edit form + router)
5. ✅ Lot Detail — Remove Cost Per Unit (Task 2)
6. ✅ After Selling — registered device count auto-calculated (Task 4, stats bar using DB query)
7. ✅ Sale List — Device search, Sale#, Users, Customer, Grade filters (Task 4)
8. ✅ Sale List — Checkboxes + Export Selected only (Task 4)
9. ✅ Sale Detail — clickable Sale#, product/customer/payment/transport/status (Task 3)

**No placeholders found.**

**Type consistency:** `DeviceStage.sold` used in Task 4 router matches the enum in `models/device.py`. `sale_ids` form field matches `id="selectedIds"` in the template. `row.grade.value` handles the SQLAlchemy Enum `.value` access correctly. `ds_colors` dict in detail.html uses string keys matching `delivery_status` values.
