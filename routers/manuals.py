"""
Learning Manuals
================
GET  /manuals/              — List all learning manuals
GET  /manuals/{mid}/download — Download PDF for a manual
POST /manuals/{mid}/share    — Share manual with a user (notification)
"""
from __future__ import annotations

import io
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_user, verify_csrf
from database import get_db
from models.user import User
from models.notification import Notification
from templates_config import templates

router = APIRouter(prefix="/manuals", tags=["manuals"])

_MANUALS_DIR = Path(__file__).resolve().parent.parent / "static" / "manuals"
try:
    _MANUALS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass


# ── Manual content definitions ────────────────────────────────────────────────

MANUALS = [
    {
        "id": 1,
        "module": "Stock Intake & Lot Management",
        "icon": "bi-box-seam",
        "color": "primary",
        "description": "Create lots, receive stock inwards, and manage lot-level tracking.",
        "steps": [
            ("Create a New Lot", [
                "Go to Intake → Lot Overview in the left navigation.",
                "Click 'New Lot' at the top right.",
                "Fill in: Lot Name, Source (Supplier), Expected Device Count, Purchase Date, and Remarks.",
                "Click 'Create Lot' to save. The lot appears in the Lot Overview list.",
            ]),
            ("Stock Inward Entry", [
                "Go to Inventory → Stock Inwards.",
                "Select the Lot from the dropdown.",
                "Enter each device's Tag Number (barcode), Brand, and Model.",
                "Click 'Add Device' for each unit.",
                "Once all devices are entered, click 'Confirm Stock In'.",
            ]),
            ("View Lot Details", [
                "In Lot Overview, click any lot name to open the detail page.",
                "The detail page shows: device count, stage-wise breakdown, GRN status, and full device list.",
                "Use 'Export' to download the lot's device list as Excel.",
            ]),
            ("GRN with Invoice", [
                "Go to Intake → GRN with Invoice.",
                "Select the lot and upload the supplier invoice PDF.",
                "Enter: Invoice Number, Date, Total Value, and Per-Device Cost.",
                "Click 'Save GRN' to record the financial receipt.",
            ]),
        ],
        "tips": [
            "Always create the Lot BEFORE entering devices — every device must belong to a lot.",
            "Tag Numbers must be unique across the entire system. Duplicates are blocked.",
            "Mark a lot as 'Closed' once all devices have completed the workflow.",
        ],
    },
    {
        "id": 2,
        "module": "IQC (Incoming Quality Check)",
        "icon": "bi-clipboard-check",
        "color": "warning",
        "description": "Perform hardware inspection and grade devices at point of entry.",
        "steps": [
            ("Open the IQC Form", [
                "Go to Intake → IQC Line Items.",
                "Click 'IQC' next to a device that has not yet been inspected.",
                "The IQC form opens pre-filled with the device's basic info from Stock Inward.",
            ]),
            ("Run OxyQC Agent for Auto-Detection", [
                "Download and install the OxyQC Agent on the device being tested.",
                "Click 'Diagnose' in the IQC form — the agent auto-fills CPU, RAM, Storage, Battery Health, and ports.",
                "Review the auto-filled values and correct any that appear incorrect.",
            ]),
            ("Fill Fields Manually (if agent unavailable)", [
                "Device Type, Brand, Model, Serial Number (mandatory for compliance).",
                "RAM (GB), Storage (GB), Storage Type, CPU, Generation.",
                "Battery Health %, Storage Health (SSD) %, Fan Sound (dB).",
                "Screen Size (inches), Color.",
            ]),
            ("Functional & Cosmetic Check", [
                "Check all Yes/No fields: Power On, Keyboard, Touchpad, Webcam, Wi-Fi, Speakers.",
                "Enter port counts: USB-A, USB-C, Ethernet, HDMI, Audio Jack.",
                "Record display defects: Dot, Line, Discoloration, Flickering, Scratch, Broken, etc.",
                "Fill keyboard, touchpad, and body panel condition fields (scratch, dent, missing, etc.).",
            ]),
            ("Assign Grade and Save", [
                "Assign Grade: A (Excellent), B (Good with minor defects), or C (Acceptable).",
                "Select R2V3 Grade Category for compliance documentation.",
                "Select Floor and Warehouse where the device will be stored.",
                "Click 'Save IQC Entry'. The device moves to the next workflow stage automatically.",
            ]),
        ],
        "tips": [
            "Grade A: No visible defects, all functions working perfectly.",
            "Grade B: Minor cosmetic defects only — fully functional.",
            "Grade C: Functional but with notable cosmetic issues.",
            "Storage Health below 80% should be flagged — consider SSD replacement.",
            "Serial Number is mandatory — required for data-wipe certificates and compliance.",
        ],
    },
    {
        "id": 3,
        "module": "GRN Post IQC",
        "icon": "bi-receipt",
        "color": "info",
        "description": "Link IQC-completed devices to financial GRN records for cost tracking.",
        "steps": [
            ("Access GRN Post IQC", [
                "Go to Intake → GRN post IQC in the left navigation.",
                "This page lists devices that have completed IQC and are awaiting GRN mapping.",
            ]),
            ("Map Devices to GRN", [
                "Click 'Map this GRN' next to a device.",
                "Select the invoice/GRN record from the dropdown.",
                "Confirm lot number and device details.",
                "Click 'Save Mapping' to link the device to the financial record.",
            ]),
            ("View GRN Records", [
                "Go to Intake → GRN Records to view all mapped devices.",
                "Filter by Lot, Date, or Supplier to find specific records.",
                "Export records as Excel for accounts reconciliation.",
            ]),
        ],
        "tips": [
            "GRN mapping is required for financial reporting and per-device cost tracking.",
            "Devices without a GRN mapping show as 'GRN Pending' in reports.",
            "Always complete GRN mapping before closing a lot.",
        ],
    },
    {
        "id": 4,
        "module": "L1 Repair",
        "icon": "bi-tools",
        "color": "danger",
        "description": "First-level repair: cleaning, basic fixes, and minor part replacements.",
        "steps": [
            ("View the L1 Queue", [
                "Go to Repair → L1 Repair in the left navigation.",
                "The queue shows all devices currently assigned to L1 repair.",
                "Devices arrive here after IQC flags basic repair needs.",
            ]),
            ("Start Repair", [
                "Click 'Start Repair' on the device you are working on.",
                "Status changes to 'In Progress' and records your name and start time.",
            ]),
            ("Log Repair Work and Parts", [
                "In the repair form, describe the work performed in the Notes field.",
                "Select the Repair Type: Cleaning, Part Replacement, Configuration, etc.",
                "If parts are needed: click 'New Request' under Parts Consumption to raise a request.",
                "After receiving the part, replace it and mark the part as 'Changed'.",
            ]),
            ("Complete or Escalate", [
                "If repair is complete: set Final Status to 'Repaired', add notes, click 'Complete'.",
                "If beyond L1 scope: click 'Escalate to L2' to move the device to the L2 queue.",
                "If device is uneconomical to repair: mark as 'Scrap' (requires manager approval).",
            ]),
        ],
        "tips": [
            "Always log parts used — this feeds directly into Parts Consumption cost reports.",
            "Escalate early if the issue requires board-level diagnosis.",
            "L1 target: 30-60 minutes per device average.",
        ],
    },
    {
        "id": 5,
        "module": "L2 Repair",
        "icon": "bi-cpu",
        "color": "danger",
        "description": "Second-level repair: motherboard, display, and advanced component work.",
        "steps": [
            ("View the L2 Queue", [
                "Go to Repair → L2 Repair.",
                "Devices here were escalated from L1 or directly assigned after IQC.",
            ]),
            ("Diagnose and Plan", [
                "Review the L1 notes and IQC report attached to the device.",
                "Run component-level diagnostics using appropriate tools.",
                "Document the root cause in the Repair Notes field before starting work.",
            ]),
            ("Repair and Request Parts", [
                "Perform board-level or display-level repair work.",
                "Raise part requests for any components needed via 'New Request'.",
                "Mark each part as 'Changed' after replacement.",
            ]),
            ("Resolve or Escalate to L3", [
                "Mark as 'Repaired' if fixed — device moves to the Cosmetic stage.",
                "Escalate to L3 if the issue requires data recovery or micro-soldering.",
                "Mark as 'Cannot Repair' only after exhausting all available repair options.",
            ]),
        ],
        "tips": [
            "Check voltage rails before replacing major components.",
            "Photograph damaged components before and after repair for the repair record.",
            "Target turnaround: 1-3 days for L2 cases depending on part availability.",
        ],
    },
    {
        "id": 6,
        "module": "L3 Repair & Device Replacement",
        "icon": "bi-arrow-repeat",
        "color": "danger",
        "description": "Advanced repair, data recovery, and warranty device replacement handling.",
        "steps": [
            ("View the L3 Queue", [
                "Go to Repair → L3 Repair.",
                "These are the most complex cases: data recovery, micro-soldering, or unrepairable units.",
            ]),
            ("Device Replacement Workflow", [
                "If a device needs to be replaced (e.g., warranty replacement):",
                "  1. Open the original device's detail page.",
                "  2. Click 'Process Return' in the device timeline.",
                "  3. Select Return Type: 'Device Replace'.",
                "  4. Enter the Tag Number of the replacement device.",
                "  5. Save — the original is marked Replaced; the replacement is linked.",
            ]),
            ("Data Recovery Process", [
                "Connect the storage media to the recovery workstation.",
                "Run the data extraction process per lab SOP.",
                "Document data recovery status: Recovered / Partial / Not Possible.",
                "Attach the data status certificate to the repair record.",
            ]),
        ],
        "tips": [
            "L3 cases marked as 'Scrap' require director approval.",
            "All L3 replacements affect COGS and must be documented for warranty reporting.",
            "Never attempt micro-soldering without proper ESD protection.",
        ],
    },
    {
        "id": 7,
        "module": "Cosmetic Refurbishment & Final QC",
        "icon": "bi-brush",
        "color": "success",
        "description": "Clean and refurbish devices cosmetically, then perform final quality check.",
        "steps": [
            ("Cosmetic Pipeline Stages", [
                "Devices flow through: Cleaning → Panel Repair → Painting → Sticker Removal → Final QC.",
                "Go to the Cosmetic section to see the full pipeline and stage counts.",
                "Click each stage tab to see devices currently in that stage.",
            ]),
            ("Send to Cleaning and Advance Through Stages", [
                "From the QC list, click 'Go Cleaning' to send a device to the Cleaning stage.",
                "After completing each stage, click 'Advance' or the stage-move button.",
                "Every stage move is logged with timestamp and the user who moved it.",
            ]),
            ("Final QC Check", [
                "In the Final QC stage, each device is shown as an accordion card.",
                "Expand the card to see: full IQC details (read-only), repair history, parts consumed.",
                "Review all details, then complete the Final QC Decision form:",
                "  - Final Status: Pass or Fail",
                "  - Failure Reason (if fail): Functional / Paint / Plastic Part",
                "  - Final Grade: A, B, or C (can override IQC grade)",
                "  - Notes: optional remarks",
                "Click 'Final QC → Ready to Sale' to move the device to the sale queue.",
            ]),
            ("Skip Cosmetic Stage", [
                "If a device requires no cosmetic work, click 'Skip Cosmetic'.",
                "The device goes directly to Final QC, bypassing all cosmetic stages.",
            ]),
        ],
        "tips": [
            "Grade A devices must have no screen scratches and clean body panels before Final QC.",
            "Always verify that all 'Required' parts show 'Changed' before passing Final QC.",
            "Failed devices return to Repair — never approve a fail to meet shipment targets.",
        ],
    },
    {
        "id": 8,
        "module": "QC Check & Stress Test",
        "icon": "bi-speedometer",
        "color": "secondary",
        "description": "Run QC verification and hardware stress tests before dispatch.",
        "steps": [
            ("QC Verification", [
                "Go to Repair → Stress Test (QC) to see devices pending QC.",
                "Click 'Verify QC' to open the QC inspection for a device.",
                "Verify: functional checks, cosmetic grade, serial number match, and IQC data.",
                "Click 'Approve QC' to pass, or 'Send to Repair' to send back for rework.",
            ]),
            ("Run Stress Test", [
                "On the QC device list, click 'Stress Test' in the action panel.",
                "Select test duration: Quick (5 min), Standard (15 min), or Thorough (30 min).",
                "Click 'Start Stress Test'. Tests run automatically on the connected server.",
                "Tests cover: CPU Load, RAM, Storage Read/Write, Battery, Temperature, Network.",
            ]),
            ("Review Stress Test Results", [
                "Results appear live as each test completes: PASS / WARN / FAIL.",
                "Overall result: PASS (all green), PASS WITH WARNINGS (some warns), or FAIL.",
                "Click 'Save Report' to store results linked to the device.",
                "Click 'Download Report' to get a PDF report for documentation.",
            ]),
        ],
        "tips": [
            "Devices with any FAIL stress result must return to repair before dispatch.",
            "WARN results — use judgment: minor thermal warn on old hardware may be acceptable.",
            "Grade A devices must pass the full Thorough stress test before dispatch.",
        ],
    },
    {
        "id": 9,
        "module": "TRC Dashboard & Dispatch",
        "icon": "bi-truck",
        "color": "dark",
        "description": "Manage dispatch-ready devices, telecaller requests, and return tracking.",
        "steps": [
            ("TRC Dashboard Overview", [
                "Go to TRC Dashboard from the left navigation.",
                "Top KPI cards show Grade A/B/C device counts with Dispatched/Pending/Sold breakdown.",
                "The 'Total Ready to Sale' card shows inventory age bands: ≤15d, 16-30d, 31-45d, 46-60d, >60d.",
            ]),
            ("Approve Telecaller Requests", [
                "Telecallers submit device requests for customers from the sales app.",
                "Admin and Sales Manager see these requests in the 'Telecaller Requests' table.",
                "Click 'Approve' to authorize the request — the device is reserved for that customer.",
            ]),
            ("Browse Grade Inventory", [
                "Grade A, B, and C devices are shown in separate accordion sections.",
                "Each row: Tag Number (clickable), Model, Quantities, Dispatched, Pending, Sold, Timeline, Warranty.",
                "Devices over 30 days show a yellow timeline badge; over 60 days shows red.",
            ]),
            ("Devices Returned Section", [
                "The bottom section shows returned devices split by warranty status.",
                "Within Warranty: returned within the 30-day warranty period.",
                "Out of Warranty: returned after warranty has expired.",
            ]),
        ],
        "tips": [
            "Devices aged 30+ days in Ready to Sale are yellow alerts — investigate selling bottlenecks.",
            "Devices aged 60+ days are red — escalate to management for review or repricing.",
        ],
    },
    {
        "id": 10,
        "module": "Sales & CRM",
        "icon": "bi-bag-check",
        "color": "success",
        "description": "Record sales, manage customer contacts, create quotes, and track the pipeline.",
        "steps": [
            ("Record a Sale", [
                "Go to CRM → Sales and click 'New Sale'.",
                "Select the Device (Tag Number), Customer/Dealer, Sale Price, and Payment Mode.",
                "Enter Quantity and confirm.",
                "Device status changes to 'Sold' automatically.",
            ]),
            ("Manage Contacts", [
                "Go to CRM → Contacts to manage customers and enterprise prospects.",
                "Use 'Import' to bulk-upload contacts from Excel.",
                "Each contact stores: Company, Name, Phone, Email, Category, and Follow-up schedule.",
            ]),
            ("Create and Send a Quote", [
                "Go to CRM → Quotes and click 'New Quote'.",
                "Add line items (devices or accessories), apply discount, and set valid-until date.",
                "Click 'Print' to download/print the quote as a formatted PDF.",
            ]),
            ("Track the Sales Pipeline", [
                "Go to CRM → Sourcing to track deals in the pipeline.",
                "Move deals through stages: Lead → Qualified → Proposal → Negotiation → Won/Lost.",
                "Set follow-up dates on active deals to ensure no opportunity is missed.",
            ]),
        ],
        "tips": [
            "Always link a sale to a contact — unlinked sales are excluded from CRM funnel reports.",
            "Use the Win/Loss report in CRM → Reports to analyze why deals are being lost.",
        ],
    },
    {
        "id": 11,
        "module": "Dealer Management",
        "icon": "bi-people",
        "color": "info",
        "description": "Manage wholesale dealers, track orders, ledgers, and follow-up schedules.",
        "steps": [
            ("Add a New Dealer", [
                "Go to Dealers from the left navigation.",
                "Click 'New Dealer'.",
                "Fill in: Company Name, Contact Person, Phone, City, Credit Limit, Payment Terms.",
                "Click 'Save Dealer'.",
            ]),
            ("Place a Dealer Order", [
                "Open the dealer's profile and click 'New Order'.",
                "Select devices, quantities, and price per unit.",
                "Save to generate an order invoice that can be printed.",
            ]),
            ("Dealer Ledger and Payments", [
                "In the dealer profile, click 'Ledger' to see all transactions.",
                "Ledger shows: invoices raised, payments received, and outstanding balance.",
                "Record payments received via Accounts → Customer Receipts.",
            ]),
            ("Log Telecalling Activity", [
                "Use 'Log Call' in the dealer profile to record call notes and outcomes.",
                "Set follow-up date and priority level.",
                "All call history is visible in the 'Call Logs' tab on the dealer profile.",
            ]),
        ],
        "tips": [
            "Review Dealers → Ageing Report weekly to identify overdue accounts.",
            "Dealers with 30+ day overdue balances should be escalated for collection.",
            "Credit limits are enforced at order creation — contact admin to update limits.",
        ],
    },
    {
        "id": 12,
        "module": "Spare Parts Management",
        "icon": "bi-gear",
        "color": "secondary",
        "description": "Manage spare parts inventory, fulfil requests, and track consumption.",
        "steps": [
            ("Add Parts to Inventory", [
                "Go to Spare Parts from the left navigation.",
                "Click 'Add Part' and fill in: Part Name, Category, Unit, Stock Quantity, Reorder Level.",
                "Save to add the part to inventory.",
            ]),
            ("Raise a Part Request (Engineer)", [
                "From the device detail page, scroll to Parts Consumption.",
                "Click 'New Request' for the required part, enter quantity, and submit.",
                "The request goes to the Spare Parts Manager queue for fulfilment.",
            ]),
            ("Fulfil a Part Request (Spare Parts Manager)", [
                "Go to Spare Parts → Part Requests.",
                "Click 'Fulfil' next to a pending request.",
                "Select from available stock, or mark 'Procure' if the part is out of stock.",
                "Fulfilled parts are automatically deducted from stock.",
            ]),
            ("Record Part Purchase", [
                "Go to Spare Parts → Purchase to log new stock received.",
                "Enter Supplier, Quantity, Unit Cost, and Invoice Number.",
                "Stock quantity is updated automatically on save.",
            ]),
        ],
        "tips": [
            "Set reorder levels for high-usage parts to receive alerts before stock-out.",
            "Review Parts Consumption monthly to identify which repairs drive the highest cost.",
            "Track the 'Replace' requests separately from 'New Request' to measure re-repair rate.",
        ],
    },
    {
        "id": 13,
        "module": "Warehouse & Locations",
        "icon": "bi-building",
        "color": "primary",
        "description": "Track physical device locations by floor, rack, and bin across warehouses.",
        "steps": [
            ("Location Dashboard", [
                "Go to Inventory → Warehouse from the left navigation.",
                "The dashboard shows device counts by floor, rack, and bin.",
            ]),
            ("Assign Device Location", [
                "During IQC, select Floor and Warehouse at the bottom of the IQC form.",
                "To change a device location later: open the device detail → use 'Move Device'.",
            ]),
            ("Run a Location Audit", [
                "Go to Warehouse → Location Audit.",
                "At each physical bin, scan or enter each device's Tag Number.",
                "The system highlights mismatches between physical location and system location.",
                "View all discrepancies in Warehouse → Gaps Report.",
            ]),
        ],
        "tips": [
            "Run a location audit for Grade A devices at least once a month.",
            "Always update the system when physically moving a device — untracked moves cause audit failures.",
            "Use the 'Find Device' lookup to quickly locate a specific Tag Number.",
        ],
    },
    {
        "id": 14,
        "module": "Reports & Analytics",
        "icon": "bi-bar-chart",
        "color": "dark",
        "description": "Access P&L, lot profitability, receivables, and inventory analytics.",
        "steps": [
            ("Business P&L Report", [
                "Go to Reports → Business P&L.",
                "Select the date range and click 'Generate Report'.",
                "Report shows: Revenue, COGS, Gross Profit, and Margin % for the selected period.",
            ]),
            ("Lot P&L Report", [
                "Go to Reports → Lot P&L and select a lot from the dropdown.",
                "Report shows: Purchase Cost, Repair Cost, Sale Revenue, and Net Profit per lot.",
                "Compare target vs. actual margin to evaluate sourcing decisions.",
            ]),
            ("Receivables Report", [
                "Go to Reports → Receivables.",
                "Shows outstanding dealer balances with ageing buckets: 0-30d, 31-60d, >60d.",
                "Export as Excel for the accounts team.",
            ]),
        ],
        "tips": [
            "Run Lot P&L on every closed lot to evaluate actual vs. estimated profitability.",
            "Share Receivables with the finance team every Monday.",
            "Business P&L is best reviewed monthly — weekly fluctuations can be misleading.",
        ],
    },
    {
        "id": 15,
        "module": "Admin & User Management",
        "icon": "bi-shield-check",
        "color": "dark",
        "description": "Manage users, roles, module permissions, and system configuration.",
        "steps": [
            ("Create a New User", [
                "Go to Admin → Users and click 'Add User'.",
                "Fill in: Username (unique, no spaces), Full Name, Email, WhatsApp Number, Role, Password.",
                "Click 'Create User' to save. The user can log in immediately.",
            ]),
            ("Role Reference Guide", [
                "Admin: Full access — user management, all modules, reports, settings.",
                "Inventory Manager: Lots, Stock In, IQC, stage movement, reports.",
                "IQC Inspector: IQC entry and stage movement only.",
                "L1/L2/L3 Engineer: Respective repair stages and parts.",
                "QC Inspector: QC check, stress test, dashboard.",
                "Sales: Ready to Sale, CRM, returns.",
                "Spare Parts Manager: Parts inventory and part request fulfilment.",
            ]),
            ("Module Permissions", [
                "Go to Admin → Permissions.",
                "Toggle each module on/off per role as needed.",
                "Changes take effect immediately — no restart required.",
            ]),
            ("System Settings and Backup", [
                "Go to Admin → Settings to configure: Company Name, Logo, Currency, defaults.",
                "Automatic backups run nightly. Check backup status in Settings.",
                "Audit logs for all admin actions are in Admin → System Audit Log.",
            ]),
        ],
        "tips": [
            "Never share admin credentials — create individual accounts for each team member.",
            "Review user access quarterly and disable inactive accounts.",
            "Always assign the most restrictive role appropriate for the user's function.",
        ],
    },
]

_MANUAL_MAP = {m["id"]: m for m in MANUALS}


# ── PDF generation ────────────────────────────────────────────────────────────

def _generate_pdf(manual: dict) -> bytes:
    try:
        from fpdf import FPDF
        return _pdf_fpdf(manual)
    except Exception:
        return _pdf_text(manual)


def _pdf_fpdf(manual: dict) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    # ── Header ──────────────────────────────────────────────────────────────
    pdf.set_fill_color(30, 30, 30)
    pdf.rect(0, 0, 210, 30, "F")
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(255, 255, 255)
    pdf.set_y(9)
    pdf.cell(0, 8, "OxyPC — Learning Manual", align="C")
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(180, 180, 180)
    pdf.cell(0, 5, "Operational Training Guide", align="C")
    pdf.ln(18)

    # ── Module title ─────────────────────────────────────────────────────────
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, manual["module"], ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(80, 80, 80)
    pdf.multi_cell(0, 6, manual["description"])
    pdf.ln(4)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(4)

    # ── Steps ────────────────────────────────────────────────────────────────
    pdf.set_text_color(0, 0, 0)
    for step_idx, (step_title, step_items) in enumerate(manual["steps"], 1):
        # Step heading
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 7, f"  Step {step_idx}: {step_title}", fill=True, ln=True)
        pdf.ln(1)
        # Step sub-items
        pdf.set_font("Helvetica", "", 9)
        for item in step_items:
            if item.startswith("  "):
                pdf.set_x(25)
                pdf.cell(4, 6, "-", border=0)
                pdf.multi_cell(0, 6, item.strip())
            else:
                pdf.set_x(20)
                pdf.cell(4, 6, "-", border=0)
                pdf.multi_cell(0, 6, item)
        pdf.ln(3)

    # ── Tips ─────────────────────────────────────────────────────────────────
    if manual.get("tips"):
        pdf.set_fill_color(255, 243, 205)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 7, "  Tips & Best Practices", fill=True, ln=True)
        pdf.ln(1)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(100, 80, 0)
        for tip in manual["tips"]:
            pdf.set_x(20)
            pdf.cell(4, 6, "*", border=0)
            pdf.multi_cell(0, 6, tip)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

    # ── Footer ───────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, "OxyPC Inventory System — Confidential Training Document", align="C")

    return bytes(pdf.output())


def _pdf_text(manual: dict) -> bytes:
    lines = [
        "OxyPC Learning Manual",
        "=" * 60,
        f"Module: {manual['module']}",
        f"Description: {manual['description']}",
        "",
    ]
    for idx, (title, items) in enumerate(manual["steps"], 1):
        lines.append(f"Step {idx}: {title}")
        lines.append("-" * 40)
        for item in items:
            lines.append(f"  - {item.strip()}")
        lines.append("")
    if manual.get("tips"):
        lines.append("Tips & Best Practices")
        lines.append("-" * 40)
        for tip in manual["tips"]:
            lines.append(f"  * {tip}")
    return "\n".join(lines).encode("utf-8")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def manuals_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Fetch all active users for the share dropdown
    res = await db.execute(
        select(User).where(User.status == True).order_by(User.full_name)
    )
    users = res.scalars().all()

    shared = request.query_params.get("shared")
    return templates.TemplateResponse("manuals/index.html", {
        "request": request,
        "current_user": current_user,
        "manuals": MANUALS,
        "users": users,
        "shared": shared,
    })


@router.get("/{mid}/download")
async def download_manual(
    mid: int,
    current_user: User = Depends(get_current_user),
):
    manual = _MANUAL_MAP.get(mid)
    if not manual:
        raise HTTPException(404, "Manual not found")

    # Serve from cache if available
    cache_path = _MANUALS_DIR / f"manual_{mid}.pdf"
    if cache_path.exists():
        pdf_bytes = cache_path.read_bytes()
    else:
        pdf_bytes = _generate_pdf(manual)
        try:
            cache_path.write_bytes(pdf_bytes)
        except Exception:
            pass

    slug = manual["module"].lower().replace(" ", "_").replace("&", "and").replace("/", "_")
    try:
        from fpdf import FPDF  # noqa
        media_type = "application/pdf"
        filename = f"OxyPC_Manual_{slug}.pdf"
    except ImportError:
        media_type = "text/plain"
        filename = f"OxyPC_Manual_{slug}.txt"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{mid}/share", dependencies=[Depends(verify_csrf)])
async def share_manual(
    mid: int,
    request: Request,
    target_user_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manual = _MANUAL_MAP.get(mid)
    if not manual:
        raise HTTPException(404, "Manual not found")

    # Verify target user exists
    res = await db.execute(select(User).where(User.id == target_user_id))
    target = res.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User not found")

    notif = Notification(
        user_id=target.id,
        title=f"Learning Manual Shared: {manual['module']}",
        message=(
            f"{current_user.full_name or current_user.username} shared the "
            f"'{manual['module']}' learning manual with you. "
            f"Download it from Manuals in the left navigation."
        ),
        notification_type="info",
        stage="Manuals",
    )
    db.add(notif)
    await db.commit()

    return RedirectResponse(f"/manuals/?shared={manual['module']}", status_code=303)
