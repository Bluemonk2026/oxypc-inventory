# Memory — OxyPC Inventory

## Project
FastAPI + PostgreSQL web ERP for OxyPC Computers (laptop refurbishment).  
Server: `C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory\`  
Runs at `192.168.1.100:8000` on LAN. 30+ concurrent users.

## People
| Who | Role |
|-----|------|
| **Pankaj** | Director / owner. CEO Deshwal. Gives feature requests. |

## Key Terms
| Term | Meaning |
|------|---------|
| **Lot** | Purchased batch of devices from a supplier (e.g., LOT-042) |
| **GRN** | Goods Receipt Note — physical receipt verification of a lot |
| **IQC** | Incoming Quality Check — first hardware inspection |
| **QC** | Quality Check — post-repair final check |
| **Stage** | Device workflow state: IQC → L1/L2/L3 repair → QC → Ready → Sold |
| **OxyQC** | Standalone PyInstaller EXE for IQC inspectors (offline-capable) |
| **is_trashed** | Soft-delete flag on Lot (boolean, nullable — use `isnot(True)` not `== False`) |
| **RBAC** | Role-based access: admin, inventory_manager, sales, iqc_inspector, l1/l2/l3_engineer, qc_inspector |
| **CRM** | contacts + sourcing deals + sales opps + telecalling / dealer management modules |

## Architecture
- **Router files:** `routers/` — one file per feature area (stock.py, crm_contacts.py, sales.py…)
- **Models:** `models/` — SQLAlchemy ORM models
- **Templates:** `templates/` — Jinja2 HTML (Bootstrap 5 + DataTables + Bootstrap Icons)
- **Services:** `services/audit_engine.py`, `services/event_bus.py`
- **Auth:** `auth/dependencies.py` — `get_current_user`, `require_roles`, `verify_csrf`
- **Key pattern:** `await db.execute(select(...))` → `.scalar_one_or_none()` or `.scalars().all()`

## Current Sprint Focus
Lot Management cleanup: cascade delete just shipped. Next: verify in app, then move to device/sale page enhancements.

## Critical Rules (from global CLAUDE.md)
- Never delete files without explicit per-file user permission
- No schema changes without dbdiagram.io approval
- `is_trashed.isnot(True)` — always, not `== False`
- All outputs to `C:\Users\Pankaj.sehgal\Claude\output\`
- Audit log before `db.delete()` — record is gone after commit
