# OxyPC Inventory — Full CLAUDE.md Compliance Audit
**Date:** 2026-04-29
**Scope:** All CLAUDE.md frameworks — MCS 5-Layer · 7-Layer As-Is (updated) · Database-First Engineering Standards · Testing Strategy · Build Governance · Pre-Commitment Profitability Gate · Audit Trail
**Previous audit:** 2026-04-28 — Overall 5.3/10 🟡 (post-remediation)
**This audit:** Overall **5.6/10 🟡** — new findings in Performance, Testing, Audit Trail, and Profitability Gate

---

## Section 1 — MCS 5-Layer Audit

The Master Control System (MCS) defines a 5-layer governance check: Process · Database · Performance · Security · Commercial.

| Layer | Score | Status | Key Finding |
|---|---|---|---|
| Process | 7.0 | 🟢 | Stage FSM enforced; workflow gaps in IQC audit trail |
| Database | 6.0 | 🟡 | UUID PKs, migrations, indexes — no soft delete, no views/procs |
| Performance | 4.0 | 🔴 | N+1 in stock list; unbounded queries across all list routes |
| Security | 6.5 | 🟡 | Secrets moved to .env; RBAC gaps remain in dealers/admin |
| Commercial | 3.5 | 🔴 | No margin floor, no profitability gate, no Deal Calculator |
| **MCS Overall** | **5.4** | 🟡 | |

---

### MCS-1 Process (7.0 🟢)

**Compliant:**
- Stage transitions enforced by `AllowedTransition` DB table — not bypassable through UI
- `validate_transition()` queries DB directly on every call (no cache risk)
- Sale blocked unless device is in `ready_to_sale` (`validate_sale_allowed`)
- Admin stage-control UI allows adding/removing transitions without code changes
- Auto-scrap trigger exists when `total_cost >= expected_sale_value`

**Gaps:**
| # | Finding | Severity |
|---|---|---|
| P-1 | IQC device creation and approval writes NO audit log entry — entry of stock into the system is completely untracked | High |
| P-2 | Lot creation (GRN receipt) writes `GRN_SUBMITTED` but lot acceptance has no profitability validation | High |
| P-3 | Admin bypass (`override_admin=True`) is not logged as a distinct event — the stage move is logged but the bypass itself is not | Medium |
| P-4 | `expected_sale_value` defaults to `None` — auto-scrap and scrap-warning engine never fires unless manually set per device; no formula or catalogue lookup to populate it | Medium |

---

### MCS-2 Database (6.0 🟡)

**Compliant:**
- UUID PKs across all 22 models
- `snake_case` naming; consistent `<ref>_id` FK naming
- Alembic with 11 versioned migrations
- Composite indexes on hot search paths (Sprint 18)
- `pool_size=20`, `max_overflow=10`, `pool_pre_ping=True`
- `db_validator.py` runs at startup — catches schema drift before first request

**Gaps:**
| # | Finding | Severity |
|---|---|---|
| DB-1 | **No soft-delete pattern** — `db.delete()` used throughout; no `is_active`/`deleted_at` on any table; deleted devices, lots, and users leave no trail | High |
| DB-2 | **Zero stored procedures, views, or triggers** — all business logic is in Python ORM; reports, cost calculations, and status transitions have no DB-layer encapsulation | High |
| DB-3 | **No bounded contexts / schema namespacing** — all 22 models in `public` schema; cross-module coupling will be uncontrollable at SaaS scale | Medium |
| DB-4 | GST fields (`sgst`, `cgst`, `igst`) now included in `base_cost` (fixed Apr-28) but `buying_price` on `lots` still refers to pre-tax invoice value — semantic ambiguity | Low |

---

### MCS-3 Performance (4.0 🔴)

**Compliant:**
- IQC list uses single JOIN query — no N+1
- Repair list uses structured JOINs — no N+1
- Audit log viewer has LIMIT/OFFSET pagination
- Database connection pool correctly sized (20 + 10 overflow)

**Gaps — Critical:**
| # | Finding | File:Line | Severity |
|---|---|---|---|
| PERF-1 | **2N+1 query loop in stock list** — loads all lots then fires 2 COUNT queries per lot inside a Python loop. With 100 lots = 201 DB round-trips per page load. Replace with single GROUP BY + conditional COUNT | `routers/stock.py:26-34` | 🔴 High |
| PERF-2 | **No pagination on ANY list route** — `iqc.py`, `stock.py`, `repair.py`, `qc.py`, `sales.py`, `dealers.py` all do unbounded `.all()` — entire table loaded into memory on every page hit. At 10,000 devices this becomes a critical issue | All list routes | 🔴 High |
| PERF-3 | Dashboard fires 15+ sequential DB queries — each section runs independently; some sections could be batched or parallelised | `routers/dashboard.py` | Medium |
| PERF-4 | `routers/crm_contacts.py` and `routers/reports.py` have no result limit on export queries — a `/reports/export/lot-pl` with 1,000 lots loads everything into a Python StringIO before streaming | `routers/reports.py:136-175` | Medium |

---

### MCS-4 Security (6.5 🟡)

*Updated from 3.5 🔴 after Apr-28 remediation.*

**Now compliant (post-remediation):**
- Secrets in `.env` (gitignored); `config.py` + `backup_db.py` read env vars
- Login rate limit: 5/min
- CSRF on logout
- bcrypt password hashing
- `httponly=True, samesite=strict` on JWT cookie
- Error detail gated behind `OXYPC_DEBUG=1`
- `/reports/*` role-gated to management roles

**Remaining gaps:**
| # | Finding | Severity |
|---|---|---|
| SEC-1 | Ad-hoc inline role checks in `dealers.py` and `admin.py` — inconsistent, not using `require_roles()` decorator | Medium |
| SEC-2 | Login audit log writes `ip_address` but **no failed-login counter** — brute force across 5-min window is unconstrained (attacker gets 5 attempts per minute, unlimited windows) | Medium |
| SEC-3 | JWT has no revocation — a compromised token is valid for the full 60-min TTL; no session blacklist | Medium |
| SEC-4 | `HS256` symmetric JWT — if `SECRET_KEY` leaks, attacker can forge tokens for any role | Low |
| SEC-5 | No account lockout after N failed logins | Low |

---

### MCS-5 Commercial (3.5 🔴)

This is the largest compliance gap against CLAUDE.md's **Pre-Commitment Profitability Gate** ("Deal Calculator") requirement.

**CLAUDE.md requires before any commercial commitment:**
1. Five cost categories (Acquisition / Transport / Processing / Loss adjustment)
2. Revenue model with grade/tier mix and yield %
3. Three output metrics: Gross Margin %, Profit per Unit, ROI %
4. Three-band verdict: ACCEPT / RENEGOTIATE / DECLINE
5. Margin floors in `*_floor_config` table with effective dates
6. All calculations server-side
7. Immutable versions — renegotiations create new versions
8. Post-decision variance tracking

**Actual state:**

| Requirement | Present? | Evidence |
|---|---|---|
| Cost calculation (acquisition + processing) | Partial | `cost_engine.py` calculates base+parts+labour but not transport/logistics costs |
| Revenue model with grade/yield mix | No | No grade-to-price mapping; `expected_sale_value` is manually set or NULL |
| Gross Margin % per deal | No | `our_offer_total` stored but no margin % calculated |
| ACCEPT/RENEGOTIATE/DECLINE verdict | No | Deal committed unconditionally (`crm_sourcing.py:177-179`) |
| `*_floor_config` table | No | `SCRAP_WARNING_RATIO = Decimal("0.70")` is a hardcoded Python constant |
| Server-side margin calculation | No | Client enters price, stored as-is, no backend validation |
| Immutable versioning on renegotiation | No | Deal is updated in-place (`update_deal` overwrites all fields) |
| Post-decision variance tracking | No | No actuals-vs-estimate comparison anywhere |

**Score: 3.5/10 🔴** — the most non-compliant area against CLAUDE.md standards.

---

## Section 2 — Database-First Engineering Standards Compliance

CLAUDE.md mandates a strict build sequence: Process → Schema → Stored Procs → APIs → UI.

| Standard | Compliant? | Evidence |
|---|---|---|
| Build sequence (schema before API) | ✅ Partial | Alembic-first approach; migrations predate most routes |
| Bounded contexts per functional area | ❌ | All in `public` schema; 22 models in one pool |
| Table types separated (master/transaction/audit) | ✅ Partial | `audit_logs`, `stage_master` separate; but `lots` mixes master+transaction data |
| Naming conventions (snake_case, `<ref>_id`) | ✅ | Consistent throughout |
| Soft delete (`is_active` + `deleted_at`) | ❌ | Not implemented on any model |
| Data retention policy | ❌ | No documented retention; no archival strategy |
| Indexing strategy (composite on hot paths) | ✅ | Composite indexes added Sprint 18 |
| Stored procedures for complex logic | ❌ | Zero stored procedures; all in Python |
| Views for reporting / AI layer | ❌ | Zero database views; all reports are raw ORM queries |
| Status flows = finite state machines | ✅ | AllowedTransition table + validate_transition() |
| Audit logs (append-only, encrypted, RBAC) | ⚠️ Partial | Table exists, not append-only by constraint, not encrypted, RBAC enforced at viewer |
| Immutable versioning on decisions | ❌ | Deals, quotes, and lots are updated in-place |
| RBAC row-level security enforced in DB | ❌ | RBAC is application-layer only; DB has no row-level security policies |
| PII field-level encryption | ❌ | No field-level encryption on `users`, `dealers`, or `crm_contacts` |
| Tenant isolation | ⚠️ | `tenant` column added to `users`; no schema routing yet |

---

## Section 3 — Testing Strategy Compliance

CLAUDE.md requires: Unit · API · Database · Workflow · Role/RBAC · Audit · Certificate · Performance · Backup-Recovery · AI Response · UAT.

| Test Category | Required | Present | Coverage |
|---|---|---|---|
| Unit tests | ✅ Required | ✅ Present | Model-layer only (field existence, column types). No business logic tested. |
| API tests | ✅ Required | ❌ Absent | No `httpx`/`TestClient` API-layer tests exist |
| Database tests | ✅ Required | ❌ Absent | No referential integrity, trigger, or constraint tests |
| Workflow tests | ✅ Required | ⚠️ Partial | `e2e_uat_test.py` covers some workflows but requires live server |
| Role/RBAC tests | ✅ Required | ❌ Absent | No test verifies that role X cannot access route Y |
| Audit log tests | ✅ Required | ❌ Absent | No test verifies that action X generates an audit entry |
| Certificate tests | N/A | N/A | No certificate generation in scope yet |
| Performance/Load tests | ✅ Required | ⚠️ Partial | `e2e_uat_test.py` has a "5000 units/day" simulation — not a real load test |
| Backup-Recovery | ✅ Required | ❌ Absent | No restore test exists |
| UAT | ✅ Required | ✅ Present | `tests/test_uat.py` + Excel UAT plan |

**Infrastructure gaps:**
- `pytest` not in `requirements.txt` — tests cannot be run without manual install
- No `conftest.py` — no shared fixtures, no test DB setup/teardown
- No CI pipeline — tests are never run automatically
- No `httpx` or `starlette.testclient` — API layer is untestable without a live server

**Score: 3.0/10 🔴**

---

## Section 4 — Build Governance Compliance

| Standard | Compliant? | Evidence |
|---|---|---|
| Schema review before table creation | ✅ | Alembic migration required for all schema changes |
| Change request process | ❌ | No formal change request template or impact assessment process |
| API naming (RESTful, versioned, no verb paths) | ⚠️ Partial | RESTful naming mostly correct; no versioning (`/v1/`); `/grn/submit` is a verb-path violation |
| Bug priority system (P0/P1/P2/P3) | ❌ | No documented bug triage process |
| DevOps + Architect approval for production deploys | ❌ | No deployment approval gate exists |
| Rollback scripts for migrations | ❌ | Alembic `downgrade()` stubs exist but no documented rollback runbook |
| API contract documentation | ❌ | No OpenAPI spec published/exported; FastAPI auto-docs at `/docs` only |

---

## Section 5 — Audit Trail Completeness

CLAUDE.md requires an append-only `audit_logs` table for all write operations, enforced by triggers/stored procedures.

### Coverage Map

| Module | Write Operations | Audited? |
|---|---|---|
| IQC | Device registration, cosmetic grading, stage approval | ❌ None |
| Stock / Lots | Lot creation, GRN submission, lot editing | ⚠️ GRN submit only |
| Repair | Job start, parts consumption, stage move, complete | ✅ All covered |
| QC | Pass/fail decision, grade change | ⚠️ Partial |
| Sales | Sale creation, return, invoice | ✅ Sale + return covered |
| Spare Parts | Stock-in, issue, low-stock | ❌ None |
| Admin | User create, edit, disable, role change | ❌ None |
| CRM | Deal create, stage move, contact create | ❌ None |
| Dealers | Order create, credit note issue, receipt | ⚠️ Receipt only |
| Stage Control | Add/remove allowed transition | ✅ Both covered |

**Unaudited critical operations:**
1. User creation / role change / password reset — **highest risk** (privilege changes must be traceable)
2. Device registration (IQC) — stock entry cannot be traced
3. Lot / GRN creation — acquisition commitment untracked
4. CRM deal creation and edits — commercial decisions untracked
5. Spare parts consumption — inventory depletion untracked

**Score: 4.5/10 🔴** — audit trail covers ~35% of write operations

---

## Section 6 — Performance Remediation Plan

The 2N+1 in stock list and unbounded queries are the highest-impact fixes.

### Fix 1: stock.py N+1 → single GROUP BY (High priority, ~2h)

**Current (201 DB calls for 100 lots):**
```python
for lot in lots:
    dev_count = await db.execute(select(func.count(Device.id)).where(...))
    sold_count = await db.execute(select(func.count(Device.id)).where(...))
```

**Replace with (1 DB call):**
```python
stats_rows = await db.execute(
    select(
        Device.lot_id,
        func.count(Device.id).label("total"),
        func.count(Device.id).filter(Device.current_stage == DeviceStage.sold).label("sold")
    ).group_by(Device.lot_id)
)
stats = {str(r.lot_id): {"total": r.total, "sold": r.sold} for r in stats_rows}
```

### Fix 2: Add pagination to all list routes (High priority, ~4h)

Standard pattern to add to every list GET:
```python
@router.get("", response_class=HTMLResponse)
async def list_devices(
    request: Request,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, le=200),
    ...
):
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)
    total = await db.scalar(select(func.count()).select_from(base_query.subquery()))
```

---

## Full Compliance Scorecard (Updated)

### 7-Layer As-Is (updated post Apr-29 evidence)

| Layer | Apr-26 | Apr-28 | Apr-29 | Δ |
|---|---|---|---|---|
| L1 Business Process | 6.0 🟡 | 7.0 🟢 | 6.5 🟡 | IQC audit gap found |
| L2 Database / Schema | 5.5 🟡 | 6.0 🟡 | 6.0 🟡 | No change |
| L3 API / Backend | 4.0 🔴 | 4.5 🔴 | 5.0 🟡 | N+1 noted, no versioning |
| L4 UI / UX | 5.5 🟡 | 7.0 🟡 | 7.0 🟡 | No change |
| L5 Security | 3.5 🔴 | 3.5 🔴 | 6.5 🟡 | Fixed: .env, rate limit, CSRF |
| L6 Deployment / DevOps | 3.0 🔴 | 3.5 🔴 | 3.5 🔴 | No change yet |
| L7 Financial / Reporting | 5.0 🟡 | 5.5 🟡 | 5.5 🟡 | Audit gaps noted |
| **Overall** | **4.9 🔴** | **5.3 🟡** | **5.6 🟡** | |

### New Framework Scores (first audit)

| Framework | Score | Status |
|---|---|---|
| MCS 5-Layer | 5.4 | 🟡 |
| Database-First Standards | 4.5 | 🔴 |
| Testing Strategy | 3.0 | 🔴 |
| Build Governance | 4.0 | 🔴 |
| Audit Trail | 4.5 | 🔴 |
| Pre-Commitment Profitability Gate | 3.5 | 🔴 |

---

## Prioritised Remediation Backlog

### 🔴 Must Fix Before Production / SaaS Launch

| # | Issue | Effort | Impact |
|---|---|---|---|
| 1 | Add `pytest` + `conftest.py` + test DB fixture to `requirements.txt` | 2h | Enables all future testing |
| 2 | Fix 2N+1 in `stock.py` lot list | 2h | Dashboard + stock page performance |
| 3 | Add pagination (page/per_page) to all list routes (IQC, Stock, Repair, QC, Sales, Dealers) | 4h | Memory safety at scale |
| 4 | Write audit log on: user create/edit/disable, IQC device registration, lot creation, CRM deal create | 4h | Compliance + traceability |
| 5 | Add `require_roles()` to inline role checks in `dealers.py` and `admin.py` | 1h | Consistent RBAC enforcement |
| 6 | Add failed-login counter + account lockout (5 failed → 15-min lockout) | 3h | Brute force protection |

### 🟡 Fix Within Next 2 Sprints

| # | Issue | Effort |
|---|---|---|
| 7 | Create at least one materialized view for lot P&L stats (eliminate repeated aggregation queries) | 3h |
| 8 | Add `/api/v1/` versioning prefix to `routers/api.py` | 1h |
| 9 | Add soft-delete (`deleted_at`) to `devices`, `lots`, `users` (Alembic migration) | 4h |
| 10 | Populate `expected_sale_value` automatically from a grade-price lookup table (enables auto-scrap) | 1 sprint |
| 11 | Add rollback runbook doc for each Alembic migration | 2h |

### 🟢 Fix Before SaaS Launch (Stage 2)

| # | Issue | Effort |
|---|---|---|
| 12 | Pre-Commitment Profitability Gate on CRM sourcing deals (margin floor check, ACCEPT/RENEGOTIATE/DECLINE) | 2 sprints |
| 13 | `margin_floor_config` table with effective dates | 1 sprint |
| 14 | Immutable deal versioning (renegotiation creates new version, does not overwrite) | 1 sprint |
| 15 | DB-layer stored procedure for lot P&L calculation | 1 sprint |
| 16 | API-layer tests with injected test database (httpx + AsyncClient) | 1 sprint |
| 17 | RBAC test suite (verify role X cannot access route Y) | 1 sprint |
| 18 | Row-level security policies in PostgreSQL | 2 sprints |
| 19 | Post-decision variance tracking (actuals vs. estimates) | 1 sprint |

---

## Target State to Achieve 🟢 Overall

| Layer | Current | Target | Key Action |
|---|---|---|---|
| L1 Business Process | 6.5 🟡 | 8.0 🟢 | Audit trail on IQC + lot creation |
| L2 Database / Schema | 6.0 🟡 | 8.0 🟢 | Soft delete + DB views |
| L3 API / Backend | 5.0 🟡 | 8.0 🟢 | Pagination + N+1 fix + versioning |
| L4 UI / UX | 7.0 🟡 | 8.0 🟢 | Consistent RBAC decorators |
| L5 Security | 6.5 🟡 | 8.5 🟢 | Lockout + JWT revocation |
| L6 Deployment / DevOps | 3.5 🔴 | 8.0 🟢 | Cloud deploy + offsite backup + CI |
| L7 Financial / Reporting | 5.5 🟡 | 8.5 🟢 | Profitability gate + variance tracking |
| Testing | 3.0 🔴 | 8.0 🟢 | pytest + API tests + RBAC tests |
| Audit Trail | 4.5 🔴 | 9.0 🟢 | All write operations audited |
| **Overall** | **5.6 🟡** | **8.3 🟢** | |

*Estimated timeline: 3–4 sprints to reach 7.5+ overall.*

---

*Next audit recommended: After remediating items 1–6 above. Expected score: ~6.5–7.0.*
