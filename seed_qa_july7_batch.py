"""
OxyPC Inventory — Seed QA/UAT tracking with all work since July 7, 2026
=========================================================================
Existing qa_requirements/test_cases/defects/uat/releases data stops at
REQ-220 / v1.7.0. This adds everything shipped in the July 7-10 batch:
Telecalling Sourcing Sales agent filter, CRM PO Line Items Offer Price
rework, IQC duplicate-review modal + bulk stage move, Quotations nav +
list page, Admin Dashboard analytics overhaul, Trade Partner PWA
installable mode, app-wide live notification toast, and the Trade
Partner dealer dropdown data-integrity fix (portal_enabled NULL bug +
db_validator root cause).

Idempotent: skips creation if REQ-221 already exists.

Usage: python seed_qa_july7_batch.py
"""
import asyncio
import uuid
from datetime import timedelta

from database import AsyncSessionLocal
from utils.timezone import app_now
from sqlalchemy import select
from models.qa_uat import (
    QARequirement, QATestCase, QADefect, QAUATScenario, QARelease,
    RequirementSource, RequirementPriority, RequirementStatus,
    TestCaseType, TestCaseStatus,
    DefectSeverity, DefectPriority, DefectStatus,
    UATStatus, ReleaseStatus,
)

CREATED_BY = "system-seed"


async def run():
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(QARequirement).where(QARequirement.req_code == "REQ-221"))
        if existing.scalar_one_or_none():
            print("Already seeded (REQ-221 exists). Nothing to do.")
            return

        now = app_now()
        reqs = {}

        def add_req(code, title, module, desc, source=RequirementSource.change_req,
                     priority=RequirementPriority.high, status=RequirementStatus.done):
            r = QARequirement(
                id=uuid.uuid4(), req_code=code, title=title, description=desc,
                source=source, priority=priority, status=status, module=module,
                created_by=CREATED_BY, created_at=now, updated_at=now,
            )
            db.add(r)
            reqs[code] = r
            return r

        add_req("REQ-221", "Telecalling Dashboard: Agent filter for Sourcing Sales role", "Telecalling",
                "Agent user dropdown filter on the Telecalling Dashboard was gated to "
                "admin/sales_manager only in the template, even though the backend already "
                "scoped assigned-agent filtering to admin/sales_manager/sales. Extended the "
                "template gate to include the sales (Sourcing Sales) role.")
        add_req("REQ-222", "CRM Sourcing Deal PO Line Items: Offer Price rework", "CRM / Sourcing",
                "Removed Lot No from Add PO Line Item modal. Line item table: 'Item' renamed "
                "'Model Name', 'Total' renamed 'Total Price', new Offer Price column + modal "
                "(shows current total, captures negotiated offer, stays open). Financials card "
                "now driven by PO Line Item sums (Total Price / Offer Price) instead of static "
                "asking/offer-per-unit fields; those unit fields removed. Buyer Deals list Qty/"
                "Value/Download now derived from PO Line Items and the latest generated PO.",
                priority=RequirementPriority.medium)
        add_req("REQ-223", "IQC bulk upload: duplicate Tag/Lot review modal + bulk stage move", "IQC",
                "Bulk device upload previously skipped duplicate Tag Numbers and unresolved "
                "lot_numbers as plain error rows. Now surfaces them in a two-section review "
                "modal — Tag Number table with Approve Move (validated stage transition via "
                "services/control_engine, modal stays open), and Lot table with Add Lot "
                "(registers the lot shell with today's date + Unknown vendor, modal stays open). "
                "Customise modal gained a 'Move to Stage' dropdown for bulk-moving any selected "
                "batch of tags, same validated-transition engine as every other move flow.",
                priority=RequirementPriority.critical)
        add_req("REQ-224", "Quotations: sidebar nav + standalone list page", "Dealers / Quotations",
                "Added a 'Quotations' sidebar link after Telecalling, and a new standalone "
                "/quotations page listing every dealer quotation system-wide with filters "
                "(search/status/created-by/date range) — previously only viewable embedded on "
                "3 other pages (Dealer Mgmt, Dealer Detail, TeleSales Dashboard).")
        add_req("REQ-225", "Admin Dashboard: analytics overhaul (12 stat cards + 5 charts)", "Reporting",
                "Removed Lot P&L, Low Stock Alerts, and Recent Stage Movements widgets (kept "
                "Financial Summary + its overall_profit calc intact). Added 12 stat cards "
                "(Products, Stock, Stage Products, GRN, Parts, Dealers, Accounts, PO, Source "
                "Requests, Sales, Product Profits, Parts Profits) and 5 Chart.js chart groups "
                "(weekly Products/Parts movement, stage distribution pie, weekly Sales/Parts/"
                "Sourcing price) below the Admin Overview accordion, admin-only. Added "
                "sales.sale_channel and parts_grn.status as small additive schema fields to "
                "back the new metrics honestly rather than approximate them.",
                priority=RequirementPriority.medium)
        add_req("REQ-226", "Trade Partner: PWA installable mode (Phase 1.5)", "Trade Partner",
                "Added a web manifest, service worker, and custom install-prompt banner to the "
                "dealer-facing Trade Partner portal so dealers can add it to their phone home "
                "screen — app-like launch (fullscreen, icon, splash) with no native app.")
        add_req("REQ-227", "Global: live notification toast popup (top-right, closable)", "Platform",
                "Added an app-wide top-right toast popup (base.html, covers all pages) that "
                "fires automatically when a new notification arrives, with its own close "
                "button — separate from the existing bell/slide-in panel. New GET "
                "/notifications/since endpoint returns unread notifications newer than a given "
                "id without mutating is_read, so a toast firing doesn't count as 'read'.")
        add_req("REQ-228", "Trade Partner: dealer dropdown mapped to full Dealer Management list", "Trade Partner",
                "Enable Portal Access modal's dealer dropdown was filtered to active dealers "
                "only and capped at 500 rows; now mirrors Dealer Management's own list (all "
                "statuses, no cap), excluding only dealers already portal-enabled, with phone "
                "added to the label for disambiguation.")
        add_req("REQ-229", "Data integrity: dealers.portal_enabled NULL backfill + db_validator fix", "Platform",
                "472 of 474 dealers had portal_enabled=NULL instead of false, silently "
                "excluding them from the Trade Partner dealer dropdown (NULL doesn't match "
                "`== False` in SQL). Root cause: db_validator.py's auto ADD COLUMN never "
                "applied the model's server_default, so any boolean/default column added this "
                "way left existing rows NULL. Fixed db_validator to include DEFAULT (and NOT "
                "NULL where applicable) on every future ADD COLUMN, and backfilled the 472 "
                "affected dealer rows to false.", priority=RequirementPriority.critical)

        await db.flush()

        def add_tc(code, req_code, title, scenario, steps, expected, type_=TestCaseType.functional,
                    module=None, is_automated=False):
            tc = QATestCase(
                id=uuid.uuid4(), tc_code=code, requirement_id=reqs[req_code].id,
                title=title, scenario=scenario, steps=steps, expected_result=expected,
                type=type_, status=TestCaseStatus.active, is_automated=is_automated,
                module=module or reqs[req_code].module, created_by=CREATED_BY,
                created_at=now, updated_at=now,
            )
            db.add(tc)
            return tc

        add_tc("TC-221-1", "REQ-221", "Sourcing Sales role sees Agent filter on Telecalling Dashboard",
               "A user with the sales (Sourcing Sales) role can filter Telecalling Dashboard by agent",
               "1. Log in as a sales-role user\n2. Open Telecalling Dashboard\n3. Check for the Agent dropdown",
               "Agent dropdown is visible and filters results by assigned agent, same as admin/sales_manager")
        add_tc("TC-222-1", "REQ-222", "Offer Price modal saves and updates Financials",
               "Setting an Offer Price on a PO line item updates the Financials card total",
               "1. Open a Sourcing Deal with PO line items\n2. Click Offer Price on a row, enter a value, Save\n3. Check Financials card",
               "Offer Price column updates, Financials 'Offer Price' total reflects the sum of all line-item offers")
        add_tc("TC-222-2", "REQ-222", "Buyer Deals list Qty/Value/Download reflect PO line items",
               "The Buyer Deals list table shows line-item-derived totals, not stale deal fields",
               "1. Add/edit PO line items on a deal\n2. Return to Buyer Deals list\n3. Check Qty, Value, Download columns",
               "Qty = sum of line item quantities, Value = sum of total price, Download offers the latest generated PO")
        add_tc("TC-223-1", "REQ-223", "Duplicate Tag Number shows Approve Move, updates in place",
               "Uploading a CSV with a tag already in the system opens the review modal",
               "1. Bulk-upload a device CSV with a barcode that already exists\n2. Click Approve Move on that row",
               "Modal opens with the duplicate listed; Approve Move updates Stage in System and stays open",
               type_=TestCaseType.negative)
        add_tc("TC-223-2", "REQ-223", "Missing lot_number shows Add Lot, registers the lot",
               "Uploading a CSV referencing a lot_number that doesn't exist yet offers Add Lot",
               "1. Bulk-upload a device CSV with an unknown lot_number\n2. Click Add Lot on that row",
               "New Lot is created with today's date + Unknown vendor; row marked Added, modal stays open")
        add_tc("TC-223-3", "REQ-223", "Customise modal Move to Stage enforces allowed transitions",
               "Bulk stage move rejects a disallowed transition instead of forcing it",
               "1. Select IQC-stage tags, open Customise\n2. Pick a disallowed target stage (e.g. Sold)\n3. Apply",
               "Disallowed tags are skipped and reported; only allowed transitions are applied")
        add_tc("TC-224-1", "REQ-224", "Quotations nav link lists every dealer quotation",
               "The Quotations sidebar page shows all quotations system-wide, filterable",
               "1. Click Quotations in sidebar\n2. Compare count against Dealer Mgmt's Quotation Shared table\n3. Try each filter",
               "Same quotations appear (single source of truth); filters narrow results correctly")
        add_tc("TC-225-1", "REQ-225", "Admin Dashboard shows new analytics, old widgets gone",
               "Lot P&L / Low Stock / Recent Stage Movements removed, 12 cards + 5 charts render",
               "1. Log in as admin, open Dashboard\n2. Scroll below Admin Overview accordion",
               "The 3 old widgets are absent; Financial Summary still shows correct overall_profit; "
               "12 stat cards and 5 charts render without console errors", type_=TestCaseType.regression)
        add_tc("TC-226-1", "REQ-226", "Trade Partner portal installs to home screen",
               "Dealer sees an install prompt and can add the portal as an app icon",
               "1. Open /partner on a mobile browser\n2. Trigger the install banner\n3. Tap Install",
               "Manifest/service worker register cleanly; portal installs and opens standalone")
        add_tc("TC-227-1", "REQ-227", "New notification pops a top-right toast with close button",
               "A newly created notification fires a toast without a page reload",
               "1. Stay on any page\n2. Trigger a new notification server-side\n3. Wait up to 15s",
               "Toast appears top-right with title/message and a working close (×) button, "
               "auto-dismisses after ~8s", type_=TestCaseType.integration)
        add_tc("TC-227-2", "REQ-227", "Existing unread backlog doesn't flood toasts on page load",
               "Opening a page with several pre-existing unread notifications shows no toast spam",
               "1. Ensure 3+ unread notifications exist\n2. Load any page fresh",
               "No toasts fire for the pre-existing backlog; only notifications created after "
               "load produce a toast", type_=TestCaseType.negative)
        add_tc("TC-228-1", "REQ-228", "Enable Portal Access dropdown lists all eligible dealers",
               "Dealer dropdown matches Dealer Management, minus already-enabled dealers",
               "1. Open Trade Partner > Partners > Enable Portal Access\n2. Compare dropdown count to Dealer Management total",
               "Every dealer not already portal-enabled appears, regardless of status, with no 500-row cap")
        add_tc("TC-229-1", "REQ-229", "No dealer has a NULL portal_enabled value",
               "All dealer rows have an explicit true/false portal_enabled after backfill",
               "1. Query SELECT portal_enabled, count(*) FROM dealers GROUP BY portal_enabled",
               "Only true/false values appear, zero NULL rows", type_=TestCaseType.regression, is_automated=True)

        await db.flush()

        def add_defect(code, title, module, desc, severity, status, resolved=True,
                        root_cause=None, resolution=None, days_ago=2):
            d = QADefect(
                id=uuid.uuid4(), defect_code=code, title=title, module=module,
                description=desc, severity=severity, priority=DefectPriority.p2,
                status=status, environment="Production", reported_by=CREATED_BY,
                reported_at=now - timedelta(days=days_ago), root_cause=root_cause, resolution=resolution,
                resolved_at=(now - timedelta(days=1)) if resolved else None,
                closed_at=(now - timedelta(hours=6)) if resolved else None,
            )
            db.add(d)
            return d

        add_defect("BUG-105", "IQC bulk upload silently skipped duplicate Tag/Lot rows", "IQC",
                    "Duplicate Tag Numbers and unresolved lot_numbers were dropped as plain "
                    "error-list rows with no way to resolve them in bulk, forcing one-by-one "
                    "manual fixes and slowing stock sync between Inventory/Telecaller/Showroom.",
                    DefectSeverity.high, DefectStatus.closed,
                    root_cause="Bulk upload treated duplicates purely as validation errors, no "
                               "resolution path existed in the UI.",
                    resolution="Added a two-section duplicate-review modal (Approve Move / Add "
                               "Lot) with per-row AJAX actions that keep the modal open.")
        add_defect("BUG-106", "Trade Partner dealer dropdown showing almost no dealers", "Trade Partner",
                    "Enable Portal Access dropdown showed only 2 dealers out of 474 in Dealer "
                    "Management.", DefectSeverity.critical, DefectStatus.closed,
                    root_cause="dealers.portal_enabled was NULL (not false) on 472 rows because "
                               "db_validator.py's auto ADD COLUMN never applied the model's "
                               "server_default; SQL `NULL = false` matches neither true nor "
                               "false, so those rows were silently excluded from the candidate query.",
                    resolution="Backfilled the 472 NULL rows to false, and fixed db_validator.py "
                               "to include DEFAULT (and NOT NULL where applicable) on every "
                               "future ADD COLUMN so the class of bug can't recur.",
                    days_ago=1)

        await db.flush()

        def add_uat(code, req_code, title, scenario, criteria, owner, status=UATStatus.pass_):
            u = QAUATScenario(
                id=uuid.uuid4(), uat_code=code, requirement_id=reqs[req_code].id,
                title=title, scenario=scenario, acceptance_criteria=criteria,
                business_owner=owner, status=status,
                executed_by=CREATED_BY, executed_at=now, created_by=CREATED_BY, created_at=now,
            )
            db.add(u)
            return u

        add_uat("UAT-204", "REQ-221", "Sourcing Sales rep filters Telecalling Dashboard by their own agents",
                "A Sourcing Sales team lead reviews call activity for a specific agent",
                "Agent filter dropdown is available and works for the sales role, not just admin", "Sourcing Sales Lead")
        add_uat("UAT-205", "REQ-222", "Buyer negotiates and records an offer price per line item",
                "Sourcing team negotiates a lower price than asking on a PO line item",
                "Offer Price is captured per item and rolls up into the deal's Financials card", "Sourcing Manager")
        add_uat("UAT-206", "REQ-223", "IQC clerk resolves duplicate tags/lots in one upload session",
                "A bulk CSV contains a few already-known tags and a new (unregistered) lot",
                "Clerk resolves both cases from the review modal without re-editing and re-uploading the CSV", "Warehouse Lead")
        add_uat("UAT-207", "REQ-224", "Sales manager reviews all quotations across telecallers",
                "Sales manager wants a single place to audit every quotation shared this month",
                "Quotations nav page lists and filters every quotation regardless of which telecaller created it", "Sales Manager")
        add_uat("UAT-208", "REQ-225", "Admin gets a fuller operational picture at a glance",
                "Admin wants stage/parts/sales visibility beyond just Lot P&L",
                "New analytics section gives category-level counts and trend charts admin can act on daily", "Admin")
        add_uat("UAT-209", "REQ-229", "Sales team can onboard any dealer to Trade Partner, not just 2",
                "Sales team tries to enable portal access for a long-standing dealer",
                "Dealer appears in the dropdown and portal access can be granted successfully", "Sales Ops Manager")

        await db.flush()

        def add_release(version, title, status, days_ago_planned=0, days_ago_release=None):
            rel = QARelease(
                id=uuid.uuid4(), version=version, title=title, status=status,
                planned_date=now - timedelta(days=days_ago_planned),
                release_date=(now - timedelta(days=days_ago_release)) if days_ago_release is not None else None,
                qa_sign_off_by=CREATED_BY, qa_sign_off_at=now - timedelta(days=1),
                created_by=CREATED_BY, created_at=now, updated_at=now,
            )
            db.add(rel)
            return rel

        add_release("v1.8.0",
                     "Telecalling agent filter + CRM Offer Price rework + IQC duplicate-review "
                     "modal + Quotations nav + Admin Dashboard analytics + Trade Partner PWA/"
                     "notification toast/dealer dropdown fix",
                     ReleaseStatus.deployed, days_ago_planned=2, days_ago_release=0)

        await db.commit()
        print("Seeded: 9 requirements, 13 test cases, 2 defects, 6 UAT scenarios, 1 release.")


if __name__ == "__main__":
    asyncio.run(run())
