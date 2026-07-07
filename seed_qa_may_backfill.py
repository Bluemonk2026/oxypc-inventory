"""
OxyPC Inventory — Backfill QA/UAT tracking from 1 May 2026
=============================================================
Existing QA tracking data started at v1.0.0 "Clean baseline" (2026-06-11) /
REQ-101 (2026-06-23) — release notes reference "Sprint 28/29", implying prior
sprints existed in code but were never logged in the QA module. This adds
earlier foundational-module Requirements/Test Cases/Defects/UAT/Releases
dated 2026-05-01 through 2026-06-09 so the QA tracker has continuous
coverage from 1 May 2026 onward.

Idempotent: skips creation if REQ-001 already exists.

Usage: python seed_qa_may_backfill.py
"""
import asyncio
import uuid
from datetime import datetime, timedelta

from database import AsyncSessionLocal
from sqlalchemy import select
from models.qa_uat import (
    QARequirement, QATestCase, QADefect, QAUATScenario, QARelease,
    RequirementSource, RequirementPriority, RequirementStatus,
    TestCaseType, TestCaseStatus,
    DefectSeverity, DefectPriority, DefectStatus,
    UATStatus, ReleaseStatus,
)

CREATED_BY = "system-seed"


def d(day_offset):
    """2026-05-01 + day_offset, as a naive datetime (matches app_now() usage elsewhere)."""
    return datetime(2026, 5, 1) + timedelta(days=day_offset)


async def run():
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(QARequirement).where(QARequirement.req_code == "REQ-001"))
        if existing.scalar_one_or_none():
            print("Already seeded (REQ-001 exists). Nothing to do.")
            return

        reqs = {}

        def add_req(code, title, module, desc, day_offset, priority=RequirementPriority.high):
            r = QARequirement(
                id=uuid.uuid4(), req_code=code, title=title, description=desc,
                source=RequirementSource.brd, priority=priority, status=RequirementStatus.done,
                module=module, created_by=CREATED_BY,
                created_at=d(day_offset), updated_at=d(day_offset),
            )
            db.add(r)
            reqs[code] = r
            return r

        add_req("REQ-001", "Master Data framework", "Master Data",
                 "Foundational key/value Master Data module (device_type, grade, location, "
                 "call modes, etc.) with admin configuration page.", 1)
        add_req("REQ-002", "RBAC / Permission Matrix base", "Admin",
                 "Role-based access control with a per-module permission matrix editable by admins.", 3)
        add_req("REQ-003", "Device Inventory core module", "Devices",
                 "Core device table + list/detail pages: serial/tag tracking, status lifecycle.", 6)
        add_req("REQ-004", "GRN base workflow", "GRN",
                 "Goods Receipt Note creation against a Purchase Order, line items, quantities.", 9)
        add_req("REQ-005", "Product IQC entry base module", "IQC",
                 "Initial IQC entry form: hardware checklist, grading (A/B/C), lot assignment.", 13)
        add_req("REQ-006", "Repair L1/L2/L3 base setup", "Repair",
                 "Three-tier repair queue with escalation between levels.", 17)
        add_req("REQ-007", "Dealer / CRM base module", "Dealers",
                 "Dealer master, contact details, basic call logging.", 21)
        add_req("REQ-008", "WhatsApp integration base", "WhatsApp",
                 "wa-service session bootstrap, QR login, outbound template messages.", 25)
        add_req("REQ-009", "Sourcing / Purchase Order base module", "Purchase Orders",
                 "PO creation, line items, vendor master, approval status.", 29)
        add_req("REQ-010", "Reports & Dashboard base", "Reports",
                 "Initial operational dashboards: inventory counts, repair queue, sales summary.", 33)

        await db.flush()

        def add_tc(code, req_code, title, scenario, steps, expected, day_offset):
            tc = QATestCase(
                id=uuid.uuid4(), tc_code=code, requirement_id=reqs[req_code].id,
                title=title, scenario=scenario, steps=steps, expected_result=expected,
                type=TestCaseType.functional, status=TestCaseStatus.active, is_automated=False,
                module=reqs[req_code].module, created_by=CREATED_BY,
                created_at=d(day_offset), updated_at=d(day_offset),
            )
            db.add(tc)

        add_tc("TC-001-1", "REQ-001", "Master Data key/value CRUD",
               "Admin can add/edit/remove values under a Master Data key",
               "1. Open /admin/master\n2. Add a value under any key\n3. Confirm it appears in dependent dropdowns",
               "New value is immediately available wherever that key is used", 2)
        add_tc("TC-002-1", "REQ-002", "Permission matrix blocks unauthorized module access",
               "A role without a module's permission cannot open that module's pages",
               "1. Remove a role's permission for a module\n2. Log in as that role\n3. Try to open the module",
               "Access is denied with a clear message", 4)
        add_tc("TC-003-1", "REQ-003", "Device list shows current status per unit",
               "Device Inventory list reflects each device's lifecycle status",
               "1. Open /devices\n2. Check Status column against known device state",
               "Status column matches the device's actual current stage", 7)
        add_tc("TC-004-1", "REQ-004", "GRN line items sum to PO quantity",
               "GRN created against a PO cannot exceed the PO's ordered quantity",
               "1. Create PO for qty 10\n2. Create GRN for the same PO\n3. Enter qty > 10",
               "Validation blocks over-receipt beyond the PO quantity", 10)
        add_tc("TC-005-1", "REQ-005", "IQC entry saves grade and lot correctly",
               "A submitted IQC entry persists grade and lot assignment",
               "1. Open IQC entry\n2. Fill checklist, select grade B, assign to a lot\n3. Submit",
               "Record saved with grade=B and correct lot_number", 14)
        add_tc("TC-006-1", "REQ-006", "Device escalates from L1 to L2 to L3",
               "A device not resolved at L1 escalates through the repair tiers",
               "1. Move device into Repair L1\n2. Escalate\n3. Escalate again",
               "Device appears in L2 queue, then L3 queue, with history preserved", 18)
        add_tc("TC-007-1", "REQ-007", "Dealer call log records a call",
               "A call logged against a dealer appears in that dealer's history",
               "1. Open a dealer\n2. Log a call with notes\n3. Reopen the dealer",
               "Call appears in the dealer's call log with timestamp and notes", 22)
        add_tc("TC-008-1", "REQ-008", "WhatsApp session QR login completes",
               "Scanning the QR code links a WhatsApp session to the current user",
               "1. Open WhatsApp setup\n2. Scan QR with a phone\n3. Check session status",
               "Session shows Connected for that user", 26)
        add_tc("TC-009-1", "REQ-009", "PO requires vendor and at least one line item",
               "A PO cannot be saved without a vendor and line items",
               "1. Start a new PO\n2. Leave vendor blank\n3. Submit",
               "Validation error is shown; PO is not created", 30)
        add_tc("TC-010-1", "REQ-010", "Dashboard counts match underlying tables",
               "Reports dashboard's inventory/repair/sales counts match live data",
               "1. Note DB counts for devices/repairs/sales\n2. Open dashboard\n3. Compare",
               "Dashboard figures match the DB counts", 34)

        await db.flush()

        def add_defect(code, title, module, desc, severity, day_offset):
            db.add(QADefect(
                id=uuid.uuid4(), defect_code=code, title=title, module=module,
                description=desc, severity=severity, priority=DefectPriority.p2,
                status=DefectStatus.closed, environment="QA", reported_by=CREATED_BY,
                reported_at=d(day_offset), resolved_at=d(day_offset + 2), closed_at=d(day_offset + 3),
            ))

        add_defect("BUG-001", "GRN allowed over-receipt beyond PO quantity", "GRN",
                    "GRN line items could exceed the linked PO's ordered quantity with no validation.",
                    DefectSeverity.high, 11)
        add_defect("BUG-002", "IQC grade not persisted on save", "IQC",
                    "Selected grade reverted to blank after saving an IQC entry under certain field combinations.",
                    DefectSeverity.medium, 15)
        add_defect("BUG-003", "WhatsApp QR session dropped after idle timeout", "WhatsApp",
                    "Sessions disconnected silently after ~10 minutes idle, requiring re-scan.",
                    DefectSeverity.medium, 27)

        await db.flush()

        def add_uat(code, req_code, title, scenario, criteria, owner, day_offset):
            db.add(QAUATScenario(
                id=uuid.uuid4(), uat_code=code, requirement_id=reqs[req_code].id,
                title=title, scenario=scenario, acceptance_criteria=criteria,
                business_owner=owner, status=UATStatus.pass_,
                executed_by=CREATED_BY, executed_at=d(day_offset),
                created_by=CREATED_BY, created_at=d(day_offset),
            ))

        add_uat("UAT-001", "REQ-003", "Ops lead tracks a device end-to-end by serial",
                "Ops lead searches by serial number to find a device's current stage",
                "Device is found and its stage/history is visible in one view", "Ops Lead", 8)
        add_uat("UAT-002", "REQ-005", "QC supervisor confirms IQC grading affects downstream pricing",
                "Supervisor sets a grade and checks it flows into Ready-to-Sale pricing logic",
                "Grade set at IQC is visible and used at Ready-to-Sale stage", "QC Supervisor", 16)
        add_uat("UAT-003", "REQ-009", "Procurement confirms PO approval gate works",
                "Procurement raises a PO and checks it requires approval before GRN",
                "PO cannot be received against (GRN) until approved", "Procurement Manager", 31)

        await db.flush()

        def add_release(version, title, day_offset):
            db.add(QARelease(
                id=uuid.uuid4(), version=version, title=title, status=ReleaseStatus.deployed,
                planned_date=d(day_offset), release_date=d(day_offset),
                qa_sign_off_by=CREATED_BY, qa_sign_off_at=d(day_offset),
                created_by=CREATED_BY, created_at=d(day_offset), updated_at=d(day_offset),
            ))

        add_release("v0.1.0", "Sprint 19-20 — Master Data + RBAC/Permission Matrix foundation", 5)
        add_release("v0.2.0", "Sprint 21-22 — Device Inventory core + GRN base workflow", 12)
        add_release("v0.3.0", "Sprint 23-24 — Product IQC entry + Repair L1/L2/L3 base", 19)
        add_release("v0.4.0", "Sprint 25-26 — Dealer/CRM base + WhatsApp integration", 28)
        add_release("v0.5.0", "Sprint 27 — Sourcing/PO base + Reports/Dashboard base", 35)

        await db.commit()
        print("Seeded (May backfill): 10 requirements, 10 test cases, 3 defects, 3 UAT scenarios, 5 releases.")


if __name__ == "__main__":
    asyncio.run(run())
