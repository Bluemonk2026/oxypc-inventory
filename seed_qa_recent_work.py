"""
OxyPC Inventory — Seed QA/UAT tracking with recent sprint work
===============================================================
Existing qa_requirements/test_cases/defects/uat/releases data stops at
REQ-208 / v1.0.3 (Dealer Mgmt + Telecalling). This adds the substantial body
of work done since then — pagination overhaul, Product IQC bulk-upload
rework, Device Type/PO Category master-data fixes, Lot optional fields,
Dealer bulk-upload validation, Move Device case-insensitivity, Diagnose
Agent accuracy + self-update fix, Mac single-file installer, and the QA
Dashboard workflow diagram/changelog — as Requirements, Test Cases, Defects,
UAT Scenarios, and Releases so the QA tracking module reflects reality.

Idempotent: skips creation if REQ-209 already exists.

Usage: python seed_qa_recent_work.py
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
        existing = await db.execute(select(QARequirement).where(QARequirement.req_code == "REQ-209"))
        if existing.scalar_one_or_none():
            print("Already seeded (REQ-209 exists). Nothing to do.")
            return

        now = app_now()
        reqs = {}

        def add_req(code, title, module, desc, source=RequirementSource.bug_fix,
                     priority=RequirementPriority.high, status=RequirementStatus.done):
            r = QARequirement(
                id=uuid.uuid4(), req_code=code, title=title, description=desc,
                source=source, priority=priority, status=status, module=module,
                created_by=CREATED_BY, created_at=now, updated_at=now,
            )
            db.add(r)
            reqs[code] = r
            return r

        add_req("REQ-209", "Device Type master-data wiring app-wide", "Master Data",
                "Overall Inventory / Stock Inward / IQC Device Type dropdowns were hardcoded; "
                "wired all to the device_type Master Data key. Fixed 'PO Category' missing from "
                "the Master Data configuration page.")
        add_req("REQ-210", "Product IQC bulk upload: full-field template", "IQC",
                "Removed CSV Template button; bulk-upload sample now covers every IQC entry "
                "field (full physical inspection checklist), not just core device fields, with "
                "Tag No/serial_no/brand/model/cpu/ram_gb/storage_gb/category/lot_number first.")
        add_req("REQ-211", "App-wide pagination standardization", "Platform",
                "Removed 18 hardcoded backend row-caps (500/1000/5000 etc.) that silently "
                "truncated list pages; standardized every DataTable to 12 rows/page with "
                "bottom-center pagination via a single global default in base.html.",
                priority=RequirementPriority.critical)
        add_req("REQ-212", "Product IQC / Ready to Sale showing only 50 of 4500+ records", "IQC / Sales",
                "Root-caused to server-side page_size=50 cap plus client-side paging:false on "
                "several tables; converted 9 pages (IQC, Sales List, Dealers List, WhatsApp "
                "Audit, Stress Test, L1/L2/L3 Repair, Lot Overview, TRC Production, Market "
                "Intel, System Audit Log) to full-fetch + client-side pagination.",
                priority=RequirementPriority.critical)
        add_req("REQ-213", "Lot Add/Edit: optional Price and Quantity", "Lots",
                "Quantity/Buying Price no longer required on Add/Edit Lot; default qty=1, "
                "price=0 when left blank (divide-by-zero guarded in sales/iqc unit-cost calcs).",
                source=RequirementSource.change_req, priority=RequirementPriority.medium)
        add_req("REQ-214", "Dealer Bulk Upload: validation fixes", "Dealers",
                "Business-name duplicate check made case-insensitive. Phone field policy "
                "iterated twice per business feedback: first tightened to reject multi-number "
                "cells, then reopened to accept comma/slash/semicolon/pipe-separated multi-number "
                "cells — required widening dealers.phone from VARCHAR(20) to VARCHAR(100).",
                source=RequirementSource.change_req)
        add_req("REQ-215", "Move Device page: case-insensitive scan fields", "Transfers",
                "Removed forced uppercase on all 3 tabs' scan inputs (Tag Number / Bucket / "
                "Lot); Tag Number lookup (/devices/api/brief) converted to ilike() to match.")
        add_req("REQ-216", "Diagnose Agent: accurate Battery/Storage Health detection", "IQC Agent",
                "Storage Health % upgraded from a crude healthy/unhealthy ratio to real SMART/"
                "NVMe wear-level data (Get-StorageReliabilityCounter on Windows, smartctl on "
                "macOS). Battery Health % already correct on both platforms.")
        add_req("REQ-217", "Diagnose Agent: stale resident process blocks self-update", "IQC Agent",
                "A rebuilt agent exe silently failed to replace an already-running old instance "
                "(file lock + port 8765 conflict), so technicians kept seeing pre-fix behavior "
                "after re-downloading. Added /quit + version handshake so a fresh launch evicts "
                "the old resident process before installing.", priority=RequirementPriority.critical)
        add_req("REQ-218", "Diagnose Agent (macOS): single-file .command installer", "IQC Agent",
                "Replaced the zip (agent.py + .command + README) with one self-contained "
                ".command file — agent source embedded via bash heredoc — so download and "
                "double-click both work with no unzip step.",
                source=RequirementSource.change_req)
        add_req("REQ-219", "QA Dashboard: Application Workflow diagram", "QA/UAT",
                "Added an end-to-end workflow diagram to the QA Dashboard covering Sourcing/PO/"
                "Part Sourcing/Part GRN, IQC & Grading, Repair L1-L3 with part request/replace/"
                "scrap, QC & Sales-Ready, Dealer/Telecalling/CRM, and the Returns/Warranty loop "
                "— as two tabs for the two valid inbound sequences (PO/GRN-first vs. IQC-received-first).",
                source=RequirementSource.change_req)
        add_req("REQ-220", "QA Dashboard: recent-changes changelog backfill", "QA/UAT",
                "Curated changelog entries for the prior ~2 weeks of sprint work added to "
                "_HARDCODED_COMMITS so /qa/ reflects actual delivered work, not just auto-pulled "
                "commit subjects.")

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

        add_tc("TC-209-1", "REQ-209", "Device Type filter uses Master Data values",
               "Overall Inventory Device Type filter shows only master_values('device_type') entries",
               "1. Open /devices\n2. Open Device Type filter dropdown\n3. Compare options to Master Data > device_type",
               "Dropdown options exactly match the configured Master Data list")
        add_tc("TC-209-2", "REQ-209", "PO Category visible in Master Data config",
               "Purchase Orders: PO Category key is selectable in Master Data admin page",
               "1. Open /admin/master\n2. Search for 'PO Category'",
               "PO Category key appears with its configured values, editable like other keys")
        add_tc("TC-210-1", "REQ-210", "Bulk upload sample includes all IQC fields",
               "Downloaded sample CSV covers every field on the IQC entry form",
               "1. Open Product IQC > Bulk Upload\n2. Download sample file\n3. Diff columns against IQC entry form fields",
               "All IQC form fields present as columns, Tag No/serial_no/brand/model/cpu/ram_gb/storage_gb/category/lot_number first")
        add_tc("TC-211-1", "REQ-211", "DataTable shows 12 rows/page with centered pagination",
               "Any list page's table paginates at 12 rows, controls centered at bottom",
               "1. Open any list page (e.g. /devices)\n2. Count visible rows\n3. Check pagination control position",
               "Exactly 12 rows shown; pagination centered below the table", is_automated=True)
        add_tc("TC-212-1", "REQ-212", "Product IQC shows all records via pagination, not capped at 50",
               "A dataset with 4500+ IQC records is fully reachable via pagination",
               "1. Seed/confirm 4500+ IQC rows\n2. Open Product IQC list\n3. Page to the last page",
               "Total record count matches DB count; last page reachable, no 50-row ceiling",
               type_=TestCaseType.regression)
        add_tc("TC-212-2", "REQ-212", "Stress Test / L1-L3 Repair tables paginate (not paging:false)",
               "Previously paging:false tables now paginate normally",
               "1. Open Stress Test / Repair L1 / L2 / L3\n2. Inspect DataTable pagination controls",
               "Pagination controls are present and functional, 12 rows/page")
        add_tc("TC-213-1", "REQ-213", "Add Lot with blank Price and Quantity",
               "Lot can be created leaving Price and Quantity empty",
               "1. Open Add Lot\n2. Leave Buying Price and Quantity blank\n3. Submit",
               "Lot is created with qty=1, buying_price=0; no divide-by-zero error downstream in Sales/IQC")
        add_tc("TC-214-1", "REQ-214", "Dealer bulk upload accepts multi-number phone cell",
               "A phone cell with comma-separated numbers is accepted, not rejected",
               "1. Prepare CSV row with phone = '9876500001, 9988877766'\n2. Bulk upload\n3. Check results",
               "Row is added successfully; phone stored as-is (no truncation error)",
               type_=TestCaseType.negative)
        add_tc("TC-214-2", "REQ-214", "Dealer bulk upload business-name dup check is case-insensitive",
               "'ABC Traders' and 'abc traders' are treated as duplicates",
               "1. Seed dealer 'ABC Traders'\n2. Bulk upload row with business_name='abc traders'",
               "Row is skipped as a duplicate with a clear reason message")
        add_tc("TC-215-1", "REQ-215", "Move Device scan fields accept lowercase/mixed case",
               "Tag Number / Bucket / Lot scan inputs work regardless of case",
               "1. Open Move Device, each of the 3 tabs\n2. Type a known tag/bucket/lot in lowercase\n3. Submit lookup",
               "Lookup succeeds and resolves the correct device/bucket/lot")
        add_tc("TC-216-1", "REQ-216", "Diagnose Agent fills Battery Health % and Storage Health %",
               "Running Diagnose this Device on a real station fills both health fields",
               "1. Run/ensure Diagnose_Device_Agent is current\n2. Click 'Diagnose this Device' on IQC entry\n3. Check Battery Health % and Storage Health %",
               "Both fields are populated with plausible percentages (not blank)",
               type_=TestCaseType.integration)
        add_tc("TC-217-1", "REQ-217", "Re-downloading the agent replaces a running old instance",
               "A newer agent exe successfully evicts and replaces an already-running old one",
               "1. Have an old agent instance running\n2. Download and run the new exe\n3. Hit /ping",
               "/ping reports the new AGENT_VERSION; only one process listens on port 8765")
        add_tc("TC-218-1", "REQ-218", "Mac agent downloads as single .command file",
               "macOS download is one file, no unzip required",
               "1. On the IQC page (mac user-agent), click Download Agent\n2. Inspect downloaded file",
               "A single Diagnose_Device_Agent.command file downloads; double-click runs it directly")
        add_tc("TC-219-1", "REQ-219", "QA Dashboard shows both workflow tabs with all stages",
               "Application Workflow section has Flow 1 and Flow 2 tabs covering full lifecycle",
               "1. Open /qa/\n2. Switch between Flow 1 and Flow 2 tabs\n3. Check for Sourcing, Part Consumption, Warranty flows, etc.",
               "Both tabs render; all named stages (Sourcing, PO, Part GRN, Part Consumption, "
               "Ready to Sale by Telecalling, Sale by Counter Sale Exec, warranty flows, "
               "L3 scrap/replace) are visible")

        await db.flush()

        def add_defect(code, title, module, desc, severity, status, resolved=True,
                        root_cause=None, resolution=None):
            d = QADefect(
                id=uuid.uuid4(), defect_code=code, title=title, module=module,
                description=desc, severity=severity, priority=DefectPriority.p2,
                status=status, environment="Production", reported_by=CREATED_BY,
                reported_at=now - timedelta(days=3), root_cause=root_cause, resolution=resolution,
                resolved_at=(now - timedelta(days=1)) if resolved else None,
                closed_at=(now - timedelta(hours=6)) if resolved else None,
            )
            db.add(d)
            return d

        add_defect("BUG-101", "Product IQC / Ready to Sale only showing 50 of 4500+ records", "IQC / Sales",
                    "Technicians reported only the first 50 records visible despite thousands "
                    "existing in the DB.", DefectSeverity.critical, DefectStatus.closed,
                    root_cause="Backend page_size=50 cap combined with paging:false on several "
                               "DataTables compounded to hide the true record count.",
                    resolution="Converted 9 pages to full-fetch + client pagination; removed "
                               "paging:false from 4 tables.")
        add_defect("BUG-102", "Dealer bulk upload 500s on multi-number phone cell", "Dealers",
                    "After loosening phone validation to accept multi-number cells, upload of "
                    "cells >20 chars crashed with a DB error.", DefectSeverity.high, DefectStatus.closed,
                    root_cause="dealers.phone was VARCHAR(20); multi-number cells overflowed it.",
                    resolution="Widened dealers.phone to VARCHAR(100) via migration + model update.")
        add_defect("BUG-103", "Diagnose Agent update silently ignored on stations with agent already running", "IQC Agent",
                    "Rebuilt agent (with Battery/Storage Health fix) still showed blank health "
                    "fields after being re-downloaded and run.", DefectSeverity.high, DefectStatus.closed,
                    root_cause="Self-install copy2() failed silently because the old resident "
                               "process held the target exe file locked and port 8765 bound.",
                    resolution="Added /quit endpoint + pre-install eviction of any running "
                               "instance, with polling for the port to free before copying.")
        add_defect("BUG-104", "Stress Test / Repair L1-L3 tables ignored pageLength entirely", "QC / Repair",
                    "Even after adding global 12-rows/page default, these 4 tables kept showing "
                    "all rows unpaginated.", DefectSeverity.medium, DefectStatus.closed,
                    root_cause="Tables had paging: false explicitly set in their DataTable init.",
                    resolution="Removed the paging:false override from qc/list.html, repair/l1-l3.html, lots/trc_production.html.")

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

        add_uat("UAT-101", "REQ-212", "Warehouse can page through all Product IQC records",
                "Warehouse lead needs to locate a specific unit anywhere in the full IQC list",
                "Can reach any of 4500+ records via pagination without a hard cap", "Warehouse Lead")
        add_uat("UAT-102", "REQ-214", "Sales ops can bulk-onboard dealers with multiple phone numbers",
                "A dealer has both a mobile and office landline in the same sheet cell",
                "Bulk upload accepts and stores multi-number cells without rejecting the row", "Sales Ops Manager")
        add_uat("UAT-103", "REQ-216", "Technician trusts Diagnose Agent's health readings",
                "Technician runs Diagnose this Device on a laptop with a used battery/SSD",
                "Battery Health % and Storage Health % both populate with realistic values", "QC Supervisor")
        add_uat("UAT-104", "REQ-218", "Mac technician sets up the agent without IT help",
                "A Mac-using technician downloads the agent for the first time",
                "One file download, double-click, agent runs — no unzip or terminal commands needed", "QC Supervisor")
        add_uat("UAT-105", "REQ-219", "QA lead reviews the full app workflow at a glance",
                "QA lead wants a single reference for how a device or part moves through the system",
                "Workflow diagram on QA Dashboard shows every stage from sourcing to warranty return", "QA Lead")

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

        add_release("v1.5.0", "Pagination overhaul + bulk-upload rework",
                     ReleaseStatus.deployed, days_ago_planned=5, days_ago_release=4)
        add_release("v1.6.0", "Device Type/PO Category master-data fixes + Lot optional fields + Dealer bulk-upload validation",
                     ReleaseStatus.deployed, days_ago_planned=3, days_ago_release=2)
        add_release("v1.7.0", "Diagnose Agent accuracy + self-update fix + Mac single-file installer + QA Dashboard workflow",
                     ReleaseStatus.deployed, days_ago_planned=1, days_ago_release=0)

        await db.commit()
        print("Seeded: 11 requirements, 15 test cases, 4 defects, 5 UAT scenarios, 3 releases.")


if __name__ == "__main__":
    asyncio.run(run())
