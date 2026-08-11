# OxyPC Inventory Management System

A multi-user inventory management system for laptop/desktop refurbishment businesses.

## Reliance Asset FieldOps — `/fieldops`

A standalone, offline-first field app for the Reliance demo-unit recovery project,
served at **https://app.oxypc.com/fieldops** and linked from the sidebar.

Serial capture → Rapid QC → Reliance approval → commercial pricing → packing →
pickup/courier AWB → warehouse GRN → closure, with an executive dashboard, MIS
exports, SLA escalation and an immutable audit log.

- Loaded with the real inventory master: **3,957 units across 622 locations**,
  reconciled to the source costing sheet (₹26,77,637 total charges).
- Installs to a phone as a PWA and keeps working with no network; state lives in
  the browser, so it touches no OxyPC data or tables.
- Files in `fieldops_app/` (deliberately not under `static/`, which is mounted
  publicly), served by `routers/fieldops.py` **behind the OxyPC login** — the
  Reliance inventory it carries is not anonymously readable.
- 147 automated checks; see `fieldops_app/README.md` for how to run them.

## Quick Start

### Step 1 — Install PostgreSQL (one time)
Download from https://www.postgresql.org/download/windows/ and install.

Then create the database:
```
psql -U postgres
CREATE USER oxypc WITH PASSWORD 'oxypc123';
CREATE DATABASE oxypc_db OWNER oxypc;
\q
```

### Step 2 — Install Python dependencies
```
cd oxypc-inventory
pip install -r requirements.txt
```

### Step 3 — Run setup (one time)
```
python setup_db.py
```
Follow prompts to create admin user. Default password: `oxypc@admin123`

### Step 4 — Start the server
```
python main.py
```
Browser opens automatically at http://localhost:8000

### Step 5 — Access from other devices on LAN
Find server IP: run `ipconfig` on server laptop
Other devices open: `http://<server-ip>:8000`

---

## Roles

| Role | Can Access |
|------|-----------|
| Admin | Everything + user management |
| Inventory Manager | Lots, Stock In, IQC, Stage Movement |
| IQC Inspector | IQC entry, Stage movement |
| L1 Engineer | L1 Repair |
| L2 Engineer | L2 Repair |
| L3 Engineer | L3 Repair |
| QC Inspector | QC Check, Dashboard |
| Sales | Ready to Sale, Sales, Returns |
| Spare Parts Manager | Spare Parts, RAM Tracking |

## Workflow

```
IQC → Stock In → L1 → L2 → L3 → QC → Ready to Sale → Sold
```

## Barcode Scanner
Plug USB barcode scanner into any client device. Click a barcode field and scan — it auto-submits.

## Build EXE
```
pip install pyinstaller
pyinstaller build.spec
```
Output: `dist/OxyPC_Inventory.exe`

## Config
Edit `config.ini` next to the EXE to change DB URL or port.
