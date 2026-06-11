# Tasks

## **Backlog — Lot Management**


## **Backlog — CRM**

- [x] **CRM sourcing: linked lot status card** - shows PO Qty / Registered / Sold stat boxes + registration & sold progress bars
- [x] **CRM contacts: export to CSV** - GET /crm/contacts/export-csv (admin only), respects all active filters, Export button on list page

## **Backlog — Device / QC / Sales**

- [x] **Add Device page: lot search dropdown** - Tom Select 2.3 autocomplete on IQC form + Device edit; barcode-lookup autofill updated to use Tom Select API
- [x] **Edit Device page: stage history panel** - collapsible card showing from/to stage, moved_by, timestamps, duration, notes
- [x] **Sale List page: filter by lot number** - already implemented: lot_id dropdown in filter bar, backend Query param + where clause, selected_lot state preserved
- [x] **Sale List page: buying price column** - Cost/Unit (buying_price÷qty) + Margin (sale_price−cost) columns added

## **Backlog — Telecalling / CRM Dashboard**

- [x] **Telecalling dashboard: agent performance table** - /telecalling/agent-performance — per-agent stats (total, interested, callback, not_interested, no_answer, order_placed, conversion%) combining DealerCall + TelecallingRecord
- [x] **Dealer management: bulk import CSV** - already implemented: GET/POST /dealers/bulk-upload + template dealers/bulk_upload.html + /dealers/bulk-upload-template CSV download

## **Backlog — Infrastructure**

- [x] **CSRF: audit all POST forms** - all 75+ POST forms protected via base.html JS inject; login.html now gets a pre-issued cookie on GET + verify_csrf on POST
- [x] **Audit log viewer** - `/admin/audit-log` with username/action/table filters + pagination
- [x] **DB backup cron** - nightly pg_dump via Windows Task Scheduler at 23:00; `scripts/backup_db.py` finds pg_dump in PostgreSQL install dirs; 30-day retention; `/admin/backup-status` + `/admin/backup-now` API routes

## **Done**

- [x] **CRM contacts: agent filter (admin only)** - filter contacts by who added them; shows full name
- [x] **CRM contacts: remove status filter** - cleaned up filter bar
- [x] **Lot list: GRN modal CSRF token** - was missing, causing silent submission failures
- [x] **Lot list: Created date column** - added between Supplier and Purchase Date
- [x] **Lot list: trash button reliability** - switched to inline form pattern (DataTables-safe)
- [x] **Lot list: is_trashed NULL handling** - isnot(True) instead of == False
- [x] **Lot number: collision-safe generation** - MAX instead of COUNT to skip gaps from deleted lots
- [x] **Lot delete: hard delete route** - POST /lots/{id}/delete with CRM nullification + audit log
- [x] **Lot delete: cascade device deletion** - deletes all 15 child tables in FK order before devices + lot
- [x] **Lot detail page: device sub-records count** - IQC ✓, Repairs count, QC count, Sold/Available status per device row
- [x] **Lot list: export respects filters** - Export button passes q/date_from/date_to; button label changes to "Export Filtered CSV"; full 15-column output
- [x] **Dealer management: admin filter + last-call column + followup filter + call-log pills**
- [x] **Telecalling dashboard: DealerCall source + clickable names + full filter bar**
