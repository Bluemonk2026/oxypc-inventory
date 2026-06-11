# OxyPC Inventory Management System

A multi-user inventory management system for laptop/desktop refurbishment businesses.

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
