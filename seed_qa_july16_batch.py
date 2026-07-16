"""
OxyPC Inventory — Seed QA/UAT tracking with all work from July 13-16, 2026
=========================================================================
Existing qa_requirements/test_cases/defects/uat/releases data stops at
REQ-239 / v1.9.0 (July 10 backfill). This captures every batch shipped in
the last 6 days (July 13-16): the Customer Care Agent (Phases 1-6), the
systemic RBAC 403 remediation, the L1/L2<->L3/L4 repair hand-off rework +
Stress Test Complete/Fail flow, the Production Manager / Final QC /
Cosmetic Stages cleanup, the remaining deferred-items batch, the
performance self-hosting + 100-user backend tuning, the Mac Agent download
fix + Pricing Visibility RBAC, the Inventory Request permission module +
Reject flow, the WhatsApp removal + session auto-logout disable, the
production schema-drift remediation (CI column provisioning + db_validator
Postgres enum auto-provision), the repair workflow integrity fixes (409
STAGE CONFLICT + L1/L2 status consistency), the 14-item cross-module
batch, the company P&L RBAC gate, and the IQC hardware capture overhaul
(CPU Make, 3-row layout, underscore HDD/RAM format, dual-OS agent
detection, size/summary swap, Invoice Number, hidden Fan Working).

Idempotent: skips creation if REQ-240 already exists.

Usage:
  Local: python seed_qa_july16_batch.py
  Prod:  railway run --service oxypc-inventory python seed_qa_july16_batch.py
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
        existing = await db.execute(select(QARequirement).where(QARequirement.req_code == "REQ-240"))
        if existing.scalar_one_or_none():
            print("Already seeded (REQ-240 exists). Nothing to do.")
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

        # ── July 13 ──────────────────────────────────────────────────────────
        add_req("REQ-240", "Customer Care Agent (Phases 1-6)", "Customer Care",
                "New customer-support agent: warranty lookup, guided diagnostics, and "
                "ticketing backend (Phase 1), then the full agent flow through Phase 6 — "
                "warranty verification against sold-device records, symptom-driven "
                "diagnostics, ticket creation/tracking, and resolution capture.",
                priority=RequirementPriority.critical)
        add_req("REQ-241", "Systemic RBAC 403 remediation (Batch 1)", "Platform / RBAC",
                "Swept and fixed a class of role-access 403s where legitimate roles were "
                "blocked from pages they own, plus several user-edit bugs surfaced during "
                "the sweep. Tightened where over-permissive and opened where over-"
                "restrictive, per the role matrix.")
        add_req("REQ-242", "28-item enhancement request (Batches 2-8 + 10)", "Cross-module",
                "Bulk enhancement batch across inventory, repair, dealers, and reporting "
                "screens — the middle tranche of a 28-item request, delivered as batches "
                "2-8 plus the partial of batch 10.", priority=RequirementPriority.medium)

        # ── July 14 ──────────────────────────────────────────────────────────
        add_req("REQ-243", "L1/L2 <-> L3/L4 repair hand-off rework + Stress Test Complete/Fail flow", "Repair",
                "Reworked the repair hand-off between L1/L2 and L3/L4: status columns on both "
                "pages kept in sync, Request-to-L3/L4 modal, Complete->Stress transition, and "
                "Stress Test Complete/Fail buttons with Fail routing a device back to "
                "production. Statuses stay consistent across every completion and fail path.",
                priority=RequirementPriority.critical)
        add_req("REQ-244", "Production Manager / Final QC / Cosmetic Stages UI cleanup + Final QC redesign", "Repair / QC",
                "Renamed the Production Manager stage, removed the cosmetic-button clutter "
                "and Cosmetic Stages side panel (full-width table), stripped the cosmetic "
                "pipeline buttons off Final QC, and redesigned the Final QC screen.",
                priority=RequirementPriority.medium)
        add_req("REQ-245", "Remaining deferred items — Lot requests, timeline pause/resume, Production Assign, Social Leads, Trade Partner Lots/Catalog", "Cross-module",
                "Finished a set of deferred items: lot-level requests, device-timeline "
                "pause/resume, a Production Assign button, a flat Social Leads table, and "
                "Trade Partner Manage Lots / Catalog screens.", priority=RequirementPriority.medium)
        add_req("REQ-246", "Start Repair hard-block reverted + Back-to-Repair link on Device Detail", "Repair",
                "Reverted an over-strict Start Repair hard-block that trapped devices, and "
                "added a Back-to-Repair link on Device Detail so a device can return to the "
                "repair queue.", priority=RequirementPriority.medium)
        add_req("REQ-247", "Performance: self-host front-end vendor libs + backend tuning for 100 concurrent users", "Platform / Performance",
                "Self-hosted Bootstrap, jQuery, DataTables, Tom-Select, and Chart.js instead "
                "of loading from CDNs (removes third-party dependency and latency), and tuned "
                "the backend to hold 100 concurrent users.")
        add_req("REQ-248", "Mac Agent download fix + IQC field rework + repair-line tables + Pricing Visibility RBAC", "IQC / Agent",
                "Fixed the Mac diagnostic-agent download, reworked IQC entry fields, added "
                "repair-line tables, and added a Pricing Visibility RBAC control so pricing "
                "is shown only to authorised roles.")

        # ── July 15 ──────────────────────────────────────────────────────────
        add_req("REQ-249", "Inventory Request permission module + Reject flow + restore L1/L2 Complete Job panel", "Inventory / Repair",
                "Added Inventory Request to the Module Permission matrix, a Reject action "
                "(modal with notes -> Rejected pill/tooltip on Inventory Requests and Ready "
                "to Sale, re-enabling Request), and restored the right-side Complete Repair "
                "Job panel on the L1/L2 page.")
        add_req("REQ-250", "Remove WhatsApp integration + disable session auto-logout", "Platform / Security",
                "Removed the WhatsApp send/broadcast integration entirely — it had no role "
                "gate and was a security risk — and disabled the session auto-logout so "
                "signed-in users stay signed in until they explicitly log out.",
                priority=RequirementPriority.critical)
        add_req("REQ-251", "Production schema-drift remediation — CI column provisioning + db_validator Postgres enum auto-provision", "Platform / DevOps",
                "Fixed production 500s caused by schema drift: the deploy now provisions "
                "missing columns, and db_validator reconciles Postgres ENUM values (ALTER "
                "TYPE ... ADD VALUE) at startup — root cause of the /iq/new 500 where the "
                "devicestage enum was missing the 'putty' value.",
                priority=RequirementPriority.critical)
        add_req("REQ-252", "Repair workflow integrity — 409 STAGE CONFLICT fix + L1/L2 status column consistency", "Repair",
                "Closed open RepairJobs on Complete-to-Stress and filtered the open-jobs "
                "query by current stage so a stale job can no longer cause a 409 STAGE "
                "CONFLICT on /repair/complete, and made the L1/L2 status column consistent "
                "across all completion and fail paths.")

        # ── July 16 ──────────────────────────────────────────────────────────
        add_req("REQ-253", "14-item cross-module batch — Multi-Sell, dealer soft-delete, L3/L4 parts, IQC RAM/HDD, PO Category, notes truncation", "Cross-module",
                "Ready-to-Sale Sell/Multi-Sell with a New Sale modal (Stock Price / Total "
                "Sale Price / No-Warranty default), Module dropdown edit pencil, Customise "
                "modal hardware edits, dealer soft-delete (single + bulk) synced across "
                "pages, L3/L4 'Incorrect column count' fix + Request Part, Part Categories, "
                "IQC RAM/HDD count+size fields, notes truncation (150 char / 2 line / "
                "tooltip), and a PO Category dropdown in the quotation/invoice/PO modals.",
                priority=RequirementPriority.medium)
        add_req("REQ-254", "Company P&L RBAC — gate financial reports to management only", "Reporting / Security",
                "Company P&L and lot P&L reports (and their exports) were reachable by "
                "sales/QC roles through a coarse gate; added an inventory_manager / "
                "sales_manager requirement so only management sees company financials.")
        add_req("REQ-255", "IQC hardware capture overhaul — CPU Make, 3-row layout, underscore HDD/RAM format, dual-OS agent, size/summary swap, Invoice Number", "IQC / Agent",
                "IQC entry reworked: CPU Make field (Intel/AMD/Apple), three-row hardware "
                "layout, underscore combined format (e.g. 512GB_SSD_7400_Samsung), "
                "Total-Size vs combined-summary values swapped per spec, Invoice Number "
                "captured on entry, CPU Make ordered before CPU, and Fan Working hidden — "
                "all detected and filled by the diagnostic agent on both Windows and macOS "
                "(including Apple Silicon unified memory).", priority=RequirementPriority.medium)

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

        add_tc("TC-240-1", "REQ-240", "Care Agent verifies warranty for a sold device",
               "A support user looks up a device by serial/tag and sees its warranty status",
               "1. Open Customer Care Agent\n2. Enter a sold device's serial/tag\n3. Read warranty status",
               "Warranty state (in/out of warranty, dates) resolves from the sold-device record")
        add_tc("TC-240-2", "REQ-240", "Care Agent creates and tracks a support ticket",
               "A support user runs diagnostics and raises a ticket from the agent",
               "1. Run guided diagnostics on a symptom\n2. Create a ticket\n3. Reopen and check status",
               "Ticket is created, linked to the device, and its status is trackable",
               type_=TestCaseType.integration)
        add_tc("TC-241-1", "REQ-241", "Legitimate roles no longer 403 on their own pages",
               "Roles fixed in the RBAC sweep can reach the pages they own",
               "1. Log in as each fixed role\n2. Open the previously-403 pages",
               "Pages load (200); no over-restrictive 403 remains for authorised roles",
               type_=TestCaseType.regression)
        add_tc("TC-243-1", "REQ-243", "L1/L2 status mirrors on L3/L4 and back",
               "Requesting L3/L4 and completing back to production keeps both status columns in sync",
               "1. From L1/L2, Request to L3/L4\n2. Complete on L3/L4\n3. Return to L1/L2 and Complete->Stress",
               "Status columns on both pages stay consistent through every transition")
        add_tc("TC-243-2", "REQ-243", "Stress Test Fail routes device back to production",
               "Failing a stress test sends the device back to the production queue with reset status",
               "1. Open a device in Stress Test\n2. Click Fail, assign back\n3. Check the device's stage/status",
               "Device returns to production; l1l2/l34 statuses reset appropriately",
               type_=TestCaseType.functional)
        add_tc("TC-244-1", "REQ-244", "Final QC no longer shows cosmetic pipeline buttons",
               "Final QC redesign removed the cosmetic buttons and Cosmetic Stages side panel",
               "1. Open Final QC\n2. Open Cosmetic Stages",
               "Final QC has no cosmetic buttons; Cosmetic Stages is a full-width table",
               type_=TestCaseType.regression)
        add_tc("TC-247-1", "REQ-247", "Front-end libraries load from self-hosted static, not CDN",
               "No third-party CDN requests for Bootstrap/jQuery/DataTables/Tom-Select/Chart.js",
               "1. Load any page with devtools Network open\n2. Filter for cdn/jsdelivr/cloudflare",
               "All vendor libs load from /static/vendor; zero external CDN requests",
               type_=TestCaseType.integration, is_automated=False)
        add_tc("TC-248-1", "REQ-248", "Mac Agent downloads and runs",
               "The macOS diagnostic agent download link serves a working artifact",
               "1. Open the agent download page on macOS\n2. Download and run the Mac agent",
               "Download succeeds and the agent detects hardware")
        add_tc("TC-248-2", "REQ-248", "Pricing Visibility RBAC hides pricing from unauthorised roles",
               "Only authorised roles see pricing fields",
               "1. Log in as a non-pricing role\n2. Open a page that shows pricing to managers",
               "Pricing is hidden for unauthorised roles, visible for authorised ones",
               type_=TestCaseType.negative)
        add_tc("TC-249-1", "REQ-249", "Reject an inventory request with notes",
               "Rejecting shows a Rejected pill/tooltip and re-enables Request",
               "1. Open an Inventory Request\n2. Reject with notes\n3. Check Inventory Requests + Ready to Sale",
               "Rejected pill + notes tooltip appear on both pages; the Request action is re-enabled")
        add_tc("TC-249-2", "REQ-249", "L1/L2 Complete Repair Job panel is present and usable",
               "The restored right-side Complete Job panel lists in-progress jobs",
               "1. Start a repair on L1/L2\n2. Open the Complete Repair Job panel",
               "Panel lists the started job and can complete it",
               type_=TestCaseType.regression)
        add_tc("TC-250-1", "REQ-250", "WhatsApp integration fully removed",
               "No WhatsApp send/broadcast endpoints or UI remain",
               "1. Search nav/pages for WhatsApp\n2. Probe former WhatsApp routes",
               "No WhatsApp UI; former endpoints are gone (404); route baseline unchanged",
               type_=TestCaseType.regression)
        add_tc("TC-250-2", "REQ-250", "Session no longer auto-logs-out an active user",
               "A signed-in user stays signed in past the old idle timeout",
               "1. Log in\n2. Leave the session idle past the previous timeout\n3. Navigate",
               "User remains authenticated; no forced sign-out")
        add_tc("TC-251-1", "REQ-251", "Production IQC entry no longer 500s on new enum value",
               "Creating an IQC device whose stage uses a newly-added enum value succeeds",
               "1. On production, submit IQC entry that lands a device in the 'putty' stage",
               "Entry saves; no InvalidTextRepresentation 500; enum auto-provisioned at startup",
               type_=TestCaseType.regression, is_automated=True)
        add_tc("TC-252-1", "REQ-252", "No 409 STAGE CONFLICT after inline Complete-to-Stress",
               "A device that already moved to stress cannot leave a stale open RepairJob",
               "1. Complete-to-Stress inline from the Complete Job panel\n2. Attempt /repair/complete again",
               "No 409; stale jobs are closed and filtered by current stage",
               type_=TestCaseType.negative)
        add_tc("TC-253-1", "REQ-253", "Multi-Sell creates one sale per selected device",
               "Selecting several Ready-to-Sale devices and Multi-Sell books each as a sale",
               "1. Select N ready devices\n2. Multi-Sell\n3. Confirm the New Sale modal",
               "N Sale rows are created (one per device); single Sell still books one")
        add_tc("TC-253-2", "REQ-253", "Dealer soft-delete is synced across pages",
               "Deleting a dealer (single or bulk) removes it from every dealer list",
               "1. Delete a dealer on Dealer Management\n2. Check Assign Dealer List",
               "Dealer no longer appears in either list; row is soft-deleted (recoverable)")
        add_tc("TC-254-1", "REQ-254", "Sales/QC roles get 403 on company P&L",
               "Financial reports are gated to management only",
               "1. Log in as sales or QC\n2. Open /reports business P&L and lot P&L (and exports)",
               "403 for sales/QC; 200 for admin/inventory_manager/sales_manager",
               type_=TestCaseType.negative, is_automated=True)
        add_tc("TC-255-1", "REQ-255", "Agent fills swapped RAM/HDD fields on Windows and Mac",
               "Diagnose populates Total-Size boxes with the combined string and RAM/Hard Drive with plain size",
               "1. Run agent on a Windows unit, then a Mac unit\n2. Click Diagnose on IQC entry\n3. Read the RAM/HDD rows",
               "Total RAM/HDD Size = combined string (e.g. 512GB_SSD_7400_Samsung); "
               "RAM/Hard Drive = plain size (e.g. 512GB); CPU Make filled on both OSes")
        add_tc("TC-255-2", "REQ-255", "Invoice Number persists from IQC entry",
               "Invoice Number entered on IQC entry saves to the device",
               "1. Enter an IQC device with an Invoice Number\n2. Open the device detail/edit",
               "Invoice Number is saved and shown")

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

        add_defect("BUG-202", "Systemic RBAC 403s blocked legitimate roles", "Platform / RBAC",
                   "Several roles received 403 on pages they legitimately own, blocking daily work.",
                   DefectSeverity.high, DefectStatus.closed,
                   root_cause="Coarse/incorrect role gates on multiple routes and templates.",
                   resolution="Swept and corrected the gates against the role matrix (Batch 1); "
                              "opened over-restrictive routes and tightened over-permissive ones.",
                   days_ago=3)
        add_defect("BUG-203", "Stress Test report page crashed", "QC / Stress Test",
                   "Opening the Stress Test report raised an error for some devices.",
                   DefectSeverity.high, DefectStatus.closed,
                   root_cause="Report rendering assumed data that could be missing.",
                   resolution="Hardened the report path and fixed the related user-edit bugs.",
                   days_ago=3)
        add_defect("BUG-204", "L1/L2/L3 engineers got 403 on the Stress Test page", "QC / Stress Test",
                   "Repair engineers who need Stress Test were blocked with 403.",
                   DefectSeverity.high, DefectStatus.closed,
                   root_cause="Stress Test route gate omitted the engineer roles.",
                   resolution="Added the engineer roles to the Stress Test access gate.",
                   days_ago=2)
        add_defect("BUG-205", "Start Repair hard-block trapped devices", "Repair",
                   "An over-strict Start Repair block prevented devices from progressing.",
                   DefectSeverity.medium, DefectStatus.closed,
                   root_cause="A hard-block was added where a soft path was needed.",
                   resolution="Reverted the hard-block and added a Back-to-Repair link on Device Detail.",
                   days_ago=2)
        add_defect("BUG-206", "Production 500 on /iq/new — devicestage enum missing 'putty'", "IQC / DevOps",
                   "Creating an IQC device on production 500'd when the stage used a value the "
                   "Postgres enum didn't have.",
                   DefectSeverity.critical, DefectStatus.closed,
                   root_cause="Postgres 'devicestage' enum lacked the 'putty' value; the app "
                              "model had it but the DB type was never altered.",
                   resolution="Added Phase 0 enum reconciliation to db_validator (ALTER TYPE ... "
                              "ADD VALUE on an AUTOCOMMIT connection) and fixed live.",
                   days_ago=1)
        add_defect("BUG-207", "Production schema drift caused 500s on several pages", "Platform / DevOps",
                   "Missing columns on production (the deploy only ran alembic, but the project "
                   "uses an auto-provisioner) caused 500s.",
                   DefectSeverity.critical, DefectStatus.closed,
                   root_cause="Deploy pipeline didn't run the additive-column auto-provisioner.",
                   resolution="Added a schema-provisioning step to the deploy that runs "
                              "validate_and_fix(auto_fix=True).",
                   days_ago=1)
        add_defect("BUG-208", "409 STAGE CONFLICT on /repair/complete after inline Complete-to-Stress", "Repair",
                   "A device already moved to stress still listed a stale RepairJob in the "
                   "Complete-Job panel, causing a 409 on complete.",
                   DefectSeverity.high, DefectStatus.closed,
                   root_cause="Open RepairJobs weren't closed on Complete-to-Stress and the "
                              "open-jobs query didn't filter by current stage.",
                   resolution="Close RepairJobs on complete-to-stress and filter open_jobs by "
                              "current_stage + is_active.",
                   days_ago=1)
        add_defect("BUG-209", "L1 couldn't mark Pending/Complete after Start (empty Complete-Job dropdown)", "Repair",
                   "After Start, the Complete Repair Job dropdown was empty so L1 couldn't set "
                   "status.",
                   DefectSeverity.high, DefectStatus.closed,
                   root_cause="/repair/l1l2-start created no RepairJob, so nothing populated the panel.",
                   resolution="l1l2-start now creates a RepairJob.",
                   days_ago=2)
        add_defect("BUG-210", "Repair showed part in-stock but Spare Parts showed zero", "Repair / Parts",
                   "A repair showed a fuzzy-matched part as in stock, but the part request "
                   "recorded a different/empty part_id so Spare Parts showed zero.",
                   DefectSeverity.high, DefectStatus.closed,
                   root_cause="PartRequest stored a mismatched part_id vs the displayed match.",
                   resolution="Submit the matched part_id so stock and request agree.",
                   days_ago=2)
        add_defect("BUG-211", "WhatsApp send/broadcast had no role gate (security)", "Platform / Security",
                   "WhatsApp send and broadcast endpoints were ungated, a real security risk.",
                   DefectSeverity.critical, DefectStatus.closed,
                   root_cause="Integration shipped without RBAC on its send/broadcast routes.",
                   resolution="Removed the WhatsApp integration entirely.",
                   days_ago=1)
        add_defect("BUG-212", "Company P&L visible to sales/QC roles (RBAC exposure)", "Reporting / Security",
                   "A coarse /reports gate let sales and QC roles view company and lot P&L.",
                   DefectSeverity.high, DefectStatus.closed,
                   root_cause="Reports gate wasn't specific to financial views.",
                   resolution="Added an inventory_manager/sales_manager requirement on the P&L "
                              "reports and exports.",
                   days_ago=0)
        add_defect("BUG-213", "Mac diagnostic-agent download was broken", "IQC / Agent",
                   "The macOS agent download didn't serve a working artifact.",
                   DefectSeverity.medium, DefectStatus.closed,
                   root_cause="Mac agent build/download path issue.",
                   resolution="Fixed the Mac Agent download.",
                   days_ago=2)

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

        add_uat("UAT-216", "REQ-240", "Support rep handles a warranty claim end-to-end via the Care Agent",
                "A customer calls with a fault; the rep verifies warranty, runs diagnostics, raises a ticket",
                "Warranty resolves from records, diagnostics guide the rep, and a trackable ticket is created", "Customer Support Lead")
        add_uat("UAT-217", "REQ-243", "Repair engineer moves a device L1/L2 -> L3/L4 -> stress cleanly",
                "An engineer escalates to L3/L4, completes, returns, and sends to stress",
                "Status stays consistent on both pages through the whole hand-off; no stuck states", "Repair Floor Manager")
        add_uat("UAT-218", "REQ-249", "Inventory manager rejects a request with a reason",
                "A manager declines an inventory request and records why",
                "Rejected pill + notes appear on both lists and the requester can request again", "Inventory Manager")
        add_uat("UAT-219", "REQ-250", "Users stay signed in and WhatsApp is gone",
                "Staff work a full shift without being logged out; no WhatsApp features remain",
                "No forced sign-outs during active use; WhatsApp UI/endpoints absent", "Operations Head")
        add_uat("UAT-220", "REQ-251", "Ops confirms production IQC entry works after the schema fix",
                "An operator adds a new product via IQC on production",
                "IQC entry saves with no 500; new columns/enum values are auto-provisioned", "Warehouse Lead")
        add_uat("UAT-221", "REQ-253", "Salesperson multi-sells a batch of ready devices",
                "A salesperson sells several ready-to-sale units in one action",
                "Each selected device is booked as its own sale with the correct prices", "Sales Manager")
        add_uat("UAT-222", "REQ-254", "Sales/QC staff cannot see company P&L",
                "A sales rep tries to open the company financial reports",
                "Company/lot P&L and exports are blocked for non-management roles", "Finance / Management")
        add_uat("UAT-223", "REQ-255", "IQC clerk auto-fills hardware on both Windows and Mac units",
                "A clerk diagnoses a Windows laptop and a MacBook and reviews the captured specs",
                "CPU Make, RAM/HDD counts+sizes, and combined strings fill correctly on both OSes; Invoice Number saves", "IQC Supervisor")

        await db.flush()

        def add_release(version, title, status, description=None, days_ago_planned=0, days_ago_release=None):
            rel = QARelease(
                id=uuid.uuid4(), version=version, title=title, description=description, status=status,
                planned_date=now - timedelta(days=days_ago_planned),
                release_date=(now - timedelta(days=days_ago_release)) if days_ago_release is not None else None,
                qa_sign_off_by=CREATED_BY, qa_sign_off_at=now - timedelta(days=1),
                created_by=CREATED_BY, created_at=now, updated_at=now,
            )
            db.add(rel)
            return rel

        add_release("v1.10.0",
                    "July 13-16 batch — Care Agent, RBAC & repair rework, prod schema fixes, IQC overhaul",
                    ReleaseStatus.deployed,
                    description=(
                        "Customer Care Agent (Phases 1-6) + systemic RBAC 403 remediation + "
                        "L1/L2<->L3/L4 repair hand-off & Stress Test Complete/Fail rework + "
                        "Production Manager/Final QC/Cosmetic Stages cleanup + remaining deferred "
                        "items (Lot requests, timeline pause/resume, Production Assign, Social "
                        "Leads, Trade Partner Lots/Catalog) + performance self-hosting of vendor "
                        "libs and 100-user backend tuning + Mac Agent download fix & Pricing "
                        "Visibility RBAC + Inventory Request permission module & Reject flow + "
                        "WhatsApp removal & session auto-logout disable + production schema-drift "
                        "remediation (CI column provisioning + db_validator Postgres enum auto-"
                        "provision) + repair integrity fixes (409 STAGE CONFLICT + L1/L2 status "
                        "consistency) + 14-item cross-module batch + company P&L RBAC gate + IQC "
                        "hardware capture overhaul (CPU Make, 3-row layout, underscore HDD/RAM "
                        "format, dual-OS agent detection, size/summary swap, Invoice Number, "
                        "hidden Fan Working)."
                    ),
                    days_ago_planned=3, days_ago_release=0)

        await db.commit()
        print("Seeded (July 13-16 batch): 16 requirements, 20 test cases, 12 defects, 8 UAT scenarios, 1 release (v1.10.0).")


if __name__ == "__main__":
    asyncio.run(run())
