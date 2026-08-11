# Reliance Asset FieldOps

Mobile-first field execution and control app for demo-unit asset QC, commercial
deduction, packing, pickup/courier movement, warehouse receipt and 45-day project
governance.

Built to **BRD v3.0 (Source Aligned)** and loaded with the **real inventory master**
from `Inventory Details_LP TAT & Costing.xlsx` — 3,957 units across 622 locations.

One URL serves phone, tablet and desktop. It installs to the home screen as a PWA
and keeps working with no network.

---

## Run it

**Hosted** — <https://app.oxypc.com/fieldops>. It is a standalone application: its
own sign-in, its own accounts, its own database. It does not appear in the OxyPC
menu, an OxyPC login grants no access to it, and it reads and writes none of
OxyPC's data. The two share a domain and a deployment, nothing else.

Anyone can reach the sign-in page; nothing past it is reachable without an account
that an administrator created — including the inventory master itself.

**First run — no server access needed.** Sign in to OxyPC as an administrator, then
open <https://app.oxypc.com/fieldops/setup>. It creates the FieldOps administrator
and shows a one-time password once. Sign in with it and you are asked immediately to
choose your own; the issued one stops working and the setup page closes permanently.
That OxyPC check is the only moment FieldOps ever looks at an OxyPC session — it is
simply the one proof of ownership available before any FieldOps account exists.

**Optional configuration**, if you do have access to the server's environment:

| Variable | Purpose |
|---|---|
| `FIELDOPS_DATABASE_URL` | give it a database of its own. Without it the app uses OxyPC's Postgres connection but keeps its own tables and metadata — still no foreign keys either way, still separately dumpable. Setting it later moves the app with no code change |
| `FIELDOPS_ADMIN_PASSWORD` | creates the administrator at startup instead of via the setup page. One-time: it must be changed at first sign-in, and is never read again once a password is set |
| `FIELDOPS_ADMIN_USERNAME` | optional, defaults to `admin` |
| `FIELDOPS_DEMO_PASSWORD` | optional. Gives the ten seeded role accounts a working password; without it they exist with the right roles but cannot sign in until an administrator issues one |

**Standalone / offline** — the folder also runs from any static file server for a
demo or to run the test suites. With no API reachable it says "this device only":
no shared store, no server accounts, nothing lost.

```bash
python3 -m http.server 8777
```

Installing on a device: Android/Chrome → menu → *Add to Home screen*;
iPhone/Safari → Share → *Add to Home Screen*; desktop → install icon in the
address bar. The app then opens full-screen and runs offline.

---

## Accounts, roles and rights

There is no role picker and no shared PIN. Every person has an account created by
an administrator, with a role, a region, assigned sites and — optionally — module
grants or revocations on top of the role default.

| Role | Sees |
|---|---|
| Field QC Engineer | My Day, their assigned sites, serial capture, QC, packing |
| Regional Coordinator | Sites in their region, approvals queue (read-only), packing |
| PMO / Project Manager | Everything except administration |
| Reliance Site SPOC | Their own site, read-only QC |
| Reliance QC Approver | The approval queue — the only role that may accept, dispute or re-QC |
| Commercial Approver | Pricing and the commercial accept/hold decision |
| Packing / Pickup Partner | Released assets, packing, pickup handover |
| Courier Desk | Courier jobs and AWB tracking |
| Warehouse User | Inbound movements, GRN, discrepancies |
| System Admin | Everything, plus accounts, masters, import/export and deletion |

**The administrator** creates and edits users, assigns roles and sites, grants or
revokes individual modules, issues and resets passwords, deactivates accounts, and
is the only role that can delete data or bulk import/export.

Passwords are bcrypt hashes — they can be set, never read. A password an admin
issues must be changed by the user at their next sign-in. Eight failed attempts
lock an account for fifteen minutes, and the sign-in endpoint is rate-limited per
IP address.

**Rights are enforced on the server, not in the browser.** A device can post
anything it likes; the sync endpoint checks every change against the account's role
before accepting it. An engineer cannot approve their own QC, only the commercial
approver can move a commercial status, only an administrator can delete — and QC
evidence and the audit log cannot be deleted by anyone, including the administrator.

---

## The end-to-end flow

Site job → asset lookup → Rapid QC → Reliance approval → pricing →
packing → pickup or courier → warehouse GRN → closure.

1. **My Day / Sites** — assigned locations, readiness, recommended FE allocation,
   planned visit date, serial-mapping progress, source TAT and costing.
2. **Serial capture — always the first step.** Starting QC at a site asks one
   question: *what is the serial number on this unit?* Nothing else is presented
   until it is answered. If the serial is already known, the app opens that unit
   directly. If it is new, the engineer picks the model from the SKUs still
   unmapped at that site, and the serial is bound to that inventory line. A serial
   already used elsewhere is rejected on the spot (BR-06), and the QC screen cannot
   be reached — by link or by URL — while a unit has no serial.
3. **Scan / Find** — camera QR/barcode scan (where the browser supports it) with
   fuzzy serial / asset-tag search as the fallback.
4. **Rapid QC** — one screen of large tap cards with a live timer against the
   12–15 min/laptop benchmark, conditional suppression on the No-Power path,
   photo capture, and auto-derived defect codes with the resulting revised price.
   The captured serial is shown locked; correcting it is a separate, audited action.
5. **Approvals** — the Reliance QC Approver accepts, disputes or requests re-QC.
   Field evidence cannot be edited by the approver.
6. **Commercial** — deduction master versions, revised-price roll-up, and a
   commercial accept/hold decision tracked separately from QC acceptance.
7. **Packing → Pickup / Courier → Warehouse** — package builder with seal control
   and printable manifest, logistics-mode recommendation by threshold, handover or
   AWB capture with tracking timeline, and GRN with variance and discrepancy log.
8. **Dashboard / Reports** — milestone RAG, chain-of-custody funnel, productivity,
   regional and Deshwal-vs-partner split, SLA ageing, CSV exports and printable PDFs.

---

## Business rules enforced in the app

| Rule | Behaviour |
|---|---|
| BR-01 | Only Reliance-accepted assets appear in Packing; anything else is rejected. |
| BR-02 | Deduction % is read-only for every role except the Commercial Approver. |
| BR-03 | No Power auto-sets display / keyboard / touchpad to *Not Tested-No Power*. |
| BR-04 | Overall photo always mandatory; defect photo mandatory for exception codes. |
| BR-05 | A submitted QC record is immutable — a correction creates a linked re-QC version. |
| BR-06 | Duplicate serial is blocked at capture, at bulk import and on the asset. |
| BR-07 | Multiple defects use the configured rule — default *highest applicable*. |
| BR-08 | A package cannot be dispatched twice; counts are validated before dispatch. |
| BR-09 | An open warehouse discrepancy locks asset closure until disposition is recorded. |
| BR-11 | Every deduction-master change is a new effective-dated, approver-signed version. |
| BR-12 | Closure requires QC + acceptance + packing + dispatch + GRN. |

Deduction percentages ship at **0%** with the master marked
*Pending Reliance Approval* — exactly as BRD Sec 7 requires. Publish an approved
version from **Admin → Deduction master** to activate pricing; records already
commercially accepted keep the version they were priced under.

---

## The data

`js/inventory.js` is generated from the source workbook and holds the compact
master: 622 locations, 121 article SKUs and 3,568 inventory lines that expand into
3,957 individual asset records at first load — 3,394 laptops (MacBook Air / Pro),
507 desktops (iMac, Mac mini, Mac Studio, Mac Pro) and 56 Studio Displays. Each SKU
string is parsed into make, model, chip, RAM and storage, which prefill the QC form.
Displays are routed to the monitor checklist rather than the desktop one, while
keeping the source MH Family for reporting.

Everything from the source is preserved and mapped:

| Source field | Where it appears |
|---|---|
| State / City / Site / Site Description / Format | Site master, sites list, MIS export |
| Zone | Region, dashboard regional progress |
| MH Family / Class / Brick, Article, Article Description | Asset master, QC report export |
| Storage Location, Inventory Type, Stock Quantity | Asset records (expanded per unit) |
| RRP / MRP | Base / agreed price and MRP; drives the deduction engine |
| Value of Shipment, QC / Packing / Pickup / FOV / Total charges, Weight | Site costing panel, charge rate card, MIS export |
| Charges post confirmation | Site costing panel, charge rate card, MIS export |
| Tat Days, Tat Days after halting | Site TAT, TAT-risk flag against the Day-45 path |
| Executed By | Executing partner — Deshwal (251) vs SAI/DVC (371) split |

Reconciled against the workbook Grand Total: **₹26,77,637** total charges,
**₹36,10,637** post-confirmation, **15,828 kg**, **3,957 units**, **622 locations**.

### Serial numbers

Serial numbers are **not** in the source workbook — it carries quantity per SKU per
site. Every unit therefore starts with a `PEND-…` placeholder, and the serial is the
first thing the app asks for. Once captured it is mapped to that site's inventory
line and becomes the unit's identity everywhere: search, QC, packing manifests,
AWB logs, GRN and every export.

Three ways to populate them:

- **In the field** — the serial step at the start of every QC (the normal path).
- **Bulk import** — Admin → Serial mapping accepts a CSV with a `Serial` column plus
  either `Asset Tag` (exact unit) or `Site` (name, code or ID), optionally with
  `Article` to target a specific SKU. Duplicates and in-file repeats are rejected.
- **Serial register** — a searchable view of every mapped and pending unit, by site
  or by unit, exportable as the full serial ↔ site mapping.

Coverage is visible at three levels: per site (on the site job), per location list
(serial register → by site), and nationally (register header).

### Refreshing the master

When Reliance issues a new inventory file, either:

- **In-app** — Admin → Data import → upload a CSV (template provided in that screen), or
- **Regenerate** — re-run the generator against the new workbook to rebuild
  `js/inventory.js`. Devices detect the new build fingerprint and re-seed
  automatically when no field work would be lost; if QC has already been captured,
  the mismatch is flagged for the PMO to reconcile instead of overwriting.

---

## Shared store — devices agree with each other

Submit a QC on the engineer's phone and it appears in the approver's queue; accept
it there and the unit is released for packing everywhere. Each device still writes
locally first and keeps working with no network — sync is what makes the devices
agree, not what makes them work.

- **How** — `js/sync.js` pushes what this device changed and pulls what changed
  elsewhere in one round trip to `POST /fieldops/api/sync`, every 20 seconds, on
  reconnect, when the app returns to the foreground, and 1.5 s after any edit.
- **What travels** — QC records, commercial records, assets, sites, packages,
  movements, receipts, users, deduction masters, rate cards and the audit log.
  The 3,957-unit inventory master never travels: every device seeds it identically
  from `inventory.js`, so only field activity crosses the wire.
- **Conflicts** — last-write-wins on the device's own edit time, so a phone that was
  offline for an hour cannot overwrite a decision taken since. QC records are
  append-only in the app itself (a correction is a new re-QC version), so the cases
  that matter never contend.
- **Record ids carry a device code** (`QC-WDL-000012`) — two engineers working
  offline on the same day can never mint the same id.
- **Offline** — changes queue on the device and drain automatically on reconnect;
  the banner shows what is held.
- **Without the API** — opened from a plain file server, the app reports "this device
  only" and carries on. Nothing is lost, nothing is shared.

Server side: `routers/fieldops.py` exposes the endpoint behind the OxyPC login, and
`models/fieldops.py` stores one JSON row per record in `fieldops_records`. That table
has no foreign keys into inventory, lots or users, so the field project can be
archived without touching OxyPC data.

## Storage and the backend

The app is **local-first**. All records persist to the device (`localStorage`) and
survive reload, airplane mode and app restart, then sync to the shared store above.

The seeded master occupies roughly **1.4 MB** of a typical 5 MB budget, leaving room
for around 40 compressed photos per device before the app starts shedding cached
image data (records are never lost, and Admin → Data shows the current usage).
That is sized for a pilot. For the full 45-day national rollout, photos and records
should sync to a server.

`Admin → Backup` exports the full JSON snapshot of a device, useful for support and
for seeding a fresh environment.

---

## What is a prototype and what is production-shaped

Production-shaped: the workflow, business rules, RBAC, pricing engine, deduction
versioning, SLA/escalation logic, audit trail, exports and offline capture.

Still to come before a production rollout, per BRD Sec 21:

- **FR-001 Authentication** — the demo uses a role picker and a shared PIN.
  Real OTP / password / SSO (SAML/OIDC) is a server concern.
- **Courier API tracking** — AWB status is entered manually (as the BRD specifies for MVP).
- **Password self-service** — someone who forgets their password needs an
  administrator to issue a new one; there is no email reset flow.
- **Photo retention policy** — pending Reliance confirmation (Open Decision #5).

None of the Day-0 items in BRD Sec 17 are resolved by this build; the app surfaces
them (deduction matrix unapproved, site readiness unconfirmed) rather than assuming them.

---

## Administration

Everything below is **administrator only**, enforced on the server.

**Admin → Users & permissions**:

- **Add / edit users** — name, employee ID (the login), role, region and account status.
  Employee IDs are unique; changing a role resets module access to that role's default.
- **Assign sites** — a searchable picker over all 622 locations (by site, city, state,
  code or partner) with unit counts, select-all-matches and a live "units in scope"
  total. Assigned sites float to the top. Field Engineers and Reliance SPOCs see only
  what is assigned to them; coordinators, packers and warehouse users fall back to
  their region when nothing is assigned.
- **Permissions** — a per-user module matrix on top of the role default. Ticking a
  module the role does not have grants it; unticking one it does have revokes it.
  Both the navigation and the routes respect it, so a revoked module disappears and
  its URL returns *Access restricted*.
- **Set password** — issue or reset a password for anyone. Existing passwords cannot
  be read, only replaced; the user must choose their own at their next sign-in.
- **Deactivate / delete** — deactivation blocks sign-in and all access while keeping
  history. Deletion is refused for the last active administrator and for the account
  you are signed in with.

Every change is written to the immutable audit log with the before/after detail.

**Admin → Serial mapping** covers bulk serial import, the CSV template and the
current-mapping export; the full register lives under **Serial register** in the nav.

**Admin → Backup** holds bulk export and import for the whole shared store — every
record every device has synced, as one JSON document, plus the account list (never
passwords). Import merges by default, or replaces the store outright.

### QC & charges

**Admin → QC & charges** holds the costing rate card — the planning/commercial
charges, kept separate from the asset-condition deduction matrix.

Every charge is a formula, and each input is editable:

| Charge | Logic |
|---|---|
| QC charge | block rate × ⌈units ÷ block size⌉ — ₹1,500 per 20 units |
| Packing | ₹150 per unit |
| Weight | 4 kg per unit |
| Pickup | ₹84/unit at or above 28 units; otherwise ₹600 single / ₹1,050 cluster (2–9) / ₹1,500 dedicated |
| FOV | 0.1% of shipment value, where applicable |
| Shipment value | Σ RRP of the units standing at the site |
| Total | QC + packing + pickup + FOV |
| Post-confirmation | total + ₹1,500 |

These were derived from your costing sheet and reconcile against it exactly: QC,
packing, weight, FOV, total and post-confirmation match all 622 sites; pickup matches
605. The other 17 (a Delhi/NCR premium the formula cannot express) are flagged as
**manual overrides** at load, so a rate-card change never silently overwrites a
negotiated figure. Re-applying the baseline card produces a delta of ₹0.

Workflow: edit the rates → **Preview impact** (sites in scope, sites changing, total
before/after, the largest movements — nothing is written) → **Publish & apply**.
Publishing creates a new effective-dated, approver-signed version; earlier versions
are retained. Any single site can be overridden by hand or reset back to the card.

### Bulk upload

**Admin → Bulk upload** takes five datasets, each with a template and a row-by-row
validation report: **inventory/assets**, **serials**, **site details & SPOC**,
**site charges**, and **users**. Uploads are additive — new rows are added and
matching rows updated by their key (site name/code, asset tag, employee ID).
Nothing is removed by an upload.

### Delete data

**Admin → Delete data** covers removals, with guards:

- **Delete a location** — removes the site, its units and any packages, dispatches
  and receipts. Requires typing the site name; sites holding recorded work need an
  extra confirmation.
- **Delete units** — by asset tag or serial. Units with QC or movement history are
  skipped unless you explicitly force it.
- **Archive a QC record** — QC evidence is **never hard-deleted**. Archiving pulls it
  out of the live queues and returns the unit to Pending QC while retaining the
  record, its evidence and its audit trail (BRD "no delete, soft-archive only").
- **Bulk clear** — photo cache, all serials, all QC and movement records (keeping the
  inventory master), or a full reset to the source master.

Every deletion and archive is audit-logged with counts and the user who did it.

## Self-test

`tools/selftest.js` drives the whole chain headlessly — suppression, photo rules,
pricing, approvals, packing gates, dispatch, GRN, discrepancy, closure, deduction
versioning, CSV import, audit and source-master reconciliation.

Three suites — the core chain; serial capture and user administration; charges,
bulk upload and deletion. Open the app, then in the browser console:

```js
fetch('/tools/selftest.js').then(r => r.text()).then(t => console.log(eval(t)))
```

```js
fetch('/tools/selftest-serial-admin.js').then(r => r.text()).then(t => console.log(eval(t)))
```

```js
fetch('/tools/selftest-charges-admin.js').then(r => r.text()).then(t => console.log(eval(t)))
```

```js
fetch('/tools/walkthrough.js').then(r => r.text()).then(t => eval(t)).then(console.log)
```

The first three drive the data layer and print `46/46`, `31/31` and `36/36`.
The fourth is a **UI walkthrough** — it signs in, opens a site, captures a serial,
taps the checklist, submits, approves, prices, packs, dispatches, receives and closes
a unit by clicking the real buttons and filling the real dialogs, then checks the
dashboard, audit log, offline capture and persistence. It prints `34/34`.

```js
fetch('tools/selftest-sync.js').then(r => r.text()).then(t => eval(t)).then(console.log)
```

The fifth covers the shared store — push, pull, a second device receiving a QC, a
remote approval landing back, stale-write rejection and offline drain (`15/15`). It
needs the app served by the FastAPI route; standalone it reports the API as
unavailable and stops.

162 checks in total. Each resets local data, so sign in again afterwards.

## Regenerating the master

```bash
python3 tools/generate_inventory.py
```

Reads `Inventory Details_LP TAT & Costing.xlsx` and rewrites `js/inventory.js`.
No third-party packages — the workbook reader in `tools/xlsx.py` is self-contained.
Point `SRC` at the new file when Reliance issues an updated inventory.

## Files

```
index.html              app shell
manifest.webmanifest    PWA manifest (installable, standalone)
sw.js                   service worker — offline shell + update prompt
css/app.css             all styling, mobile-first with a desktop sidebar layout
js/inventory.js         generated source master (622 sites, 3,957 units)
js/data.js              masters, config, QC schema, defect codes, seeding
js/store.js             persistence, audit, business rules, pricing, SLA
js/ui.js                UI helpers, photo capture/compression, scanner, exports
js/screens-field.js     Login, My Day, Sites, Site Job, Scan, Rapid QC, Asset
js/screens-ops.js       Approvals, Commercial, Packing, Pickup, Courier, Warehouse
js/screens-admin.js     Dashboard, Reports/MIS, Serial register, Alerts, Audit, Admin, Profile
icons/                  app icons
tools/                  inventory generator + headless self-test (not served to users)
```
