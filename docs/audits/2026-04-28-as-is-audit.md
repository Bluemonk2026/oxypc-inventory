# OxyPC Inventory — Phase 2.5 Enterprise As-Is Audit
**Date:** 2026-04-28  
**Auditor:** Claude (automated code audit against CLAUDE.md enterprise standards)  
**Previous audit:** 2026-04-26 — Overall 4.9/10 🔴  
**This audit:** Overall **5.3/10 🟡** — material progress, 3 layers still RED/near-RED

---

## Layer Scorecard

| Layer | Score | Status | Δ vs Apr-26 |
|-------|-------|--------|-------------|
| L1 — Business Process | 7.0 | 🟢 | +1.0 (stage enforcement confirmed solid) |
| L2 — Database / Schema | 6.0 | 🟡 | +0.5 (composite indexes added) |
| L3 — API / Backend | 4.5 | 🔴 | +0.5 (bcrypt confirmed, error logging added) |
| L4 — UI / UX | 7.0 | 🟡 | +1.5 (CSRF auto-inject confirmed working) |
| L5 — Security | 3.5 | 🔴 | ±0 (secrets still plaintext, 30/min login too loose) |
| L6 — Deployment / DevOps | 3.5 | 🔴 | +0.5 (db_validator on startup confirmed) |
| L7 — Financial / Reporting | 5.5 | 🟡 | +0.5 (full lot-pl confirmed accurate) |
| **Overall** | **5.3** | 🟡 | **+0.4** |

Score scale: 1–10 · GREEN ≥7.5 · YELLOW 5–7.4 · RED <5

---

## L1 — Business Process (7.0 🟢)

### Strengths
- Stage transitions enforced server-side via `AllowedTransition` DB table — cannot be bypassed from UI
- `services/control_engine.py` `validate_transition()` executes a live DB query on every move
- 32 default transitions seeded; admin can add/remove via `/stage-control` UI
- Per-router enforcement: Repair, QC and Sales all call `validate_transition` or equivalent before mutating stage
- Sale enforces `ready_to_sale` stage check (`validate_sale_allowed`)

### Gaps (🟡)
| # | Finding | File | Severity |
|---|---------|------|----------|
| 1 | Admin bypass (`override_admin=True`) is unconditional — no logging of the override event itself, only the outcome | `routers/repair.py:134`, `services/control_engine.py:59` | Medium |
| 2 | IQC device creation hard-codes `DeviceStage.iqc` without going through AllowedTransition (acceptable by design — entry stage has no predecessor) | `routers/iqc.py:164` | Low |
| 3 | In-memory `_transitions_cache` is per-uvicorn-worker-process; with `workers=4` an admin change invalidates cache in ONE worker only — other 3 may enforce stale rules until next cache miss | `services/control_engine.py:12–45` | High |

---

## L2 — Database / Schema (6.0 🟡)

### Strengths
- UUID PKs across all 22 models — no integer sequences
- `snake_case` table naming, consistent `<ref>_id` FK naming
- Alembic configured; 10 migration files with descriptive slugs; DB URL not hardcoded in `alembic.ini`
- `pool_size=20`, `max_overflow=10`, `pool_pre_ping=True` — connection hygiene
- Composite indexes added in Sprint 18 migration for hot search paths
- Per-column indexes on `barcode` (unique), `brand`, `current_stage`, `updated_at`

### Gaps
| # | Finding | File | Severity |
|---|---------|------|----------|
| 4 | **No soft-delete pattern** — `db.delete()` is used throughout; deleted devices, lots, transitions, users leave no `deleted_at` trail | All models | High |
| 5 | No bounded contexts / schema namespacing — all tables in default PostgreSQL `public` schema; as the system grows cross-module coupling will be hard to control | — | Medium |
| 6 | `stage_movements` table exists but stage-move audit log completeness not verified; admin bypass moves (L1-gap-1) may not write a movement record | `routers/stage_control.py` | Medium |
| 7 | GST fields (`sgst`, `cgst`, `igst`) stored on `lots` but never referenced in cost calculations — creates schema-logic drift | `models/lot.py:27–29` | Medium |

---

## L3 — API / Backend (4.5 🔴)

### Strengths
- bcrypt for password hashing (`passlib[bcrypt]`)
- `get_current_user` on all routes (none are fully public except `/auth/login` and `/health`)
- `verify_csrf` dependency on all mutating routers
- Alembic-managed schema — no direct DDL in application code (except db_validator auto-fix)
- Error logging added to `errors.log` + console (Sprint fix)

### Gaps
| # | Finding | File | Severity |
|---|---------|------|----------|
| 8 | **Plaintext DB password and JWT secret in `config.ini`** — committed to project directory | `config.ini` | 🔴 Critical |
| 9 | **Financial reports unrestricted by role** — any authenticated user (IQC inspector, L1 engineer) can access `/reports/lot-pl`, `/reports/sales`, `/reports/export/*` | `routers/reports.py` (all routes) | High |
| 10 | Ad-hoc role checks inline in router functions instead of `require_roles()` dependency — inconsistent, easy to miss | `routers/dealers.py`, `routers/admin.py:228` | Medium |
| 11 | No Pydantic model validation on any form route — all inputs are `str = Form(...)` with manual casting; malformed floats/ints cause 422 or 500 | `routers/iqc.py`, `routers/repair.py` et al. | Medium |
| 12 | `routers/repair.py` GET list view (stage list) uses only `get_current_user`, not role-restricted — any authenticated user can view repair stage queues | `routers/repair.py:41–44` | Low |
| 13 | `db_validator.py` auto-fix uses f-string SQL (source is hardcoded constant, not user input — low risk, but the pattern should be parameterized) | `db_validator.py:209–215` | Low |

---

## L4 — UI / UX (7.0 🟡)

### Strengths
- CSRF auto-inject via JS in `base.html` (reads `csrf_token` cookie, appends hidden input to all POST forms at runtime) — elegant pattern that covers all templates centrally
- Server-side `verify_csrf` dependency enforced on all mutating routers
- Sidebar nav is fully RBAC-gated — each menu item behind `{% if role in [...] %}` checks
- Role-specific dashboard views — each role sees their own queue only
- Template-level role gates on Edit/Delete buttons (e.g., `devices/detail.html`)

### Gaps
| # | Finding | File | Severity |
|---|---------|------|----------|
| 14 | **Logout POST route lacks `verify_csrf` dependency** — an attacker can force a user to log out via a CSRF request | `routers/auth.py:61` (no `verify_csrf`) | Medium |
| 15 | JS-based CSRF inject depends on browser JS being enabled and the cookie being readable — a template that is served as a direct response (not extending `base.html`) would miss injection | `templates/base.html:354–381` | Low |
| 16 | Error detail displayed to all users in `error.html` (`{{ detail }}` block with full exception class + message) — acceptable for LAN dev context, must be removed before any public deployment | `templates/error.html:13–18` | Medium (for production) |

---

## L5 — Security (3.5 🔴)

### Strengths
- bcrypt password hashing (confirmed)
- `httponly=True, samesite="strict"` on the JWT access-token cookie — prevents JS access
- Rate limiting applied globally via SlowAPI (`100/minute` default)
- Reverse proxy trusted-IP support (`OXYPC_TRUSTED_PROXY=1`)

### Gaps
| # | Finding | File | Severity |
|---|---------|------|----------|
| 17 | **DB password `oxypc123` and JWT secret key in plaintext in `config.ini`** — also hardcoded in `backup_db.py` | `config.ini`, `backup_db.py:21–26` | 🔴 Critical |
| 18 | **No `.env` file** — `python-dotenv` is in requirements but no `.env` exists; developers fall back to `config.ini` | — | High |
| 19 | Login rate limit is `30/minute` — standard recommendation is `5/minute` for credential endpoints | `routers/auth.py:23` | Medium |
| 20 | HS256 symmetric JWT — if `secret_key` is compromised, attacker can forge valid tokens for any user/role; RS256 with private key signing would contain blast radius | `auth/dependencies.py:13` | Medium |
| 21 | No JWT revocation mechanism — stolen/leaked token valid for full 60-minute TTL; no logout-side blacklist or session table | `auth/dependencies.py` | Medium |
| 22 | `backup_db.py` stores backup files locally only, unencrypted; no offsite/cloud copy; local disk loss = data loss | `backup_db.py` | High |
| 23 | `config.ini` is present in the project working directory — if committed to git (not confirmed), secret exposure in version history | `config.ini` | 🔴 Critical |

---

## L6 — Deployment / DevOps (3.5 🔴)

### Strengths
- `db_validator.py` runs at server startup — catches schema drift before first request
- Auto-fix capability for missing columns/tables on startup
- Alembic with 10 versioned migrations — schema changes traceable
- `OXYPC_AUTO_FIX=0` env var allows disabling auto-fix in production if needed

### Gaps
| # | Finding | File | Severity |
|---|---------|------|----------|
| 24 | **No `.env` file, no secret management** — all config in `config.ini` plaintext file | — | 🔴 Critical |
| 25 | **Backup is local-only** — `backups/` subdirectory on same machine as DB; no remote copy, no encryption | `backup_db.py` | High |
| 26 | **`workers=4` with in-memory `_transitions_cache` per worker process** — cache invalidation by one worker is not propagated to the other three; stale transition rules can persist | `services/control_engine.py:12`, `main.py:259` | High |
| 27 | No environment separation — dev and production share the same `config.ini` pattern; no `.env.development` vs `.env.production` | — | Medium |
| 28 | No CI/CD pipeline, no automated test runner on commit | — | Medium |
| 29 | No rollback scripts for migrations — `alembic downgrade -1` is possible but no documented runbook | `alembic/` | Medium |
| 30 | `install_service.bat` is untracked — Windows service install script not in version control | `install_service.bat` (untracked) | Low |

---

## L7 — Financial / Reporting (5.5 🟡)

### Strengths
- `/reports/lot-pl` includes all three cost components: acquisition (`buying_price/qty`) + parts (`SUM(spare_parts_consumption)`) + labour (`SUM(repair_attempts.cost)`) — formula is correct
- Below-cost sale detection warns (doesn't block — intentional)
- Auto-scrap trigger exists when `total_cost >= expected_sale_value`

### Gaps
| # | Finding | File | Severity |
|---|---------|------|----------|
| 31 | **Dashboard Lot P&L widget omits labour cost** — `total_cost = buying + parts_cost` only; dashboard systematically overstates profit when repair costs exist | `routers/dashboard.py:254` | High |
| 32 | **GST not in landed cost** — `sgst`, `cgst`, `igst` stored in `lots` table but excluded from `DeviceCosting.base_cost` (`buying_price / qty` only); true landed cost understated by tax amount | `services/cost_engine.py:42`, `models/lot.py:27–29` | High |
| 33 | **Financial reports accessible to all authenticated users** — no role guard on `/reports/` routes | `routers/reports.py` | High |
| 34 | `expected_sale_value` defaults to `None` — auto-scrap and scrap-warning logic never fires unless explicitly populated per device; there is no default/formula to populate it | `services/cost_engine.py:52,105` | Medium |
| 35 | No variance tracking — actuals vs. lot estimate not stored anywhere; the "Deal Calculator" pattern in CLAUDE.md requires post-decision variance feed-back | — | Medium |

---

## Top 5 Critical Risks (Remediate Immediately)

### 🔴 RISK-1: Plaintext Secrets in Config Files
**Files:** `config.ini` (DB password, JWT secret), `backup_db.py` (DB password)  
**Impact:** Anyone with filesystem access can impersonate any user or directly connect to the DB.  
**Fix:**
1. Create `.env` with `OXYPC_DATABASE_URL`, `OXYPC_SECRET_KEY`, `OXYPC_BACKUP_DB_PASS`
2. Update `config.py` to read env vars (already supports `OXYPC_DATABASE_URL`); add `OXYPC_SECRET_KEY` override
3. Update `backup_db.py` to read `os.environ.get("OXYPC_BACKUP_DB_PASS")`
4. Add `.env` to `.gitignore`; replace `config.ini` secrets with placeholder comments

### 🔴 RISK-2: Multi-Worker Cache Inconsistency
**File:** `services/control_engine.py:12–45`, `main.py:259`  
**Impact:** After admin changes allowed transitions, 3 of 4 workers continue enforcing old rules. A device can be moved to a stage that the admin just blocked — or blocked from a stage the admin just opened.  
**Fix (choose one):**  
- Option A (quick): `workers=1` — removes inconsistency; reduces throughput but acceptable for LAN use  
- Option B (proper): Replace in-memory dict cache with Redis or PostgreSQL advisory lock + DB-side cache busting; or drop cache entirely (DB query is fast for 32-row table)

### 🔴 RISK-3: Financial Reports Unrestricted by Role
**File:** `routers/reports.py`  
**Impact:** An IQC inspector, L1 repair tech, or any employee can view full financial P&L, lot buying prices, and margins — business-sensitive data.  
**Fix:** Add `require_roles(UserRole.admin, UserRole.inventory_manager, UserRole.sales_manager)` dependency to all `/reports/` routes.

### 🟡 RISK-4: Dashboard Lot P&L Understates Cost (Labour Missing)
**File:** `routers/dashboard.py:254`  
**Impact:** Dashboard shows inflated profit figures; managers make restocking/pricing decisions on wrong numbers.  
**Fix:** Add the repair labour sub-query to dashboard Lot P&L (same pattern as `reports/lot-pl` line 75). Single SQL join change.

### 🟡 RISK-5: GST Excluded from Per-Device Landed Cost
**File:** `services/cost_engine.py:42`, `models/lot.py:27–29`  
**Impact:** Profitability is overstated by the GST paid on the lot. For high-volume lots this can be material.  
**Fix:** `base_cost = (buying_price + sgst + cgst + igst) / qty`. Requires `lot` object to be passed to cost engine (currently only `lot.buying_price` and `lot.qty` are used).

---

## 30-Day Recovery Sprint Plan

### Week 1 — Fix all RED findings (Security + Secrets)

| Task | Owner | Effort |
|------|-------|--------|
| Create `.env` file with all secrets; update `config.py` and `backup_db.py` to read env vars | Dev | 2h |
| Add `.env` to `.gitignore`; rotate JWT secret key and DB password (coordinate with DBA) | Dev + DBA | 2h |
| Reduce login rate limit to 5/minute | Dev | 15min |
| Switch `workers=4` → `workers=1` (interim fix for cache inconsistency) OR implement Redis-backed cache | Dev | 1h |
| Add `require_roles` to all `/reports/` routes | Dev | 1h |

### Week 2 — Fix HIGH findings

| Task | Owner | Effort |
|------|-------|--------|
| Fix dashboard Lot P&L to include labour cost (align with `/reports/lot-pl` formula) | Dev | 2h |
| Add GST to landed cost in cost engine | Dev | 2h |
| Add soft-delete pattern to `Lot`, `Device`, `User` models (Alembic migration) | Dev | 4h |
| Add `verify_csrf` to logout route | Dev | 15min |
| Remove or gate `error.html` error detail behind `DEBUG` mode env var | Dev | 30min |

### Week 3 — Address MEDIUM findings + Architecture alignment

| Task | Owner | Effort |
|------|-------|--------|
| Add `require_roles` or consistent role guards to `dealers.py`, `admin.py` inline checks | Dev | 3h |
| Document stage transition bypass logic; add audit log entry for admin overrides | Dev | 2h |
| Set up offsite backup (copy `backups/` to network share or cloud bucket nightly) | DevOps | 3h |
| Document rollback procedure for each Alembic migration | Dev | 2h |
| Add `expected_sale_value` default formula (e.g., 60% of catalogue price) or UI prompt | Dev | 4h |

### Week 4 — Resume feature sprints

New features may proceed after Week 2 items are complete and Week 1 is fully verified.

---

## Deferred / Backlog Items

| Item | Priority | Notes |
|------|----------|-------|
| RS256 JWT (asymmetric signing) | P2 | Replace HS256; reduces breach blast radius |
| JWT revocation / session blacklist | P2 | Needed before any public deployment |
| Bounded context / schema namespacing | P3 | Long-term; not blocking now |
| Pydantic validation on form routes | P2 | Replace `str = Form(...)` + manual cast |
| CI/CD pipeline | P2 | GitHub Actions / bare-metal runner |
| Variance tracking (actuals vs. lot estimates) | P2 | CLAUDE.md "Deal Calculator" requirement |
| `.env.development` vs `.env.production` separation | P2 | Needed before staging environment |
| `install_service.bat` added to version control | P3 | Low risk, just hygiene |

---

## Comparison vs Previous Audit (2026-04-26)

| Layer | Apr-26 | Apr-28 | Change |
|-------|--------|--------|--------|
| L1 Business Process | 6.0 🟡 | 7.0 🟢 | +1.0 |
| L2 Database/Schema | 5.5 🟡 | 6.0 🟡 | +0.5 |
| L3 API/Backend | 4.0 🔴 | 4.5 🔴 | +0.5 |
| L4 UI/UX | 5.5 🟡 | 7.0 🟡 | +1.5 |
| L5 Security | 3.5 🔴 | 3.5 🔴 | ±0 |
| L6 Deployment/DevOps | 3.0 🔴 | 3.5 🔴 | +0.5 |
| L7 Financial/Reporting | 5.0 🟡 | 5.5 🟡 | +0.5 |
| **Overall** | **4.9 🔴** | **5.3 🟡** | **+0.4** |

**Progress made since Apr-26:**
- Section-level fault isolation on dashboard (no more total crash from one bad query)
- CSRF protection confirmed working across all mutating routers
- Error logging to `errors.log` + console added
- bcrypt confirmed for password hashing
- Composite DB indexes added (Sprint 18)

**Still RED / unchanged:**
- L5 Security remains unchanged — secrets still in `config.ini`; no `.env`; login rate limit unchanged
- L6 DevOps still RED — backup still local-only; multi-worker cache still an issue

---

*Next audit target: Overall ≥ 7.0 🟢 — requires completing Weeks 1–2 of the recovery sprint above.*
