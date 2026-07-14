# Repair-Flow Redesign, IQC Rework & Cross-Page Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This project's actual verification pattern (established across 80+ prior batches — see TaskList) is: `python -m py_compile` on touched files, a TestClient-based smoke script per batch (impersonate the relevant role via `app.dependency_overrides[get_current_user]`), then `python _scan_routes.py` to confirm no regression against the current 228-route/9-flag baseline. This project does not use pytest-style unit tests — do not invent them; follow the established pattern instead (writing-plans skill explicitly allows deviating from generic TDD to match an existing codebase's pattern).

**Goal:** Redesign the L1/L2 → L3/L4 → Stress Test → Cosmetic repair pipeline into an explicit status-driven hand-off flow with WorkID-based reassignment, rework the IQC Entry page's field set and Agent auto-fill format, and clean up table/button clutter across Inventory Manager, Production Manager, GRN, and Cosmetic pages.

**Architecture:** Existing `WorkOrder` model already carries a `work_id` per device-at-a-stage (see `routers/repair.py:215`); this plan adds new status columns to `Device`/`WorkOrder` rather than new tables (mirrors how `final_qc_status` was already added directly to `Device`), and adds a small number of new join-style tables only where genuinely new data needs to persist (`ScrapRecord`, `BucketAllocation` sub-tables, `PricingVisibility` role flag). Scan/autocheck tag-number inputs are a single reusable JS snippet (`static/js/tag-scan-autocheck.js`) wired into 3 pages rather than 3 bespoke implementations.

**Tech Stack:** FastAPI + Jinja2 + async SQLAlchemy + PostgreSQL (existing stack, no new dependencies except confirming `python-multipart`/existing agent-side OCR/WMI libs already present for the Windows Agent).

---

## Batch 0 — Clarifications (RESOLVED 2026-07-14)

1. **"Fan Sound" removal** — confirmed: remove from form AND stop the Agent capturing/writing it.
2. **RAM/HDD auto-fill format** — confirmed: add new `Device.ram_summary` / `Device.hdd_summary` string columns; old numeric columns stay in DB untouched, just no longer written by this form/Agent path.
3. **L1/L2 → L3/L4 dual-WorkID** — confirmed: one device can have two simultaneously open WorkOrders. Auto-generated WorkID prefix is **`L1L2-`** for L1/L2 repair page work orders and **`L3L4-`** for L3/L4 repair page work orders (replaces whatever generic prefix the existing WorkID generator uses for these two stages — Batch 10/11 must locate and parametrize that generator rather than hardcoding one prefix globally).
4. **Mac Agent** — root cause lead confirmed by user: **the macOS launcher is a `.command` file, and it no longer runs, though an older `.command` file used to work.** This is a launcher-script regression, not a missing hardware-detection path. Batch 1 now investigates the `.command` file directly (diff against last-known-working version / check for macOS Gatekeeper quarantine attribute / shebang or path assumptions that broke) instead of waiting on a stack trace.

---

## Batch 1 — Mac Agent `.command` launcher fix

1. **Locate the `.command` file** in `oxyqc-standalone/agent` (or its dist/packaging folder — check `oxyqc-standalone/agent/dist` per this session's working-directory list). Read it in full.
2. **Check git history for the file** (`git log --follow -p -- <path-to>.command`) to diff the current version against the last-known-working one the user references — look specifically for: a changed shebang line, a hardcoded Windows-style path, a reference to a binary/script that got renamed/moved in a recent restructure, or a missing `chmod +x` step in how it's distributed (a `.command` file that arrives without the executable bit — e.g. re-zipped, re-uploaded via a channel that strips permissions — is the single most common cause of "used to work, now doesn't" on macOS).
3. **Check for macOS Gatekeeper quarantine** (`xattr -l` on the file, or ask the user to run `xattr -d com.apple.quarantine <file>.command` as a quick test) — a `.command` file downloaded fresh via browser/email/Slack gets a quarantine attribute that blocks execution with a silent-looking failure ("cannot be opened") unless the user right-clicks → Open the first time. This is a strong candidate if the file itself hasn't changed but the *distribution channel* changed.
4. **Ask the user to run the `.command` file from Terminal directly** (`bash /path/to/file.command` or `sh /path/to/file.command`) rather than double-clicking, and paste whatever output/error appears — this surfaces the real error even if double-click fails silently, and doesn't require guessing further.
5. **Fix based on findings**: most likely one-line fix (correct shebang, fix a path, add an explicit `chmod +x` step to whatever packages/exports the `.command` file) — implement once the actual cause from steps 2-4 is known, don't speculate further in this plan.
6. **Verify:** confirm with the user that the fixed `.command` file runs on their Mac before considering this batch closed — this is the one verification step in the whole plan that cannot be TestClient/py_compile-checked, since it's platform-specific to macOS.

---

## Batch 2 — IQC Entry page field rework (schema + form)

**Files:**
- Modify: `models/device.py` (add `ram_summary`, `hdd_summary` columns near existing `ram_gb`/`hdd_capacity_gb` block, lines ~101-109)
- Modify: `templates/iqc/form.html` (remove/rename fields, make all fields editable)
- Modify: `routers/iqc.py` (accept new field names on submit)
- Modify: OxyQC Agent detection payload mapping (wherever it posts field values matching `templates/iqc/form.html` input `name` attributes — find via `Grep "ram_type\|fan_sound_dba" oxyqc-standalone/agent`)

2. **Add `ram_summary` / `hdd_summary` columns to `Device`.**

```python
# models/device.py — insert directly after the existing ram_gb/hdd_capacity_gb block (after line 109)
ram_summary = Column(String(255), nullable=True)   # e.g. "16GB_DDR4_2300MHz_Samsung, 8GB_DDR4_2133MHz_Crucial"
hdd_summary = Column(String(255), nullable=True)    # e.g. "520GB_SSD_5400RPM_Samsung, 1TB_SSD_7200RPM_Seagate"
```

Confirm this project's additive-column auto-provision (referenced in `docs/schema.dbml` MCS rule and prior batches' migration pattern — check `db_validator.py` for the `ADD COLUMN ... DEFAULT` pattern fixed in run #113) picks this up without a manual Alembic step; if the project uses a `db_validator.py` startup auto-migration, no Alembic file is needed — confirm by reading `db_validator.py`'s column-diffing logic before assuming.

3. **Remove fields from `templates/iqc/form.html`:** Fan Sound (line ~378-379), RAM Type (line ~183-184), RAM Speed, RAM Make, HDD (as a labeled block), Capacity (HDD), HDD Type, HDD Speed, Storage Type. Read the full file first (`Read templates/iqc/form.html`) to find exact line ranges for each — the RAM block (~180-200) and a likely-adjacent HDD block are template patterns to match structurally when replacing.

4. **Rename "Storage Capacity" (line ~217) to "Hard Drive"** and make its underlying input bind to the new `hdd_summary` string field instead of the old numeric `storage_gb`. Add a single new "RAM" field bound to `ram_summary`, replacing the removed RAM Type/Speed/Make/size inputs.

5. **Make all remaining `readonly`-attributed inputs in this form editable.** `Grep -n "readonly" templates/iqc/form.html` to enumerate every occurrence, then remove the `readonly` attribute from each (verify none of them are `disabled` computed fields critical to a validation invariant — if any readonly field is a computed total, confirm with user before making it freely editable, since a wrong manual edit could desync a derived value).

6. **Update `routers/iqc.py`'s submit handler** to accept `ram_summary: str = Form(None)` and `hdd_summary: str = Form(None)` instead of the removed individual fields, and stop reading `fan_sound_dba`, `ram_type`, `ram_speed`, `ram_make`, `hdd_type`, `hdd_speed`, `storage_type` from the form (leave the columns in the model/DB for historical rows — do not delete columns, only stop writing them from this form per the additive-only DB discipline in CLAUDE.md).

7. **Verify:** `python -m py_compile models/device.py routers/iqc.py`, then a TestClient POST to the IQC submit endpoint with the new field names as an admin user, confirm 200/redirect and that the created `Device` row has `ram_summary`/`hdd_summary` populated and old fields null. Run `python _scan_routes.py` to confirm no regression.

---

## Batch 3 — Agent RAM/HDD detection + auto-fill format

**Files:**
- Modify: OxyQC Agent's hardware-detection module (find via `Grep -rn "ram_gb\|storage_gb" oxyqc-standalone/agent --include=*.py`) — the module that currently detects individual RAM/HDD specs and posts them to the IQC form fields.

8. **Locate the Agent's existing RAM/disk enumeration code.** Per `oxyqc_ui_design.md` memory, hardware detection already exists (WMI-based) and previously fed `ram_gb`, `ram_type`, etc. individually. Read that module fully before changing it.

9. **Add a formatting function producing the packed string per stick/drive:**

```python
# In the Agent's hardware-detection module, alongside existing per-stick RAM enumeration
def format_ram_summary(sticks):
    """sticks: list of dicts with keys size_gb, mem_type, speed_mhz, make"""
    parts = []
    for s in sticks:
        parts.append(f"{s['size_gb']}GB_{s['mem_type']}_{s['speed_mhz']}MHz_{s['make']}")
    return ", ".join(parts)

def format_hdd_summary(drives):
    """drives: list of dicts with keys size, unit ('GB'/'TB'), drive_type ('SSD'/'HDD'), rpm, make"""
    parts = []
    for d in drives:
        parts.append(f"{d['size']}{d['unit']}_{d['drive_type']}_{d['rpm']}RPM_{d['make']}")
    return ", ".join(parts)
```

10. **Wire these into the Agent's existing payload-posting call**, replacing whatever currently sets the individual `ram_type`/`ram_speed`/`ram_make`/`hdd_type`/`hdd_speed` form fields with a single `ram_summary`/`hdd_summary` key matching Batch 2's new form field names.

11. **Verify:** Run the Agent against a real test machine (or the Agent's existing mock/dev mode if one exists — check for a `--dry-run` or sample-payload mode), confirm the posted payload's `ram_summary`/`hdd_summary` strings match the exact format examples in the spec (`16GB_DDR4_2300MHz_Samsung`), including the multi-stick comma-space join.

---

## Batch 4 — Tag-number scan/autocheck component (shared, used 3x)

**Files:**
- Create: `static/js/tag-scan-autocheck.js`
- Modify: `templates/iqc/... ` (wherever the IQC "Tag Number table" lives — likely a separate list/lookup view, not `form.html` itself; locate via Grep `"Tag Number"` across `templates/iqc/`)
- Modify: `templates/grn/*.html` (TRC GRN page's Tag Number table)
- Modify: `templates/inventory/*.html` or `stock_in.html` (Inventory Manager's Inventory Stock table)

12. **Build one reusable JS module** rather than three copies (DRY per plan discipline):

```javascript
// static/js/tag-scan-autocheck.js
// Attaches a scan/type multi-tag input to a table of checkboxes.
// Usage: initTagScanAutocheck({ inputId, tableSelector, rowTagAttr, countSelector })
function initTagScanAutocheck({ inputId, tableSelector, rowTagAttr = 'data-tag', countSelector }) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const table = document.querySelector(tableSelector);

  function applyTags() {
    const tags = input.value.split(',').map(t => t.trim().toUpperCase()).filter(Boolean);
    const tagSet = new Set(tags);
    let checkedCount = 0;
    table.querySelectorAll(`tr[${rowTagAttr}]`).forEach(row => {
      const tag = row.getAttribute(rowTagAttr).toUpperCase();
      const cb = row.querySelector('input[type="checkbox"]');
      if (!cb) return;
      if (tagSet.has(tag)) {
        cb.checked = true;
        checkedCount++;
      }
    });
    if (countSelector) {
      const countEl = document.querySelector(countSelector);
      if (countEl) countEl.textContent = document.querySelectorAll(`${tableSelector} input[type="checkbox"]:checked`).length;
    }
  }

  input.addEventListener('input', applyTags);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); applyTags(); }
  });
  // Keep the live count in sync with manual row-checkbox clicks too
  if (countSelector) {
    table.addEventListener('change', (e) => {
      if (e.target.matches('input[type="checkbox"]')) {
        const countEl = document.querySelector(countSelector);
        if (countEl) countEl.textContent = document.querySelectorAll(`${tableSelector} input[type="checkbox"]:checked`).length;
      }
    });
  }
}
```

13. **Wire into IQC's Tag Number table** — add `<input id="iqc-tag-scan" placeholder="Scan or type tag numbers, comma separated">` above the table, ensure each `<tr>` already has (or add) `data-tag="{{ device.tag_number }}"`, call `initTagScanAutocheck({ inputId: 'iqc-tag-scan', tableSelector: '#iqc-tag-table', countSelector: '#iqc-selected-count' })` in a page-bottom `<script>` block.

14. **Wire into GRN TRC page's Tag Number table** the same way (`inputId: 'grn-tag-scan'`).

15. **Wire into Inventory Manager's Inventory Stock table** the same way, with `countSelector` pointed at the existing "Assign Bucket" button's count badge — read the current Assign Bucket button markup first (likely already has a count span from Batch "Inventory Manager: bucket count from selection", task #51 in TaskList) and reuse that same span ID as `countSelector` so the two selection mechanisms (manual checkbox + scan) update the same counter.

16. **Verify:** manual browser walk-through (gstack `/qa` or Browser pane) on all 3 pages — type a comma-separated list of 2-3 real tag numbers from a dev-seeded device, confirm matching rows auto-check and the count updates; also manually click a row checkbox and confirm the count still updates (regression check on task #51's existing behavior).

---

## Batch 5 — Global "Back" button

**Files:**
- Modify: `templates/base.html` (shared layout — add once, applies everywhere)

17. **Add a reusable Back button to the shared page-header include** in `templates/base.html` (find the common header/breadcrumb block already established from Batch A, task #17 — "breadcrumb" fix). Insert:

```html
<button type="button" class="btn btn-primary btn-sm" onclick="history.back()">
  <i class="bi bi-arrow-left"></i> Back
</button>
```

placed next to (not replacing) the existing breadcrumb, so it appears on every page inheriting `base.html`. Use `history.back()` (client-side) rather than a server-rendered "previous page" URL — simpler, always correct for the browser's actual navigation history, no per-route wiring needed.

18. **Verify:** load 3-4 different pages, click Back, confirm it returns to the prior page in each case; confirm it doesn't appear twice on pages that already have a manual "Back" link (Grep `>Back<` across templates first to find and remove any now-redundant existing ones).

---

## Batch 6 — GRN TRC: remove duplicate invoice-file validation

**Files:**
- Modify: `routers/stock.py` (GRN creation endpoint — 1592 lines, locate via `Grep -n "duplicate\|invoice" routers/stock.py`)

19. **Find and remove the file-hash/duplicate-invoice check** in the GRN creation flow. Read the matched lines first to confirm this is a content-hash or filename check (not a legitimate "duplicate GRN record" business-logic guard) before removing — the spec explicitly wants the *same file* uploadable multiple times to create multiple GRNs, so only the file-level duplicate-rejection logic should go, not GRN creation itself.

20. **Verify:** TestClient POST the same invoice file twice through GRN creation as admin, confirm both succeed and create 2 distinct GRN records.

---

## Batch 7 — Inventory Manager / Production Manager table cleanup

**Files:**
- Modify: `templates/stock/inventory_manager.html` (or equivalent — locate via Grep `"Cost & Parts\|Costs & Parts\|Movement"` across `templates/stock/` and `templates/repair/`)
- Modify: `routers/stock.py` (remove now-unused query blocks feeding removed tables)

21. **Remove "Cost & Parts" table** from both Inventory Manager and Production Manager pages (per spec, appears on both).

22. **Remove "Movement" table** from Inventory Manager page (Bucket/Carton table's "Move to Production" flow stays — only the separate Movement table goes).

23. **Rename "Devices in Production"** — Production Manager's first table, remove its "Assign Stock" button from the Action column.

24. **Verify:** Read each modified template's full table-rendering block before deleting, confirm no other page includes the same Jinja macro/partial (if these tables are shared partials, e.g. `_movement_table.html`, deleting the file breaks other includes — check `grep -rn "movement_table\|cost_parts_table" templates/` before removing any shared partial file, only remove the block on these two pages if it's page-specific markup).

---

## Batch 8 — New allocation/repair-line tables + wiring

**Files:**
- Modify: `models/device.py` or new `models/repair.py` (add `ScrapRecord` model if not present — check `models/` directory first)
- Modify: `routers/stock.py` (Bucket Allocation "Assign Bucket" modal submit handler)
- Modify: `routers/repair.py` (bucket-to-L1/L2 allocation tracking)
- Modify: Production Manager + Inventory Manager templates (new tables)

25. **Add "Tag Numbers in Repair Line" table to Production Manager** — a read-only query of all devices currently in `DeviceStage` values corresponding to L1/L2/L3/L4 repair stages (check `models/device.py`'s `DeviceStage` enum for the exact repair-stage names first).

26. **Add "Scrap Products from Repair Line" table to Production Manager**, with Action column buttons "Move to Inventory" and "Replace With Another" — backed by the `ScrapRecord`/scrap-status devices added in Batch 10 (L3/L4 Scrap flow). Sequence this after Batch 10 since it depends on scrap records existing.

27. **Wire "Assign Bucket" modal submit** (Inventory Manager's Bucket Allocation table) to also insert a row into a new "Allocation - Buckets in L1/L2 Repair" table at the Production Manager page — this requires either a new lightweight `BucketAllocation` model (bucket_id, target_stage, assigned_at) or reusing the existing bucket-assignment write path and adding a second query on Production Manager filtering by `target_stage='l1_l2'`. Prefer the query-filter approach (no new table) if the existing bucket-assignment record already stores enough fields — read the current `/buckets/{id}/assign` handler in `routers/stock.py` first to check.

28. **Wire Inventory Manager's Bucket/Carton "Move to Production" click** to similarly populate an "Allocation - Buckets in production" table at the Inventory Manager page — same pattern as #27.

29. **Verify:** TestClient — assign a bucket, confirm it now appears in both the original table and the new allocation table; move a bucket to production, confirm the same for the production-side table. Run `_scan_routes.py`.

---

## Batch 9 — Master Data: Pricing Visibility RBAC tab

**Files:**
- Modify: `routers/admin.py` (Master Data configuration router — find via existing Module Permission matrix pattern, likely same file/pattern as the existing RBAC matrix)
- Modify: `templates/admin/master_data.html` (or wherever the Master Data config tabs live)
- Modify: `models/` — new `PricingVisibility` model (role → enabled boolean), OR a new column set on the existing role/permission table if one already models per-role feature flags (check `models/` for an existing `ModulePermission`-style table first — reuse its pattern rather than inventing a new one)

30. **Add a `PricingVisibility` table** (or extend the existing Module Permission matrix table with a `feature='pricing'` row per role, if that table is generic enough — read its schema first) storing one boolean per built-in + custom role.

31. **Add "Pricing Visibility" tab to Master Data configuration page**, listing all roles with an enable/disable toggle, following the exact UI pattern of the existing Module Permission matrix tab (reuse its table/toggle markup).

32. **Add a shared template helper / context processor** exposing `can_view_pricing(current_user)` to all templates (check `main.py` for the existing Jinja global-function registration pattern used for other RBAC checks, e.g. `require_module_perm`), then gate every existing pricing column/field across the app behind it. This is the largest fan-out change in this batch — enumerate every pricing display point first via `Grep -rn "unit_price\|selling_price\|Pricing" templates/ | grep -v node_modules` and wrap each with `{% if can_view_pricing(current_user) %}`.

33. **Verify:** create a test role with pricing disabled, TestClient-impersonate it, confirm pricing columns are absent from at least 3 representative pages (Ready to Sale, Final QC, Device Detail); re-enable, confirm they reappear.

---

## Batch 10 — L1/L2 Repair page rework

**Files:**
- Modify: `routers/repair.py` (692 lines — start/complete endpoints at lines 264/336, new endpoints for Request-to-L3/L4 and Scrap)
- Modify: `templates/repair/l1.html`, `templates/repair/l2.html` (134/132 lines each)
- Modify: `models/device.py` or a `WorkOrder` model file (add `l1l2_status`, `l3l4_status` fields if not present — check whether `WorkOrder` already has a generic `status` column via `Read routers/repair.py` around line 215's `work_id` usage first)

34. **Read `routers/repair.py` in full** before touching it — 692 lines with existing `/start`, `/complete`, `/move` endpoints and an existing WorkID-carry-forward pattern (line ~476 comment: "Carry the same WorkID to the next level"). The new "Request to L3/L4 creates a NEW WorkID while L1/L2 stays open" behavior is the opposite of this existing carry-forward pattern for the *within-repair* hand-off — confirm with user (Batch 0, item 3) before implementing, since it changes an established convention.

35. **Add `Device.l1l2_status` and `Device.l3l4_status` string columns** (default "New" / null) if no equivalent exists on `WorkOrder` already.

36. **Rework `templates/repair/l1.html` / `l2.html`:** remove the right-side "Complete Job" panel, expand table to full width (change the Bootstrap grid classes, e.g. `col-md-8` → `col-12`). Add "Status" column right after "Tag Number", add "L3/L4 Status" column (blank by default). Action column shows only "Request Part" + "Request to L3/L4" by default.

37. **Add `POST /repair/request-l3l4` endpoint** in `routers/repair.py`: accepts `device_id`, `assigned_l3l4_username`; sets `Device.l1l2_status = "Requested to L3/L4"`; creates a new `WorkOrder` row with `stage` set to the L3/L4 stage, `assigned_username = assigned_l3l4_username`, and a new auto-generated `work_id` (reuse the existing WorkID-generation helper already used elsewhere in this file); does NOT close the existing L1/L2 `WorkOrder`.

38. **Add the "Request to L3/L4" modal** to `l1.html`/`l2.html`: a Bootstrap modal with a `<select>` populated from `/api/users?role=l3l4_engineer` (or however other assignment dropdowns in this codebase are already populated — reuse that existing endpoint/pattern, e.g. check how Stress Test's engineer-assignment dropdowns are built if they exist, or the Bucket assign-to-engineer modal) and an "Assign" button posting to the new endpoint.

39. **Wire "Start Repair"** (existing button) to set `Device.l1l2_status = "Repair Started"` and reveal a "Complete" button in the Action column (client-side toggle based on status, or server-rendered conditional based on `device.l1l2_status`).

40. **Add "Complete" modal**: select Stress Test engineer from dropdown, "Assign" button → `POST /repair/l1l2-complete-to-stress` sets the device's stage to Stress Test, assigns to the selected engineer, and the row disappears from L1/L2 (moves to the Stress Test table per existing stage-based table filtering).

41. **Add conditional Action-column rendering**: if `Device.l3l4_status` is one of `("Normal Scrap", "Replacement Scrap")`, show only a single "Back to Production" button; clicking it moves the row into the "Scrap Products from Repair Line" table (Batch 8, item 26) — implement as a stage/status change plus the existing `_scan_routes.py`-verified move pattern used elsewhere in this router (`/move` endpoint at line 659 is likely the reusable primitive here — read it first).

42. **Verify:** TestClient walk the full flow as an L1/L2-role fake user: Start Repair → status updates → Complete → modal assign → device appears in Stress Test's device list. Separately: Request to L3/L4 → confirm a second WorkOrder exists with a different `work_id` while the original L1/L2 WorkOrder is still open (per Batch 0 confirmation).

---

## Batch 11 — L3/L4 Repair page rework

**Files:**
- Modify: `routers/repair.py` (new endpoints alongside Batch 10's)
- Modify: `templates/repair/l3.html` (and l4 if a separate template exists — check for `l4.html`; if only `l3.html` handles both via a `level` param, follow that existing pattern)

43. **Rework `templates/repair/l3.html`:** remove right-side Complete Job panel, full-width table. New columns: WorkID, Tag Number, Status (default "New"), Bucket, Notes (L1/L2 engineer's full name — pull from the parent WorkOrder's `assigned_username` via the `parent_work_id` FK from Batch 10, item 37), Aging, Action. Default only "Start Repair" visible.

44. **"Start Repair"** → `Device.l3l4_status = "Repair Started"`, reveals "Complete" + "Scrap" buttons.

45. **"Complete"** → `Device.l3l4_status = "Completed"` in this table AND writes `"Completed"` into `Device.l3l4_status` as read by the L1/L2 table for the same device (same column — since both pages read/write the same `Device.l3l4_status` field per Batch 10 item 35, this is automatically consistent; no extra sync code needed as long as both pages query the same column).

46. **"Scrap"** → modal with a radio choice (Normal Scrap / Replacement Scrap); on submit, sets `Device.l3l4_status` to the selected label — same column, so the L1/L2 table's conditional "Back to Production" button (Batch 10, item 41) picks it up automatically.

47. **Verify:** TestClient — Start Repair → Complete on an L3/L4-assigned device, confirm `Device.l3l4_status` reads "Completed" when queried from both the L3/L4 endpoint and the L1/L2 list endpoint (same underlying column, so this is really confirming both routers' queries reference `Device.l3l4_status` and not two different fields).

---

## Batch 12 — Stress Test page button rework

**Files:**
- Modify: `templates/qc/list.html` (424 lines)
- Modify: `routers/stress_api.py` (413 lines) or `routers/qc.py` (273 lines) — locate the existing "Go Cleaning"/"Verify QC" handlers first (Grep `"Go Cleaning\|Verify QC\|send-to-cosmetic"` across both routers)

48. **Rename "Go Cleaning" → "Complete"; replace "Verify QC" → "Fail".** Read the existing button/endpoint wiring first (this session's earlier work already touched a "Go Cleaning" 403 per the completed cosmic-herding-clover Batch 1 item — confirm that fix is in place before renaming so the rename doesn't resurrect the old bug under a new label).

49. **"Fail" button → modal**: select L1/L2 engineer + notes field, "Assign" → moves the device to that engineer's L1/L2 Repair page table (sets stage + `assigned_username`, mirrors Batch 10's assignment pattern).

50. **"Complete" button → modal**: select Paint engineer + notes, "Assign" → moves device to that engineer's Stages (Cleaning) page (existing Cosmetic pipeline's "cleaning" stage — reuse `routers/cosmetic.py`'s existing stage-assignment primitive, read `advance_stage()` at line 208 first).

51. **Verify:** TestClient both flows, confirm device lands in the correct destination table for the correct assigned user.

---

## Batch 13 — Final QC + Cosmetic Stages page cleanup

**Files:**
- Modify: `templates/cosmetic/final_qc.html` (246 lines)
- Modify: `templates/cosmetic/stage.html` (224 lines)

52. **Remove cosmetic pipeline nav buttons from Final QC page** — read `templates/cosmetic/final_qc.html` in full first; this likely mirrors the "remove Final QC button from cosmetic stage nav" item already done in a prior batch (cosmic-herding-clover Batch 3, item 16) — confirm that's not already removed before duplicating effort, and remove the reverse-direction buttons (links back into cleaning/sanding/etc. stages) from the Final QC page itself.

53. **Remove right-side "Scan to Advance" section from `templates/cosmetic/stage.html`**, scale the main table to full width (same Bootstrap grid-class change pattern as Batch 10/11's Complete Job panel removal).

54. **Verify:** browser walk-through both pages, confirm full-width table renders correctly and no broken references to the removed scan-to-advance JS (check `stage.html`'s `<script>` block for now-orphaned event listeners referencing removed DOM elements).

---

## Batch 14 — Sidebar reorder

**Files:**
- Modify: `templates/base.html` (sidebar nav block)

55. **Move "Transfer in Stages" nav item to immediately after "Transfer in Floors"** — a straightforward reorder of two `<li>`/nav-link blocks in the existing sidebar markup (Batch A / task #17 and the cosmic-herding-clover Batch 8 item 34 already did related nav regrouping — read the current state of the sidebar block first rather than assuming its pre-refactor structure).

56. **Verify:** browser screenshot of sidebar, confirm order.

---

## Cross-batch verification (run once, after all batches land)

- `python -m py_compile` across every touched `.py` file.
- Full `python _scan_routes.py` regression sweep — confirm the 228-route baseline holds or grows only by intentionally-added routes, and the 9-flag baseline is unchanged (no new unexplained flags).
- Update `docs/schema.dbml` for every new column/table added in Batches 2, 8, 9, 10 (MCS System-1 rule from CLAUDE.md).
- Manual browser walk-through (gstack `/qa`) of the full L1/L2 → L3/L4 → Stress Test → Cosmetic happy path end-to-end, plus the Scrap branch, since this is the highest-risk multi-page state-machine change in the batch.
- Per this project's `commit-deploy-gate` skill: stop after each batch, summarize exact files changed, wait for explicit go-ahead before commit/push/restart.

---

## Self-review notes (spec coverage check)

- All ~40 numbered spec bullets from the user's message map to a task above except the Mac Agent error (Batch 1, correctly left as BLOCKED pending real error text — cannot be fixed blind).
- Three ambiguities (RAM/HDD schema shape, L1/L2→L3/L4 dual-WorkID semantics, "Fan Sound" full removal scope) are flagged in Batch 0 for explicit confirmation rather than silently guessed, since guessing wrong here cascades into rework across Batches 2-3 and 10-11.
- No placeholder steps — every step above either names the exact file/function to read first (when the codebase's current shape isn't yet confirmed from this session's exploration) or gives literal code.
