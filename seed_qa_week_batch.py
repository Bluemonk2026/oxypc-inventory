"""
OxyPC Inventory — Seed QA/UAT tracking with this week's work (July 7-10, 2026)
================================================================================
Continues from seed_qa_july7_batch.py, which stopped at REQ-229 / v1.8.0.
This adds everything shipped after that: Product IQC filters/sort/pagination,
Customise-modal replication to Overall Inventory (Tag + Lot) + Model Based
Summary tables, the full Admin Dashboard restructure (flattened admin-only
layout, 12→10 stat cards with Total badges, Inventory/GRN/Dealers redefined,
Total Stock renamed to Total In/Out, Total Sales sourced from real data),
QA Dashboard Stage Workflows tab, QA Dashboard SRS Documents card, Trade
Partner Edit Dealer Login Mobile field, and admin-lands-on-dashboard login
redirect.

Idempotent: skips creation if REQ-230 already exists.

Usage: python seed_qa_week_batch.py
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
        existing = await db.execute(select(QARequirement).where(QARequirement.req_code == "REQ-230"))
        if existing.scalar_one_or_none():
            print("Already seeded (REQ-230 exists). Nothing to do.")
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

        add_req("REQ-230", "Product IQC: Search/Stage/Grade/Lot filters + sortable Stage column", "IQC",
                "Added a filter bar (Search box across Tag Number/model/brand/serial, Stage "
                "dropdown, Grade dropdown, Lot dropdown) to Product IQC, plus a sortable Stage "
                "column and DataTable pagination on the main table.",
                priority=RequirementPriority.medium)
        add_req("REQ-231", "Customise modal replicated to Overall Inventory (Tag + Lot) + Model Based Summary", "IQC / Inventory",
                "The Product IQC Customise modal (bulk Device Type / Grade / Invoice / PO / "
                "Move to Stage) now also appears on Overall Inventory's Tag Number table and its "
                "Lot Based Summary table, with full feature parity. Added a new Model Based "
                "Summary table to Product IQC with its own Customise modal. Backing endpoint "
                "/iqc/bulk-apply-grade-type generalized to accept barcodes, lot_numbers, or "
                "model_keys plus a return_to path (allow-listed to /iqc and /devices).",
                priority=RequirementPriority.high)
        add_req("REQ-232", "Admin Dashboard: flatten to Operations-only layout, remove duplicate widgets", "Reporting",
                "Removed the Operations/Finance/Inventory tab switcher for admin (Operations "
                "content shown directly), removed the Admin Overview accordion, and removed the "
                "duplicate standalone Stage Pipeline section. Reorganized into a 3/4 + 1/4 first "
                "row (Device Stage Pipeline + Location Gaps / Financial Summary) and a final row "
                "with Weekly Sourcing Price + Inventory by Category & Stage at equal width.",
                priority=RequirementPriority.medium)
        add_req("REQ-233", "Admin Dashboard: Total count badge on every stat card + card reordering", "Reporting",
                "Each of the 10 analytics stat cards now shows a Total badge (either the sum of "
                "its own breakdown, or an explicit override where summing would be semantically "
                "wrong). Stage Products card moved to sit immediately after Total Products.",
                priority=RequirementPriority.medium)
        add_req("REQ-234", "Admin Dashboard: redefine Total Products/GRN/Dealers card semantics", "Reporting",
                "Total Products card gained an 'Inventory' breakdown (tag-number count across "
                "all stages, shown before 'To be Sold'), and its Total badge now equals this "
                "Inventory figure. Total GRN redefined from Parts-GRN status to Device.grn_number "
                "presence — 'In Plan' = tag numbers without a GRN value, 'In TRC' = tag numbers "
                "with one, Total badge = the In TRC (has-GRN) count. Total Dealers badge now "
                "shows the real total dealer count from Dealer Management instead of a sum of "
                "call-outcome breakdowns.", priority=RequirementPriority.high)
        add_req("REQ-235", "QA Dashboard: Stage Workflows tab with Download + Create Detail Workflow", "QA Tooling",
                "Added a Stage Workflows tab covering 5 named stage-transition flows (Sourcing>"
                "GRN, GRN>IQC, IQC>Stock IN>Repair>Cosmetic>Final QC>Ready To Sale, Ready to Sale>"
                "Sold, Sold>Return), each with a plain-text Download export and a Create Detail "
                "Workflow modal showing the per-stage breakdown.")
        add_req("REQ-236", "Admin Dashboard: rename Total Stock to Total In/Out, source Total Sales from real data", "Reporting",
                "Total Stock renamed to Total In/Out with its breakdown simplified to Total Sold "
                "/ Total Return, and moved to sit immediately before Total Sales. Total Sales' "
                "three buckets (Procurement / Telecaller / Showroom) now come from real queries "
                "(CRMPurchaseOrder count / Sale joined to a telecaller-role User / Sale joined to "
                "a sales-role User) instead of the dead Sale.sale_channel field, which was never "
                "actually set at sale-creation time.", priority=RequirementPriority.high)
        add_req("REQ-237", "QA Dashboard: SRS Documents card (Technical + Functional Spec downloads)", "QA Tooling",
                "Added an SRS Documents card between UAT Progress and Active Releases with "
                "on-demand downloadable Technical Specification and Functional Specification "
                "documents covering the current architecture, modules, workflows, and roles.")
        add_req("REQ-238", "Trade Partner: Edit Dealer modal — Login Mobile field", "Trade Partner",
                "The Edit Dealer detail modal on the Trade Partner Accounts page now includes a "
                "Login Mobile field, letting an admin change a dealer's portal login mobile "
                "number directly (same 10-digit + duplicate-check validation as Enable Portal "
                "Access) without disabling and re-enabling the account.")
        add_req("REQ-239", "Login: admin lands on Admin Dashboard first", "Platform",
                "Admin users now land on the Admin Dashboard (/dashboard) immediately after "
                "login instead of Inventory Search; every other role continues to land on "
                "Inventory Search (/devices), which remains reachable for admins via the nav.")

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

        add_tc("TC-230-1", "REQ-230", "Product IQC filters narrow the list correctly",
               "Search/Stage/Grade/Lot filters each narrow the Product IQC table independently and combined",
               "1. Open Product IQC\n2. Apply each filter alone, then combined\n3. Sort the new Stage column",
               "Each filter narrows results as expected; Stage column sorts correctly; pagination reflects the filtered set",
               type_=TestCaseType.regression)
        add_tc("TC-231-1", "REQ-231", "Customise modal on Overall Inventory Tag table applies Move to Stage",
               "Selecting tags on the Overall Inventory Tag Number table and using Customise moves them, validated",
               "1. Open Overall Inventory\n2. Select several tags, open Customise\n3. Pick Move to Stage, Apply",
               "Allowed transitions apply and redirect back to /devices; disallowed tags are skipped and reported")
        add_tc("TC-231-2", "REQ-231", "Model Based Summary Customise modal applies to every device of that model",
               "Applying Customise from the new Model Based Summary table affects all matching devices",
               "1. Open Product IQC > Model Based Summary\n2. Select a model row, open Customise, Apply a grade change",
               "All devices matching that model|||brand key are updated")
        add_tc("TC-232-1", "REQ-232", "Admin Dashboard shows flattened Operations content, no duplicate widgets",
               "Admin sees Operations content directly with no tab switcher, accordion, or duplicate Stage Pipeline",
               "1. Log in as admin, open Dashboard",
               "No Finance/Inventory tabs or Admin Overview accordion render; only one Stage Pipeline-style section (Device Stage Pipeline) appears",
               type_=TestCaseType.regression)
        add_tc("TC-233-1", "REQ-233", "Every analytics stat card shows a Total badge",
               "Each of the 10 stat cards displays a badge total matching its breakdown or explicit override",
               "1. Open Admin Dashboard\n2. Inspect each stat card's badge against its breakdown values",
               "Badge equals sum-of-parts, or the documented override value, for every card")
        add_tc("TC-234-1", "REQ-234", "Total GRN card reflects Device.grn_number, not Parts GRN status",
               "In Plan / In TRC counts match devices without/with a grn_number value",
               "1. Query devices grouped by whether grn_number is set\n2. Compare to the Total GRN card",
               "In Plan = no-GRN device count, In TRC = has-GRN device count, badge = In TRC")
        add_tc("TC-236-1", "REQ-236", "Total Sales buckets are non-zero and reflect real sources",
               "Procurement/Telecaller/Showroom counts come from CRMPurchaseOrder and role-joined Sale queries",
               "1. Create a PO, a telecaller-role sale, and a sales-role sale\n2. Check the Total Sales card",
               "Each bucket increments from its real source; none of the three buckets are permanently 0",
               type_=TestCaseType.regression)
        add_tc("TC-235-1", "REQ-235", "Stage Workflows tab downloads and expands each of the 5 flows",
               "Every stage-transition workflow card downloads a text file and opens a detail modal",
               "1. Open QA Dashboard > Stage Workflows\n2. Click Download and Create Detail Workflow on each card",
               "Download returns a populated .txt file per workflow; detail modal lists every stage with its description")
        add_tc("TC-237-1", "REQ-237", "SRS Documents card downloads both specs",
               "Technical and Functional Specification documents download successfully from the QA Dashboard",
               "1. Open QA Dashboard\n2. Click the download icon for each of the two documents",
               "Both files download with non-empty, relevant content")
        add_tc("TC-238-1", "REQ-238", "Editing Login Mobile updates the dealer's portal login number",
               "Changing the Login Mobile field in Edit Dealer updates portal_phone with validation",
               "1. Open Trade Partner Accounts > Edit a dealer\n2. Change Login Mobile to a new 10-digit number, Save\n3. Attempt to reuse a number already in use by another dealer",
               "Valid unique numbers save and the dealer can log in with the new number; duplicate numbers are rejected with an error",
               type_=TestCaseType.negative)
        add_tc("TC-239-1", "REQ-239", "Admin login redirects to Admin Dashboard, other roles unaffected",
               "Only the admin role's post-login landing page changed",
               "1. Log in as admin — check landing page\n2. Log in as a non-admin role — check landing page",
               "Admin lands on /dashboard; every other role still lands on /devices",
               type_=TestCaseType.regression, is_automated=True)

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

        add_defect("BUG-107", "Total Sales card on Admin Dashboard always showed zero", "Reporting",
                    "Procurement/Telecaller/Showroom buckets on the Total Sales card were grouped "
                    "by Sale.sale_channel, a field declared on the model but never actually set at "
                    "any sale-creation code path, so every bucket always read 0.",
                    DefectSeverity.medium, DefectStatus.closed,
                    root_cause="sale_channel was added to the schema but no sale-creation flow "
                               "(telecalling, showroom, or procurement) was ever wired to set it.",
                    resolution="Replaced the grouped sale_channel query with three real-source "
                               "queries: CRMPurchaseOrder count for Procurement, and Sale joined "
                               "to User.role for Telecaller/Showroom.",
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

        add_uat("UAT-210", "REQ-230", "IQC clerk narrows a large IQC queue to just their current lot",
                "IQC clerk filters Product IQC down to devices in a specific lot and stage",
                "Filter bar + sortable Stage column let the clerk find the exact subset without scrolling the full queue", "Warehouse Lead")
        add_uat("UAT-211", "REQ-231", "Inventory manager bulk-moves a batch of tags straight from Overall Inventory",
                "Inventory manager no longer has to go back to Product IQC to bulk-move a batch of tags",
                "Customise modal with Move to Stage is available directly on Overall Inventory's Tag and Lot tables", "Inventory Manager")
        add_uat("UAT-212", "REQ-232", "Admin gets a cleaner, non-redundant dashboard on daily login",
                "Admin no longer sees duplicate Stage Pipeline sections or an empty accordion",
                "Dashboard shows one clear layout: pipeline+gaps, financial summary, stat cards, charts", "Admin")
        add_uat("UAT-213", "REQ-234", "Admin trusts the GRN and Dealer counts on the dashboard",
                "Admin cross-checks the Total GRN and Total Dealers cards against source data",
                "GRN counts match Device.grn_number presence; Dealers total matches Dealer Management's own count", "Admin")
        add_uat("UAT-214", "REQ-236", "Admin can finally see real sales-channel mix on the dashboard",
                "Admin wants to know how much of this week's sales came from Telecalling vs Showroom vs Procurement",
                "Total Sales card shows non-zero, source-backed numbers for all three channels", "Admin")
        add_uat("UAT-215", "REQ-238", "Admin updates a dealer's login mobile after they change their number",
                "A dealer reports their registered mobile number changed and can no longer receive OTP/login",
                "Admin edits the dealer's Login Mobile in Edit Dealer and the dealer can log in with the new number", "Sales Ops Manager")

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

        add_release("v1.9.0",
                     "IQC filters + Customise modal parity + Admin Dashboard restructure + "
                     "QA Stage Workflows/SRS Documents + Trade Partner Login Mobile edit",
                     ReleaseStatus.deployed, days_ago_planned=1, days_ago_release=0)

        await db.commit()
        print("Seeded: 10 requirements, 12 test cases, 1 defect, 6 UAT scenarios, 1 release.")


if __name__ == "__main__":
    asyncio.run(run())
