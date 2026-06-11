/**
 * OxyPC Inventory — Complete Training Module Generator
 * Run:  node docs/generate_training.js
 * Out:  docs/OxyPC_Training_Complete.docx
 */
"use strict";

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
  PageBreak, LevelFormat, Header, Footer, PageNumber,
  TableOfContents
} = require("docx");
const fs = require("fs");
const path = require("path");

// ─── Colours ─────────────────────────────────────────────────────────────────
const CLR = {
  brand:    "1A3C6B",  // deep navy
  accent:   "E8722A",  // orange
  success:  "1B7340",
  danger:   "C0392B",
  warning:  "D4820A",
  info:     "1A5C8A",
  muted:    "6C757D",
  lightBg:  "F2F6FB",
  white:    "FFFFFF",
  black:    "1A1A1A",
};

// ─── Reusable border spec ─────────────────────────────────────────────────────
const border = (color = "CCCCCC") => ({
  style: BorderStyle.SINGLE, size: 6, color
});
const noBorder = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const borders = (color = "CCCCCC") => ({
  top: border(color), bottom: border(color),
  left: border(color), right: border(color)
});

// ─── Typography helpers ───────────────────────────────────────────────────────
const h1 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  spacing: { before: 360, after: 160 },
  children: [new TextRun({ text, bold: true, size: 36, color: CLR.brand, font: "Calibri" })],
});

const h2 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_2,
  spacing: { before: 240, after: 120 },
  children: [new TextRun({ text, bold: true, size: 28, color: CLR.brand, font: "Calibri" })],
});

const h3 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_3,
  spacing: { before: 180, after: 80 },
  children: [new TextRun({ text, bold: true, size: 24, color: CLR.accent, font: "Calibri" })],
});

const body = (text, opts = {}) => new Paragraph({
  spacing: { before: 80, after: 80 },
  children: [new TextRun({ text, size: 22, font: "Calibri", color: CLR.black, ...opts })],
});

const bold = (text) => body(text, { bold: true });

const gap = (lines = 1) => new Paragraph({
  spacing: { before: 0, after: lines * 100 },
  children: [new TextRun({ text: "", size: 22 })],
});

const pageBreak = () => new Paragraph({ children: [new PageBreak()] });

// ─── Numbered list ────────────────────────────────────────────────────────────
const numbered = (items, reference = "steps") =>
  items.map((text, i) => new Paragraph({
    numbering: { reference, level: 0 },
    spacing: { before: 60, after: 60 },
    children: [new TextRun({ text, size: 22, font: "Calibri", color: CLR.black })],
  }));

// ─── Bullet list ─────────────────────────────────────────────────────────────
const bullets = (items, reference = "bullets") =>
  items.map(text => new Paragraph({
    numbering: { reference, level: 0 },
    spacing: { before: 60, after: 60 },
    children: [new TextRun({ text, size: 22, font: "Calibri", color: CLR.black })],
  }));

// ─── Info box ─────────────────────────────────────────────────────────────────
const infoBox = (label, items, color = CLR.info) => new Table({
  width: { size: 9026, type: WidthType.DXA },
  columnWidths: [9026],
  borders: { top: border(color), bottom: border(color), left: border(color), right: border(color) },
  rows: [
    new TableRow({ children: [new TableCell({
      width: { size: 9026, type: WidthType.DXA },
      shading: { fill: "E8F4FB", type: ShadingType.CLEAR },
      margins: { top: 120, bottom: 80, left: 160, right: 160 },
      borders: borders(color),
      children: [
        new Paragraph({ spacing: { before: 0, after: 60 }, children: [
          new TextRun({ text: label, bold: true, size: 22, color, font: "Calibri" })
        ]}),
        ...items.map(t => new Paragraph({ spacing: { before: 40, after: 40 }, children: [
          new TextRun({ text: `• ${t}`, size: 20, color: CLR.black, font: "Calibri" })
        ]})),
      ],
    })]})
  ],
});

// ─── 2-column key-value table ─────────────────────────────────────────────────
const kvTable = (rows) => new Table({
  width: { size: 9026, type: WidthType.DXA },
  columnWidths: [3200, 5826],
  rows: [
    new TableRow({ children: [
      new TableCell({
        width: { size: 3200, type: WidthType.DXA },
        shading: { fill: CLR.brand, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        borders: borders(CLR.brand),
        children: [new Paragraph({ children: [new TextRun({ text: "Item", bold: true, size: 20, color: CLR.white, font: "Calibri" })] })],
      }),
      new TableCell({
        width: { size: 5826, type: WidthType.DXA },
        shading: { fill: CLR.brand, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        borders: borders(CLR.brand),
        children: [new Paragraph({ children: [new TextRun({ text: "Detail", bold: true, size: 20, color: CLR.white, font: "Calibri" })] })],
      }),
    ]}),
    ...rows.map(([k, v], i) => new TableRow({ children: [
      new TableCell({
        width: { size: 3200, type: WidthType.DXA },
        shading: { fill: i % 2 === 0 ? CLR.lightBg : CLR.white, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        borders: borders("DDDDDD"),
        children: [new Paragraph({ children: [new TextRun({ text: k, bold: true, size: 20, font: "Calibri", color: CLR.brand })] })],
      }),
      new TableCell({
        width: { size: 5826, type: WidthType.DXA },
        shading: { fill: i % 2 === 0 ? CLR.lightBg : CLR.white, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        borders: borders("DDDDDD"),
        children: [new Paragraph({ children: [new TextRun({ text: v, size: 20, font: "Calibri", color: CLR.black })] })],
      }),
    ]})),
  ],
});

// ─── Do / Don't table ─────────────────────────────────────────────────────────
const dosDonts = (dos, donts) => new Table({
  width: { size: 9026, type: WidthType.DXA },
  columnWidths: [4513, 4513],
  rows: [
    new TableRow({ children: [
      new TableCell({
        width: { size: 4513, type: WidthType.DXA },
        shading: { fill: "1B7340", type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        borders: borders("1B7340"),
        children: [new Paragraph({ children: [new TextRun({ text: "✔  DO", bold: true, size: 22, color: CLR.white, font: "Calibri" })] })],
      }),
      new TableCell({
        width: { size: 4513, type: WidthType.DXA },
        shading: { fill: CLR.danger, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        borders: borders(CLR.danger),
        children: [new Paragraph({ children: [new TextRun({ text: "✘  DON'T", bold: true, size: 22, color: CLR.white, font: "Calibri" })] })],
      }),
    ]}),
    ...Array.from({ length: Math.max(dos.length, donts.length) }, (_, i) => new TableRow({ children: [
      new TableCell({
        width: { size: 4513, type: WidthType.DXA },
        shading: { fill: "E8F5EE", type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        borders: borders("AADDB5"),
        children: [new Paragraph({ children: [new TextRun({ text: dos[i] || "", size: 20, font: "Calibri", color: CLR.black })] })],
      }),
      new TableCell({
        width: { size: 4513, type: WidthType.DXA },
        shading: { fill: "FDECEA", type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        borders: borders("F1A59A"),
        children: [new Paragraph({ children: [new TextRun({ text: donts[i] || "", size: 20, font: "Calibri", color: CLR.black })] })],
      }),
    ]})),
  ],
});

// ─── Role banner ─────────────────────────────────────────────────────────────
const roleBanner = (role, subtitle, url) => new Table({
  width: { size: 9026, type: WidthType.DXA },
  columnWidths: [9026],
  rows: [new TableRow({ children: [new TableCell({
    width: { size: 9026, type: WidthType.DXA },
    shading: { fill: CLR.brand, type: ShadingType.CLEAR },
    margins: { top: 200, bottom: 200, left: 240, right: 240 },
    borders: borders(CLR.brand),
    children: [
      new Paragraph({ alignment: AlignmentType.LEFT, children: [
        new TextRun({ text: role, bold: true, size: 40, color: CLR.white, font: "Calibri" })
      ]}),
      new Paragraph({ spacing: { before: 60 }, alignment: AlignmentType.LEFT, children: [
        new TextRun({ text: subtitle, size: 22, color: "BDD6F0", font: "Calibri" })
      ]}),
      new Paragraph({ spacing: { before: 60 }, alignment: AlignmentType.LEFT, children: [
        new TextRun({ text: `URL: ${url}`, size: 20, color: "BDD6F0", font: "Calibri" })
      ]}),
    ],
  })]})],
});

// ═══════════════════════════════════════════════════════════════════════════════
// ROLE CONTENT
// ═══════════════════════════════════════════════════════════════════════════════

function sectionIQC() {
  return [
    roleBanner("IQC Inspector", "Incoming Quality Control — Device intake & grading", "/iqc"),
    gap(),
    h2("What you do"),
    body("You are the FIRST person to handle every device that enters OxyPC. Your job is to inspect, grade, and decide the next step for each device that arrives in a lot."),
    gap(),
    h2("Daily Workflow"),
    ...numbered([
      "Open the app → go to IQC (top navigation).",
      "You will see all devices pending IQC inspection.",
      "Click a device barcode to open its IQC form.",
      "Fill in: Physical condition, screen, keyboard, ports, battery.",
      "Select Grade: A (excellent), B (good), C (fair), D (poor / for parts).",
      "Add notes for any damage you notice.",
      "Click Submit — device moves to Stock-In automatically.",
      "If device is unusable, select 'Scrap' instead.",
    ], "steps"),
    gap(),
    h2("Grading Guide"),
    kvTable([
      ["Grade A", "Like new — minimal or no visible wear, all functions working perfectly."],
      ["Grade B", "Light wear — small scratches, all major functions working."],
      ["Grade C", "Moderate wear — visible damage, some functions may need repair."],
      ["Grade D", "Heavy damage — mostly for spare parts, not resaleable."],
      ["Scrap", "Non-functional, broken beyond repair, no parts value."],
    ]),
    gap(),
    h2("Quick Reference"),
    infoBox("IQC Checklist (do this for EVERY device)", [
      "Physical body — cracks, dents, liquid damage",
      "Screen — dead pixels, cracks, backlight",
      "Keyboard / trackpad — all keys, touchpad response",
      "Ports — USB, HDMI, power jack, audio",
      "Battery — charges, holds charge, swollen?",
      "RAM / Storage — visible slots, HDD/SSD seated",
      "Cosmetic grade — A / B / C / D",
    ]),
    gap(),
    h2("Do's and Don'ts"),
    dosDonts(
      ["Grade every device before submitting.", "Add notes for any specific damage.", "Use the barcode scanner to find devices quickly.", "Ask your manager if unsure about a grade."],
      ["Submit without completing all fields.", "Skip a device — even if it looks fine.", "Give Grade A without checking all ports.", "Mark scrap without manager approval for valuable devices."]
    ),
  ];
}

function sectionInventory() {
  return [
    roleBanner("Inventory Manager", "Lot management, stock-in, device tracking", "/stock"),
    gap(),
    h2("What you do"),
    body("You manage the flow of devices from arrival (lot creation) through to the repair pipeline. You create lots, oversee stock-in, and ensure location tracking is accurate."),
    gap(),
    h2("Creating a New Lot"),
    ...numbered([
      "Go to Lots → New Lot.",
      "Enter: Supplier name, lot number, quantity, buying price.",
      "Attach the purchase invoice / document.",
      "Click Save — the lot is created and devices can now be registered.",
      "Share the lot number with the team receiving the shipment.",
    ], "steps"),
    gap(),
    h2("Stock-In Process"),
    ...numbered([
      "Go to Stock Room (sidebar).",
      "Scan or enter each device barcode.",
      "Assign it to the correct lot.",
      "Verify quantity matches the supplier's delivery note.",
      "Confirm stock-in — devices move to IQC queue.",
    ], "steps"),
    gap(),
    h2("Location Tracking"),
    body("Every device must have a physical location assigned. Use the Location Map (/locations/dashboard) to:"),
    ...bullets([
      "See where each device is stored (shelf, rack, tray).",
      "Identify devices with no location assigned (gap alerts on dashboard).",
      "Assign or move device locations after physical movement.",
    ]),
    gap(),
    h2("Key Reports"),
    kvTable([
      ["Lot P&L", "Dashboard → Finance tab — profit/loss per lot."],
      ["Device list", "/devices — filter by stage, lot, category."],
      ["Location gaps", "Dashboard — red badge shows unaccounted devices."],
      ["Stock report", "/reports — full inventory summary."],
    ]),
    gap(),
    h2("Do's and Don'ts"),
    dosDonts(
      ["Create the lot BEFORE devices arrive.", "Match physical count with system count.", "Update location immediately after moving a device.", "Review the dashboard gap alert daily."],
      ["Create a device without assigning it to a lot.", "Accept deliveries without counting units.", "Leave location blank — it causes gap alerts.", "Delete a lot that has devices attached."]
    ),
  ];
}

function sectionRepair(level) {
  const labels = { l1: "L1 — Basic Repair", l2: "L2 — Intermediate Repair", l3: "L3 — Advanced / Board Repair" };
  const urls   = { l1: "/repair/l1", l2: "/repair/l2", l3: "/repair/l3" };
  const descs  = {
    l1: "You handle basic repairs: cleaning, RAM/storage swaps, OS reinstall, driver fixes, basic diagnostics.",
    l2: "You handle intermediate repairs: display replacements, keyboard replacements, charging port, motherboard-level diagnostics.",
    l3: "You handle advanced repairs: motherboard soldering, chip-level repair, BGA rework, power section diagnosis.",
  };
  return [
    roleBanner(`${labels[level]} Engineer`, descs[level], urls[level]),
    gap(),
    h2("What you do"),
    body(descs[level]),
    gap(),
    h2("Daily Workflow"),
    ...numbered([
      `Go to Repair → ${level.toUpperCase()} Queue.`,
      "Pick the next device from the queue (oldest first).",
      "Click Start Repair — system logs your start time.",
      "Diagnose the device and record findings.",
      "Order spare parts if needed (via Spare Parts module).",
      "Complete the repair — record what was done and parts used.",
      "Click Complete — device moves to QC Check queue automatically.",
      "If device cannot be repaired, flag for scrap with notes.",
    ], "steps"),
    gap(),
    h2("Recording a Repair Job"),
    kvTable([
      ["Findings", "Describe what was wrong (e.g., 'HDD failed, replaced with 256GB SSD')."],
      ["Parts Used", "Select from the parts catalogue — stock is deducted automatically."],
      ["Time Spent", "Approximate hours — helps track repair cost per device."],
      ["Outcome", "Repaired / Partially repaired / Cannot repair."],
    ]),
    gap(),
    infoBox("Watch for scrap warnings", [
      "If the dashboard shows a SCRAP RISK banner for a device, check the cost vs expected sale price.",
      "If repair cost exceeds 70% of expected sale value, escalate to manager before continuing.",
      "A READY FOR QC banner means a device has no open jobs — move it to QC.",
    ], CLR.warning),
    gap(),
    h2("Do's and Don'ts"),
    dosDonts(
      ["Always record parts used — stock accuracy depends on it.", "Complete one device fully before picking the next.", "Flag unrepairable devices immediately.", "Use the barcode scanner to find devices quickly."],
      ["Skip the repair log — management cannot see progress.", "Use parts without recording them in the system.", "Move a device to QC manually — use the Complete button.", "Repair without reading the IQC notes first."]
    ),
  ];
}

function sectionQC() {
  return [
    roleBanner("QC Inspector", "Quality Control — final check before sale", "/qc"),
    gap(),
    h2("What you do"),
    body("You are the LAST line of quality before a device is listed for sale. Your job is to verify that the repair was successful, the device is fully functional, and assign a final grade."),
    gap(),
    h2("Daily Workflow"),
    ...numbered([
      "Go to QC Check (sidebar).",
      "Pick the next device from the queue.",
      "Run the full QC checklist (see below).",
      "Assign a QC Score out of 100.",
      "The grade is set automatically based on score.",
      "Click Pass — device moves to Ready to Sale.",
      "Click Fail — device goes back to the repair queue with your notes.",
    ], "steps"),
    gap(),
    h2("QC Checklist"),
    kvTable([
      ["Power on / off", "Device boots cleanly, no errors on startup."],
      ["Display", "No dead pixels, no backlight bleed, touch works."],
      ["Keyboard / trackpad", "Every key responds, trackpad smooth."],
      ["Ports", "USB, HDMI, audio, power — all tested."],
      ["Wi-Fi / Bluetooth", "Connects and holds signal."],
      ["Battery", "Charges, holds charge, no swelling."],
      ["OS / Software", "OS activated, no trial software, clean desktop."],
      ["Cosmetic", "Matches the grade assigned in IQC."],
    ]),
    gap(),
    h2("Scoring → Grade Mapping"),
    kvTable([
      ["90–100", "Grade A — ready to sell at premium price."],
      ["75–89",  "Grade B — ready to sell at standard price."],
      ["55–74",  "Grade C — ready to sell at discounted price."],
      ["Below 55","Fail — send back to repair with detailed notes."],
    ]),
    gap(),
    h2("Do's and Don'ts"),
    dosDonts(
      ["Test EVERY item on the checklist — no shortcuts.", "Write clear failure notes so the engineer knows what to fix.", "Reject if ANY critical function fails.", "Check cosmetic grade matches IQC grade."],
      ["Pass a device to hit daily targets.", "Skip ports/connectivity — buyers notice.", "Change the grade without justification.", "Pass a device with an unactivated OS."]
    ),
  ];
}

function sectionSales() {
  return [
    roleBanner("Sales Team", "Selling devices, managing customers & dealer orders", "/sales/ready"),
    gap(),
    h2("What you do"),
    body("You sell devices to walk-in customers and B2B dealers. You manage the sale process from finding the right device to completing the sale and processing returns."),
    gap(),
    h2("Selling a Device (Walk-in Customer)"),
    ...numbered([
      "Go to Sales → Ready to Sale — see all available devices.",
      "Find the right device using filters (category, RAM, grade).",
      "Click Sell on the chosen device.",
      "Enter: Customer name, phone, state, invoice number, payment mode.",
      "Review the sale price — a warning appears if below cost.",
      "Click Confirm Sale — system records the sale and marks device as Sold.",
      "Print / share the invoice.",
    ], "steps"),
    gap(),
    h2("Selling to a Dealer (B2B)"),
    ...numbered([
      "Go to Dealers → find or create the dealer.",
      "Create a Dealer Order — specify devices, quantity, price.",
      "Set payment terms and due date.",
      "Once devices are dispatched, mark order as Delivered.",
      "Record payments as they come in (Payments tab).",
      "Monitor the Ageing report for overdue amounts.",
    ], "steps"),
    gap(),
    h2("Processing a Return"),
    ...numbered([
      "Go to Returns → New Return.",
      "Scan / enter the device barcode.",
      "Enter reason and condition on return.",
      "Select action: Restock (goes back to IQC) or Scrap.",
      "Enter refund amount if applicable.",
      "Click Submit — device re-enters the pipeline.",
    ], "steps"),
    gap(),
    h2("Key Dashboard KPIs"),
    kvTable([
      ["Ready to Sell",        "Devices available — your sellable inventory."],
      ["Sold Today",           "Your team's sales count for today."],
      ["Month Revenue",        "Total sales revenue this month."],
      ["Dealer Outstanding",   "Total amount owed by dealers — chase overdue."],
      ["Overdue Orders",       "Dealers with payment past due date."],
    ]),
    gap(),
    h2("Do's and Don'ts"),
    dosDonts(
      ["Confirm payment before marking as sold.", "Always enter customer phone for warranty tracking.", "Check dealer outstanding before adding new orders.", "Issue a credit note for any pricing dispute."],
      ["Sell a device not in Ready to Sale stage.", "Skip the invoice number field.", "Ignore overdue dealer payments.", "Process a return without entering the reason."]
    ),
  ];
}

function sectionSpareParts() {
  return [
    roleBanner("Spare Parts Manager", "Parts inventory, consumption tracking & stock alerts", "/spare-parts"),
    gap(),
    h2("What you do"),
    body("You manage the spare parts inventory. You receive new parts, track consumption by engineers, and ensure critical parts are always in stock."),
    gap(),
    h2("Receiving New Parts"),
    ...numbered([
      "Go to Spare Parts → Add New Part (first time) or Restock.",
      "Enter: Part name, part code, supplier, quantity, unit price.",
      "Set the Minimum Stock Alert level (e.g., 5 units).",
      "Click Save — parts are added to stock.",
    ], "steps"),
    gap(),
    h2("Recording Consumption"),
    body("When an engineer uses a part for a repair, the system deducts it automatically when they record the repair job. You can also manually record consumption:"),
    ...numbered([
      "Go to Spare Parts → Record Consumption.",
      "Select the part, quantity used, and which device/lot it was for.",
      "Click Submit — stock is deducted.",
    ], "steps"),
    gap(),
    h2("Managing Low Stock"),
    infoBox("Low Stock Alert", [
      "Dashboard shows a LOW STOCK badge when any part falls at or below the minimum.",
      "Go to Spare Parts → filter by 'Low Stock' to see all affected parts.",
      "Place orders with suppliers immediately to avoid repair delays.",
      "Update the reorder quantity once stock is received.",
    ], CLR.danger),
    gap(),
    h2("Key Metrics"),
    kvTable([
      ["Low Stock Count",    "Dashboard — number of parts below minimum alert."],
      ["Stock Value",        "Dashboard — total value of all parts on hand."],
      ["Today Consumption",  "Dashboard — how many parts were used today."],
      ["Part Code",          "Unique identifier — use when ordering from suppliers."],
    ]),
    gap(),
    h2("Do's and Don'ts"),
    dosDonts(
      ["Set min stock alert for every part.", "Update stock immediately on receipt.", "Review the dashboard low-stock badge daily.", "Keep supplier contact details updated in the system."],
      ["Let stock go to zero before reordering.", "Skip the part code — it causes duplicates.", "Manually adjust stock without recording reason.", "Ignore consumption records — they affect lot P&L."]
    ),
  ];
}

function sectionAdmin() {
  return [
    roleBanner("Admin / Manager", "Full system access — oversight, reporting, user management", "/"),
    gap(),
    h2("What you do"),
    body("You have full access to the system. Your role is to monitor all operations, review financial performance, manage users, and resolve escalations."),
    gap(),
    h2("Dashboard Overview"),
    body("The Admin dashboard shows all queues at once:"),
    kvTable([
      ["IQC Pending",         "Devices waiting for incoming inspection."],
      ["L1/L2/L3 Queues",     "Devices at each repair level."],
      ["QC Pending",          "Devices awaiting final QC check."],
      ["Ready to Sale",       "Devices cleared for sale."],
      ["Today Sales",         "Units sold today."],
      ["Month Revenue",       "Total revenue this month."],
      ["Dealer Outstanding",  "Total unpaid dealer balances."],
      ["Overdue Orders",      "Dealer orders past due date."],
      ["Credit Notes (Month)","Credit notes issued this month."],
    ]),
    gap(),
    h2("Financial Monitoring"),
    ...bullets([
      "Finance tab (dashboard) → Month Revenue, Investment, Parts Cost, Net Profit.",
      "Lot P&L table → profit/loss per buying lot.",
      "Dealer Ageing report (/dealers/ageing) → overdue balances by dealer.",
      "Full reports at /reports — sales, lot P&L, spare parts consumption.",
    ]),
    gap(),
    h2("User Management"),
    ...numbered([
      "Go to Admin → Users.",
      "Add new user: enter name, username, password, role.",
      "Edit existing user: change role or reset password.",
      "Disable a user: uncheck Active — they cannot log in.",
    ], "steps"),
    gap(),
    h2("Stage Control — Allowed Transitions"),
    body("You control which stages devices can move between. To configure:"),
    ...numbered([
      "Go to Admin → Stage Control.",
      "Add an allowed transition: From stage → To stage.",
      "Engineers can only move devices along allowed paths.",
    ], "steps"),
    gap(),
    infoBox("Escalation Triggers — act immediately on these", [
      "Location Gap badge on dashboard — devices not physically located.",
      "Overdue Dealer Orders — chase payment or issue credit note.",
      "Low Stock alert for critical parts — authorise emergency reorder.",
      "Scrap Risk banner on repair list — approve / reject scrapping decision.",
    ], CLR.danger),
    gap(),
    h2("Do's and Don'ts"),
    dosDonts(
      ["Review dashboard every morning before operations start.", "Act on overdue dealer payments within 24 hours.", "Approve scrap decisions — don't leave them to engineers.", "Review lot P&L after each lot is fully sold."],
      ["Share admin credentials — each user needs their own account.", "Override stage transitions without audit reason.", "Ignore location gap alerts — it means devices are unaccounted for.", "Approve credit notes without checking the original invoice."]
    ),
  ];
}

function sectionCRM() {
  return [
    roleBanner("CRM / Telecaller", "Sales pipeline, sourcing deals, follow-ups & outreach", "/crm"),
    gap(),
    h2("What you do"),
    body("You manage the full sales and sourcing pipeline using the CRM. This includes tracking potential buyers, following up on leads, sourcing stock from suppliers, and managing contact records."),
    gap(),
    h2("CRM Modules"),
    kvTable([
      ["CRM Dashboard",     "/crm — your pipeline overview and today's follow-ups."],
      ["Contacts",          "/crm/contacts — all buyers, suppliers, dealers."],
      ["Sales Opps",        "/crm/sales — active sales opportunities."],
      ["Sourcing Deals",    "/crm/sourcing — stock sourcing / buying leads."],
      ["Activities",        "/crm/activities — calls, meetings, emails logged."],
      ["Quotes",            "/crm/quotes — price quotes sent to buyers."],
      ["Telecalling",       "/telecalling — daily call list and scripts."],
    ]),
    gap(),
    h2("Daily Workflow — Telecaller"),
    ...numbered([
      "Open CRM Dashboard — check Today's Follow-Ups badge.",
      "Go to Telecalling → today's call list.",
      "Call each contact — log the outcome (interested / not interested / callback).",
      "Schedule next follow-up date for callbacks.",
      "For interested buyers → create a Sales Opportunity.",
      "Send a quote from the Quotes module if requested.",
      "Mark follow-up as done when complete.",
    ], "steps"),
    gap(),
    h2("Creating a Sales Opportunity"),
    ...numbered([
      "Go to CRM → Sales → New Opportunity.",
      "Link to a Contact (or create a new contact).",
      "Enter: Device type wanted, grade, quantity, budget per unit.",
      "Set priority: Low / Medium / High / Urgent.",
      "Click Save — opportunity appears in the pipeline.",
      "Move through stages: Lead → Qualified → Proposal → Negotiation → Won / Lost.",
    ], "steps"),
    gap(),
    h2("Sourcing a Lot (Buying Stock)"),
    ...numbered([
      "Go to CRM → Sourcing → New Deal.",
      "Enter: Supplier contact, device type, quantity, expected price.",
      "Move deal through stages: Prospecting → Negotiating → Stock Received → Won.",
      "When stock arrives, link the deal to a Lot — stage auto-advances to Received.",
      "After IQC is complete, manually close deal to Won.",
    ], "steps"),
    gap(),
    infoBox("Follow-Up Badge on Dashboard", [
      "The Operations tab shows a red badge with the count of due follow-ups.",
      "This includes both Dealer Call follow-ups and CRM Activity follow-ups.",
      "Clear the badge every day by completing or rescheduling all overdue follow-ups.",
    ], CLR.accent),
    gap(),
    h2("Do's and Don'ts"),
    dosDonts(
      ["Log EVERY call — even rejections (they're useful data).", "Set a follow-up date on every contact.", "Link sales opps to the matching ready-to-sale devices.", "Update deal stage immediately after each interaction."],
      ["Skip logging a call because 'nothing happened'.", "Leave follow-up date blank — it disappears from your list.", "Create duplicate contacts — always search first.", "Mark a deal Won before payment is confirmed."]
    ),
  ];
}

// ─── Cover Page ───────────────────────────────────────────────────────────────
function coverPage() {
  return [
    gap(4),
    new Table({
      width: { size: 9026, type: WidthType.DXA },
      columnWidths: [9026],
      rows: [new TableRow({ children: [new TableCell({
        width: { size: 9026, type: WidthType.DXA },
        shading: { fill: CLR.brand, type: ShadingType.CLEAR },
        margins: { top: 600, bottom: 600, left: 400, right: 400 },
        borders: borders(CLR.brand),
        children: [
          new Paragraph({ alignment: AlignmentType.CENTER, children: [
            new TextRun({ text: "OxyPC Inventory System", bold: true, size: 56, color: CLR.white, font: "Calibri" })
          ]}),
          new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 160 }, children: [
            new TextRun({ text: "Complete Training Manual", size: 36, color: "BDD6F0", font: "Calibri" })
          ]}),
          new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 200 }, children: [
            new TextRun({ text: "All Roles · All Workflows · Quick Reference Cards", size: 22, color: "9BBFDF", font: "Calibri" })
          ]}),
        ],
      })]})],
    }),
    gap(2),
    new Paragraph({ alignment: AlignmentType.CENTER, children: [
      new TextRun({ text: `Version 1.0  ·  ${new Date().toLocaleDateString("en-IN", { day: "2-digit", month: "long", year: "numeric" })}`, size: 20, color: CLR.muted, font: "Calibri" })
    ]}),
    gap(2),
    new Table({
      width: { size: 9026, type: WidthType.DXA },
      columnWidths: [9026],
      rows: [new TableRow({ children: [new TableCell({
        width: { size: 9026, type: WidthType.DXA },
        shading: { fill: CLR.lightBg, type: ShadingType.CLEAR },
        margins: { top: 160, bottom: 160, left: 240, right: 240 },
        borders: borders("C5D8EE"),
        children: [
          new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 0, after: 80 }, children: [
            new TextRun({ text: "Roles covered in this manual", bold: true, size: 22, color: CLR.brand, font: "Calibri" })
          ]}),
          ...[
            "IQC Inspector", "Inventory Manager",
            "L1 Engineer · L2 Engineer · L3 Engineer",
            "QC Inspector", "Sales Team", "Spare Parts Manager",
            "Admin / Manager", "CRM / Telecaller"
          ].map(r => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 40, after: 40 }, children: [
            new TextRun({ text: `• ${r}`, size: 20, color: CLR.black, font: "Calibri" })
          ]})),
        ],
      })]})],
    }),
    pageBreak(),
  ];
}

// ─── Document assembly ────────────────────────────────────────────────────────
async function build() {
  const numbering = {
    config: [
      {
        reference: "steps",
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: "%1.",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        }],
      },
      {
        reference: "bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "•",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        }],
      },
    ],
  };

  const styles = {
    default: {
      document: { run: { font: "Calibri", size: 22, color: CLR.black } },
    },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Calibri", color: CLR.brand },
        paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0 },
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Calibri", color: CLR.brand },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 },
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Calibri", color: CLR.accent },
        paragraph: { spacing: { before: 180, after: 80 }, outlineLevel: 2 },
      },
    ],
  };

  const header = new Header({ children: [
    new Paragraph({
      border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "CCCCCC" } },
      children: [
        new TextRun({ text: "OxyPC Inventory — Training Manual", size: 18, color: CLR.muted, font: "Calibri" }),
        new TextRun({ text: "  |  CONFIDENTIAL — Internal use only", size: 18, color: CLR.muted, font: "Calibri" }),
      ],
    }),
  ]});

  const footer = new Footer({ children: [
    new Paragraph({
      border: { top: { style: BorderStyle.SINGLE, size: 6, color: "CCCCCC" } },
      alignment: AlignmentType.RIGHT,
      children: [
        new TextRun({ text: "Page ", size: 18, color: CLR.muted, font: "Calibri" }),
        new TextRun({ children: [PageNumber.CURRENT], size: 18, color: CLR.muted, font: "Calibri" }),
        new TextRun({ text: " of ", size: 18, color: CLR.muted, font: "Calibri" }),
        new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 18, color: CLR.muted, font: "Calibri" }),
      ],
    }),
  ]});

  const sectionProps = {
    properties: {
      page: {
        size: { width: 11906, height: 16838 }, // A4
        margin: { top: 1080, bottom: 1080, left: 1080, right: 1080 },
      },
    },
    headers: { default: header },
    footers: { default: footer },
  };

  const allContent = [
    // Cover
    ...coverPage(),

    // TOC
    h1("Table of Contents"),
    new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-2" }),
    pageBreak(),

    // Sections
    h1("1. IQC Inspector"),
    ...sectionIQC(),
    pageBreak(),

    h1("2. Inventory Manager"),
    ...sectionInventory(),
    pageBreak(),

    h1("3. L1 Engineer — Basic Repair"),
    ...sectionRepair("l1"),
    pageBreak(),

    h1("4. L2 Engineer — Intermediate Repair"),
    ...sectionRepair("l2"),
    pageBreak(),

    h1("5. L3 Engineer — Advanced Repair"),
    ...sectionRepair("l3"),
    pageBreak(),

    h1("6. QC Inspector"),
    ...sectionQC(),
    pageBreak(),

    h1("7. Sales Team"),
    ...sectionSales(),
    pageBreak(),

    h1("8. Spare Parts Manager"),
    ...sectionSpareParts(),
    pageBreak(),

    h1("9. Admin / Manager"),
    ...sectionAdmin(),
    pageBreak(),

    h1("10. CRM / Telecaller"),
    ...sectionCRM(),
  ];

  const doc = new Document({
    numbering,
    styles,
    sections: [{ ...sectionProps, children: allContent }],
  });

  const outPath = path.join(__dirname, "OxyPC_Training_Complete.docx");
  const buf = await Packer.toBuffer(doc);
  fs.writeFileSync(outPath, buf);
  console.log(`\n✓  Written: ${outPath}  (${Math.round(buf.length / 1024)} KB)\n`);
}

build().catch(err => { console.error("FAILED:", err); process.exit(1); });
