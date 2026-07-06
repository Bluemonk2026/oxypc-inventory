---
name: server-side-financial-snapshot
description: Use when building any feature that generates a document with computed totals from line items (quotations, invoices, certificates) and/or reuses another table's data at a point in time (dealer details, company settings). Enforces server-side-only calculation and immutable snapshot-on-create, per the project's Database-First Engineering Standards.
---

# Server-Side Financial Snapshot Pattern (OxyPC Inventory)

## Two rules this pattern always enforces

1. **All calculations happen server-side, from raw inputs — never trust a
   client-submitted total.** The client submits `quantity`/`unit_price` per
   line item; the server recomputes `total_price` per line and the aggregate
   `total_quantity`/`total_price` using `Decimal` arithmetic. Any
   client-submitted total field is ignored, not validated-then-trusted.

2. **Referenced records are snapshotted as columns at creation time, not
   just FK'd.** If the source record (Dealer, Company Settings) is edited
   later, historical documents must not silently change. Copy the fields you
   need onto the new row instead of relying on a live join.

## Reference implementation: `DealerQuotation`

- `models/dealer_quotation.py` — `DealerQuotation` has `dealer_id` (FK, for
  traceability/queries) *plus* copied columns `customer_name`, `dealer_phone`,
  `dealer_email`, `dealer_address`, `dealer_gstin`, `company_name`,
  `company_address`, `company_gstin`, `company_phone`, `company_email` — all
  snapshotted at creation. Line items live in a child table
  `DealerQuotationItem` (`cascade="all, delete-orphan"`).

- `routers/dealer_quotations.py`'s `create_dealer_quotation`:
  ```python
  def _to_decimal(value, default="0"):
      try: return Decimal(str(value))
      except Exception: return Decimal(default)

  # recompute from raw form arrays — never read a "total" field from the client
  total_quantity = sum(_to_int(q) for q in quantity)
  total_price = sum(_to_int(q) * _to_decimal(p) for q, p in zip(quantity, unit_price))
  ```

- Quote numbers are generated server-side (`f"QTN-{seq:04d}"`), never
  accepted from the client.

## Reusable settings via generic key/value table

Don't create a new one-row settings table per feature. Reuse the existing
generic `AppSetting(key, value, description, updated_by, updated_at)` table
(same convention as `page_title_*`/`sidebar_label_*`). See
`routers/company_settings.py`'s `get_company_settings(db)` for the read-side
helper pattern (`select(...).where(AppSetting.key.in_(KEYS))` → dict with
defaults for missing keys).

## Checklist for any new "generate a priced document" feature

- [ ] Line-item quantities/prices arrive as parallel form arrays; recompute
      per-line and aggregate totals server-side with `Decimal`, never int/float.
- [ ] Snapshot every field that must stay historically accurate (customer
      details, company details) as columns on the new row, not just an FK.
- [ ] Any sequence/document number is generated server-side.
- [ ] Status transitions (`shared` → `confirmed`) are their own endpoint,
      audited via the existing audit engine, never a raw field PATCH.
- [ ] Run `python db_validator.py` after adding tables/columns — must report
      "Schema is in sync with ORM models -- no issues found" before continuing.
