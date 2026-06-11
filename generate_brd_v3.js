"use strict";
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak, LevelFormat,
  TabStopType, TabStopPosition
} = require("docx");

// ── Helpers ──────────────────────────────────────────────────────────────────

const FONT = "Arial";
const PW = 9360; // content width (US Letter, 1" margins each side)

function border(color = "CCCCCC") {
  return { style: BorderStyle.SINGLE, size: 1, color };
}
function borders(color = "CCCCCC") {
  const b = border(color);
  return { top: b, bottom: b, left: b, right: b };
}
function noBorder() {
  const b = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
  return { top: b, bottom: b, left: b, right: b };
}

function cell(text, opts = {}) {
  const {
    bold = false, fill = "FFFFFF", color = "000000", shade = ShadingType.CLEAR,
    span = 1, align = AlignmentType.LEFT, vAlign = VerticalAlign.CENTER,
    width = null, borderColor = "CCCCCC", italic = false, size = 18
  } = opts;
  return new TableCell({
    borders: borders(borderColor),
    shading: { fill, type: shade },
    verticalAlign: vAlign,
    columnSpan: span,
    ...(width ? { width: { size: width, type: WidthType.DXA } } : {}),
    margins: { top: 60, bottom: 60, left: 120, right: 120 },
    children: [new Paragraph({
      alignment: align,
      children: [new TextRun({ text, bold, color, font: FONT, size, italic })]
    })]
  });
}

function hcell(text, fill = "1F3864", span = 1, width = null) {
  return cell(text, { bold: true, fill, color: "FFFFFF", shade: ShadingType.CLEAR, span, width, borderColor: "1F3864" });
}

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 300, after: 120 },
    children: [new TextRun({ text, font: FONT, size: 32, bold: true, color: "1F3864" })]
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 240, after: 100 },
    children: [new TextRun({ text, font: FONT, size: 26, bold: true, color: "2E4D8A" })]
  });
}
function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 200, after: 80 },
    children: [new TextRun({ text, font: FONT, size: 22, bold: true, color: "2E4D8A" })]
  });
}
function para(text, opts = {}) {
  const { bold = false, size = 20, color = "000000", spacing = { before: 60, after: 60 }, align = AlignmentType.LEFT, italic = false } = opts;
  return new Paragraph({
    alignment: align,
    spacing,
    children: [new TextRun({ text, bold, size, color, font: FONT, italic })]
  });
}
function bullet(text, level = 0) {
  return new Paragraph({
    numbering: { reference: "bullets", level },
    spacing: { before: 40, after: 40 },
    children: [new TextRun({ text, font: FONT, size: 20 })]
  });
}
function spacer(before = 120) {
  return new Paragraph({ spacing: { before, after: 0 }, children: [] });
}
function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}
function hr(color = "C0C0C0") {
  return new Paragraph({
    spacing: { before: 60, after: 60 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color } },
    children: []
  });
}

// ── Tables ───────────────────────────────────────────────────────────────────

function simpleTable(headers, rows, colWidths) {
  const total = colWidths.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: colWidths,
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((h, i) => hcell(h, "1F3864", 1, colWidths[i]))
      }),
      ...rows.map((row, ri) =>
        new TableRow({
          children: row.map((val, ci) =>
            cell(val, {
              fill: ri % 2 === 0 ? "F2F4F8" : "FFFFFF",
              width: colWidths[ci]
            })
          )
        })
      )
    ]
  });
}

// ── COVER PAGE ───────────────────────────────────────────────────────────────

function coverPage() {
  return [
    spacer(1800),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 120 },
      children: [new TextRun({ text: "OxyPC Inventory & Operations System", font: FONT, size: 48, bold: true, color: "1F3864" })]
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 60 },
      children: [new TextRun({ text: "BUSINESS REQUIREMENTS DOCUMENT", font: FONT, size: 36, bold: true, color: "2E4D8A" })]
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 200 },
      children: [new TextRun({ text: "Complete System Specification & Workflow Reference v3.0", font: FONT, size: 26, italic: true, color: "555555" })]
    }),
    hr("1F3864"),
    spacer(300),
    new Table({
      width: { size: PW, type: WidthType.DXA },
      columnWidths: [2800, 6560],
      rows: [
        ["Document Version", "v3.0"],
        ["Date", "March 2026"],
        ["Status", "Production + UAT Verified"],
        ["Product", "OxyPC Inventory & Operations System"],
        ["Total Modules", "22 Modules"],
        ["User Roles", "9 User Roles"],
        ["Device Stages", "17 Device Stages"],
        ["Prepared By", "OxyPC Engineering Team"],
        ["UAT Completed", "2026-03-28"]
      ].map((row, i) =>
        new TableRow({
          children: [
            cell(row[0], { bold: true, fill: "1F3864", color: "FFFFFF", shade: ShadingType.CLEAR, width: 2800, borderColor: "1F3864" }),
            cell(row[1], { fill: i % 2 === 0 ? "EEF2F8" : "FFFFFF", width: 6560 })
          ]
        })
      )
    }),
    spacer(400),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 0 },
      children: [new TextRun({ text: "CONFIDENTIAL — For Internal Use Only", font: FONT, size: 18, italic: true, color: "888888" })]
    }),
    pageBreak()
  ];
}

// ── SECTION 1: Executive Summary ──────────────────────────────────────────────

function section1() {
  return [
    h1("1. Executive Summary"),
    para("OxyPC is a full-stack inventory and operations management system built for refurbished PC and electronics businesses. It manages the complete device lifecycle — from goods receipt through workshop repair stages, quality control, sales, and post-sale returns — within a single integrated web application."),
    spacer(),
    para("Version 3.0 represents the production-ready release, verified through a full UAT cycle (91/91 test cases PASS). This version adds inventory location management, stage control dashboards, market intelligence, dealer management, attendance, telecalling, WhatsApp integration, GRN register, and lot line items — bringing the total to 22 functional modules."),
    spacer(),
    h2("1.1 Key Metrics (v3.0)"),
    simpleTable(
      ["Metric", "Value"],
      [
        ["Total Functional Modules", "22"],
        ["User Roles", "9"],
        ["Device Lifecycle Stages", "17"],
        ["UAT Test Cases (E2E)", "91 / 91 PASS"],
        ["Functional Tests", "66 / 66 PASS"],
        ["Bulk Insert Performance", "500 devices @ 307K records/sec"],
        ["Concurrent Sales Performance", "20 concurrent @ 14.4 sales/sec"],
        ["UAT Completion Date", "2026-03-28"]
      ],
      [3500, 5860]
    ),
    pageBreak()
  ];
}

// ── SECTION 2: System Overview ────────────────────────────────────────────────

function section2() {
  return [
    h1("2. System Overview"),
    h2("2.1 Technology Stack"),
    simpleTable(
      ["Layer", "Technology", "Notes"],
      [
        ["Backend Framework", "FastAPI (Python 3.11)", "Async, OpenAPI auto-docs"],
        ["Database", "PostgreSQL 15+", "asyncpg driver, pgcrypto for UUIDs"],
        ["ORM / Migrations", "SQLAlchemy 2.0 + Alembic", "Async session, declarative base"],
        ["Template Engine", "Jinja2", "Server-side rendered HTML"],
        ["Frontend", "Bootstrap 5 + Vanilla JS", "No SPA framework"],
        ["Authentication", "Session-based (itsdangerous)", "Signed cookies, role checks"],
        ["Connection Pool", "asyncpg pool_size=20, max_overflow=10", "Production tuned"],
        ["Sequence Generation", "PostgreSQL sequence sale_number_seq", "Race-condition-safe"],
        ["Packaging", "PyInstaller + Inno Setup", "Offline Windows installer"]
      ],
      [2200, 3200, 3960]
    ),
    spacer(),
    h2("2.2 Architecture Pattern"),
    bullet("Monolithic FastAPI application with modular router files"),
    bullet("All HTML rendered server-side via Jinja2 templates"),
    bullet("RESTful JSON APIs for AJAX operations (barcode lookup, gap counts, etc.)"),
    bullet("PostgreSQL as single source of truth — no Redis, no message queue"),
    bullet("Role-based access enforced at router level via dependency injection"),
    bullet("Async throughout: async def routes, async SQLAlchemy sessions, asyncpg pool"),
    pageBreak()
  ];
}

// ── SECTION 3: User Roles ─────────────────────────────────────────────────────

function section3() {
  return [
    h1("3. User Roles & Access"),
    h2("3.1 Role Definitions"),
    simpleTable(
      ["Role", "Code", "Description"],
      [
        ["Super Admin", "superadmin", "Full system access, user management, all overrides"],
        ["Admin", "admin", "Operational admin, stage overrides, reports"],
        ["Manager", "manager", "Sales, purchasing, lot management, reports"],
        ["Sales", "sales", "Create sales, view inventory, customer lookup"],
        ["Technician L1", "technician_l1", "IQC, L1 repair, stock-in operations"],
        ["Technician L2", "technician_l2", "L2, L3 repair stages"],
        ["QC Inspector", "qc", "QC check, Final QC sign-off"],
        ["Warehouse", "warehouse", "Cleaning, painting, masking, dry/water sanding, location management"],
        ["Viewer", "viewer", "Read-only access to inventory and reports"]
      ],
      [2200, 1800, 5360]
    ),
    spacer(),
    h2("3.2 Access Control Matrix"),
    para("Legend: \u2713 = Full Access   \u2713* = Own records only   \u2014 = No Access"),
    spacer(100),
    new Table({
      width: { size: PW, type: WidthType.DXA },
      columnWidths: [2200, 900, 900, 900, 900, 900, 900, 900, 900],
      rows: [
        new TableRow({
          tableHeader: true,
          children: [
            hcell("Module", "1F3864", 1, 2200),
            hcell("SA", "1F3864", 1, 900),
            hcell("Admin", "1F3864", 1, 900),
            hcell("Mgr", "1F3864", 1, 900),
            hcell("Sales", "1F3864", 1, 900),
            hcell("L1", "1F3864", 1, 900),
            hcell("L2", "1F3864", 1, 900),
            hcell("QC", "1F3864", 1, 900),
            hcell("WH", "1F3864", 1, 900)
          ]
        }),
        ...([
          ["Lot / GRN Management", "\u2713", "\u2713", "\u2713", "\u2014", "\u2014", "\u2014", "\u2014", "\u2014"],
          ["Device Registration (IQC)", "\u2713", "\u2713", "\u2713", "\u2014", "\u2713", "\u2014", "\u2014", "\u2014"],
          ["Stage Transitions", "\u2713", "\u2713", "\u2714", "\u2014", "\u2713", "\u2713", "\u2713", "\u2713"],
          ["Sales", "\u2713", "\u2713", "\u2713", "\u2713", "\u2014", "\u2014", "\u2014", "\u2014"],
          ["Returns", "\u2713", "\u2713", "\u2713", "\u2713", "\u2014", "\u2014", "\u2014", "\u2014"],
          ["Inventory Locations", "\u2713", "\u2713", "\u2713", "\u2014", "\u2014", "\u2014", "\u2014", "\u2713"],
          ["Stage Control", "\u2713", "\u2713", "\u2713", "\u2014", "\u2014", "\u2014", "\u2014", "\u2014"],
          ["Reports", "\u2713", "\u2713", "\u2713", "\u2713*", "\u2014", "\u2014", "\u2014", "\u2014"],
          ["Market Intelligence", "\u2713", "\u2713", "\u2713", "\u2713", "\u2014", "\u2014", "\u2014", "\u2014"],
          ["Dealer Management", "\u2713", "\u2713", "\u2713", "\u2014", "\u2014", "\u2014", "\u2014", "\u2014"],
          ["Attendance", "\u2713", "\u2713", "\u2713", "\u2014", "\u2014", "\u2014", "\u2014", "\u2014"],
          ["Telecalling", "\u2713", "\u2713", "\u2713", "\u2713", "\u2014", "\u2014", "\u2014", "\u2014"],
          ["WhatsApp Integration", "\u2713", "\u2713", "\u2713", "\u2713", "\u2014", "\u2014", "\u2014", "\u2014"],
          ["User Management", "\u2713", "\u2713", "\u2014", "\u2014", "\u2014", "\u2014", "\u2014", "\u2014"],
          ["Audit Logs", "\u2713", "\u2713", "\u2014", "\u2014", "\u2014", "\u2014", "\u2014", "\u2014"]
        ]).map((row, ri) =>
          new TableRow({
            children: row.map((val, ci) => {
              const isCheck = val.startsWith("\u2713") || val.startsWith("\u2714");
              const isDash = val === "\u2014";
              return cell(val, {
                fill: ri % 2 === 0 ? "F2F4F8" : "FFFFFF",
                color: isCheck ? "1A5C2A" : isDash ? "888888" : "000000",
                bold: isCheck || isDash,
                width: ci === 0 ? 2200 : 900,
                align: ci === 0 ? AlignmentType.LEFT : AlignmentType.CENTER
              });
            })
          })
        )
      ]
    }),
    pageBreak()
  ];
}

// ── SECTION 4: Device Lifecycle ───────────────────────────────────────────────

function section4() {
  return [
    h1("4. Device Lifecycle & Stage Definitions"),
    h2("4.1 DeviceStage Enum (Corrected v3.0)"),
    para("The following are the exact stage values as defined in the DeviceStage PostgreSQL enum and Python model. Note: v2.0 incorrectly listed l1_repair, l2_repair, qc — these have been corrected below.", { italic: true }),
    spacer(100),
    simpleTable(
      ["#", "Stage Code", "Stage Label", "Category", "Sequence"],
      [
        ["1", "iqc", "Incoming Quality Check", "Intake", "1"],
        ["2", "stock_in", "Stocked In", "Intake", "2"],
        ["3", "l1", "L1 Repair", "Workshop", "3"],
        ["4", "l2", "L2 Repair", "Workshop", "4"],
        ["5", "l3", "L3 Repair", "Workshop", "5"],
        ["6", "qc_check", "QC Check", "Quality", "6"],
        ["7", "cleaning", "Cleaning", "Cosmetic", "7"],
        ["8", "dry_sanding", "Dry Sanding", "Cosmetic", "8"],
        ["9", "masking", "Masking", "Cosmetic", "9"],
        ["10", "painting", "Painting", "Cosmetic", "10"],
        ["11", "water_sanding", "Water Sanding", "Cosmetic", "11"],
        ["12", "final_qc", "Final QC", "Quality", "12"],
        ["13", "ready_to_sale", "Ready to Sale", "Sales", "13"],
        ["14", "sold", "Sold", "Sales", "14"],
        ["15", "returned", "Returned", "Post-Sale", "15"],
        ["16", "scrapped", "Scrapped", "Terminal", "16"],
        ["17", "lost", "Lost / Written Off", "Terminal", "17"]
      ],
      [400, 1400, 2200, 1600, 1200]
    ),
    spacer(),
    h2("4.2 Stage Transition Rules"),
    para("Allowed transitions are enforced by the allowed_transitions table. The stage_master table stores sequence and active status for each stage."),
    spacer(100),
    simpleTable(
      ["From Stage", "Allowed Next Stages", "Notes"],
      [
        ["iqc", "stock_in, scrapped", "Device enters system; either accepted or scrapped at IQC"],
        ["stock_in", "l1, l2, l3, qc_check, cleaning, ready_to_sale", "Skip-ahead allowed based on device condition"],
        ["l1", "l2, l3, qc_check, scrapped", "Escalate to L2/L3 or pass to QC"],
        ["l2", "l3, qc_check, scrapped", "Escalate to L3 or pass to QC"],
        ["l3", "qc_check, scrapped", "Must go to QC after L3"],
        ["qc_check", "cleaning, final_qc, l1, l2, l3, scrapped", "Fail: re-route to repair; Pass: cosmetic or final"],
        ["cleaning", "dry_sanding, masking, painting, water_sanding, final_qc", "Cosmetic flow"],
        ["dry_sanding", "masking, painting, water_sanding, final_qc", "Cosmetic flow"],
        ["masking", "painting, final_qc", "Cosmetic flow"],
        ["painting", "water_sanding, final_qc", "Cosmetic flow"],
        ["water_sanding", "final_qc", "Last cosmetic step"],
        ["final_qc", "ready_to_sale, l1, l2, l3, scrapped", "Pass: ready; Fail: re-repair or scrap"],
        ["ready_to_sale", "sold, scrapped", "Available for sale"],
        ["sold", "returned", "Post-sale return only"],
        ["returned", "iqc, scrapped", "Return re-enters as fresh IQC or is scrapped"],
        ["scrapped", "\u2014 (terminal)", "No further transitions allowed"],
        ["lost", "\u2014 (terminal)", "No further transitions allowed"]
      ],
      [1600, 3300, 4460]
    ),
    pageBreak()
  ];
}

// ── SECTION 5: Data Model ─────────────────────────────────────────────────────

function section5() {
  return [
    h1("5. Data Model"),
    h2("5.1 Core Tables"),
    simpleTable(
      ["Table", "Key Columns", "Purpose"],
      [
        ["users", "id (UUID PK), username, hashed_password, role, is_active, created_at", "Authentication & RBAC"],
        ["lots", "id (UUID PK), lot_number, supplier, purchase_date, total_devices, total_amount, status, notes, created_by, created_at", "Purchase lots / GRN header"],
        ["lot_line_items", "id, lot_id (FK), sub_category, brand, model, cpu, generation, ram_gb, has_ram, storage_gb, storage_type, has_storage, screen_size, grade, unit_price, qty, notes, created_at", "Line items per lot (mixed-spec lots)"],
        ["devices", "id (UUID PK), barcode (unique), lot_id (FK), brand, model, sub_category, cpu, generation, ram_gb, storage_gb, screen_size, color, grade, current_stage, is_sold, sale_id (FK), created_at, updated_at", "Device master record"],
        ["stage_history", "id, device_id (FK), from_stage, to_stage, moved_by, moved_at, notes", "Immutable audit of stage changes"],
        ["sales", "id (UUID PK), sale_number (seq), device_id (FK), customer_name, customer_phone, sale_price, payment_mode, sold_by, sold_at, invoice_path", "Sales transactions"],
        ["returns", "id (UUID PK), sale_id (FK), device_id (FK), reason, returned_by, returned_at, condition_notes", "Post-sale returns"],
        ["customers", "id (UUID PK), name, phone (unique), email, address, created_at", "Customer master"],
        ["device_costing", "id, device_id (unique FK), base_cost, parts_cost, labour_cost, total_cost, expected_sale_value, updated_at", "Per-device cost breakdown"]
      ],
      [2000, 3800, 3560]
    ),
    spacer(),
    h2("5.2 New Tables (v3.0)"),
    h3("5.2.1 inventory_locations"),
    simpleTable(
      ["Column", "Type", "Description"],
      [
        ["id", "UUID PK", "Primary key"],
        ["zone", "ZoneType enum", "workshop / warehouse / showroom / office / transit"],
        ["rack", "VARCHAR(50)", "Rack identifier (e.g. R1, R2)"],
        ["shelf", "VARCHAR(50)", "Shelf identifier (e.g. S1, S2)"],
        ["bin", "VARCHAR(50)", "Bin identifier (e.g. B1, B2)"],
        ["label", "VARCHAR(100)", "Human-readable label (e.g. WH-R1-S2-B3)"],
        ["capacity", "INTEGER", "Max devices this location can hold"],
        ["description", "TEXT", "Free-text description"],
        ["is_active", "BOOLEAN", "Whether location is in use"],
        ["created_at", "TIMESTAMP", "Creation timestamp"]
      ],
      [2000, 2000, 5360]
    ),
    spacer(),
    h3("5.2.2 device_location_assignments"),
    simpleTable(
      ["Column", "Type", "Description"],
      [
        ["id", "UUID PK", "Primary key"],
        ["device_id", "UUID FK \u2192 devices", "Device being assigned"],
        ["location_id", "UUID FK \u2192 inventory_locations", "Target shelf location"],
        ["assigned_by", "UUID FK \u2192 users", "Who assigned the device"],
        ["assigned_at", "TIMESTAMP", "When assigned"],
        ["picked_up_at", "TIMESTAMP (nullable)", "When device was picked up for work"],
        ["placed_back_at", "TIMESTAMP (nullable)", "When device was returned to shelf"],
        ["is_active", "BOOLEAN", "TRUE = device is currently in this location"]
      ],
      [2500, 2500, 4360]
    ),
    spacer(),
    h3("5.2.3 audit_logs"),
    simpleTable(
      ["Column", "Type", "Description"],
      [
        ["id", "UUID PK", "Primary key"],
        ["username", "VARCHAR", "Who performed the action"],
        ["action", "VARCHAR", "Action type (CREATE, UPDATE, DELETE, LOGIN, etc.)"],
        ["table_name", "VARCHAR", "Affected table"],
        ["record_id", "UUID (nullable)", "Affected record ID"],
        ["old_value", "JSONB", "State before change"],
        ["new_value", "JSONB", "State after change"],
        ["ip_address", "VARCHAR", "Client IP address"],
        ["notes", "TEXT", "Free-text context"],
        ["created_at", "TIMESTAMP", "Log entry timestamp"]
      ],
      [2000, 2000, 5360]
    ),
    spacer(),
    h3("5.2.4 stage_master"),
    simpleTable(
      ["Column", "Type", "Description"],
      [
        ["id", "UUID PK", "Primary key"],
        ["name", "VARCHAR (unique)", "Stage code matching DeviceStage enum"],
        ["label", "VARCHAR", "Display label"],
        ["sequence", "INTEGER", "Ordering for display"],
        ["is_active", "BOOLEAN", "Whether stage is currently in use"],
        ["created_at", "TIMESTAMP", "Creation timestamp"]
      ],
      [2000, 2000, 5360]
    ),
    spacer(),
    h3("5.2.5 allowed_transitions"),
    simpleTable(
      ["Column", "Type", "Description"],
      [
        ["id", "UUID PK", "Primary key"],
        ["from_stage", "VARCHAR", "Source stage code"],
        ["to_stage", "VARCHAR", "Destination stage code"],
        ["is_active", "BOOLEAN", "Whether transition is currently allowed"]
      ],
      [2000, 2000, 5360]
    ),
    spacer(),
    h3("5.2.6 lot_line_items"),
    simpleTable(
      ["Column", "Type", "Description"],
      [
        ["id", "UUID PK", "Primary key"],
        ["lot_id", "UUID FK \u2192 lots", "Parent lot"],
        ["sub_category", "VARCHAR", "Device category (Laptop, Desktop, etc.)"],
        ["brand", "VARCHAR", "Manufacturer"],
        ["model", "VARCHAR", "Model name"],
        ["cpu", "VARCHAR", "Processor"],
        ["generation", "VARCHAR", "CPU generation"],
        ["ram_gb", "INTEGER", "RAM in GB"],
        ["has_ram", "BOOLEAN", "Whether RAM is present"],
        ["storage_gb", "INTEGER", "Storage capacity in GB"],
        ["storage_type", "VARCHAR", "SSD / HDD / NVMe"],
        ["has_storage", "BOOLEAN", "Whether storage is present"],
        ["screen_size", "VARCHAR", "Screen size (e.g. 15.6 inch)"],
        ["grade", "VARCHAR", "Cosmetic grade A/B/C/D"],
        ["unit_price", "NUMERIC(10,2)", "Purchase price per unit"],
        ["qty", "INTEGER", "Quantity of this spec"],
        ["notes", "TEXT", "Additional notes"],
        ["created_at", "TIMESTAMP", "Creation timestamp"]
      ],
      [2000, 2200, 5160]
    ),
    pageBreak()
  ];
}

// ── SECTION 6: Functional Modules ────────────────────────────────────────────

function section6() {
  return [
    h1("6. Functional Modules"),
    para("The system comprises 22 functional modules. Modules 6.1–6.11 were present in v2.0. Modules 6.12–6.22 are new in v3.0."),
    spacer(),

    // ── 6.1 to 6.11 (existing modules summary) ──
    h2("6.1 Authentication & Session Management"),
    bullet("Username/password login with hashed passwords (bcrypt)"),
    bullet("Session cookie signed with itsdangerous secret key"),
    bullet("Role stored in session; every route checks required_roles dependency"),
    bullet("Login audit logged to audit_logs table"),
    bullet("Session timeout configurable; force-logout on role change"),
    spacer(),

    h2("6.2 User Management"),
    bullet("Super Admin and Admin can create, edit, deactivate users"),
    bullet("Roles: superadmin, admin, manager, sales, technician_l1, technician_l2, qc, warehouse, viewer"),
    bullet("Password reset by admin (generates temp password)"),
    bullet("User list with search and filter by role"),
    spacer(),

    h2("6.3 Lot Management"),
    bullet("Create lot (purchase from supplier) with lot number, supplier, date, amounts"),
    bullet("Lot status: draft, received, partial, complete, closed"),
    bullet("Each lot now supports multiple line items (see Module 6.20)"),
    bullet("Bulk device import from lot (template CSV/Excel upload)"),
    bullet("Lot-level GRN register view (see Module 6.19)"),
    spacer(),

    h2("6.4 Device Registration (IQC)"),
    bullet("Register device at IQC stage — assigns unique barcode"),
    bullet("Capture: brand, model, sub_category, cpu, generation, RAM, storage, screen_size, color, grade, cosmetic notes"),
    bullet("Initial stage is always iqc"),
    bullet("Batch registration from lot line items with partial fill"),
    spacer(),

    h2("6.5 Stage Transitions"),
    bullet("Move device from one stage to another via UI or barcode scan"),
    bullet("Allowed transitions enforced by allowed_transitions table"),
    bullet("Each move creates immutable stage_history record"),
    bullet("Notes captured per transition"),
    bullet("Admin stage override bypasses allowed_transitions check"),
    spacer(),

    h2("6.6 Inventory Search & Filters"),
    bullet("Full-text search across barcode, brand, model, serial number"),
    bullet("Filter by stage, brand, model, grade, sub_category"),
    bullet("Sortable columns; paginated results"),
    bullet("Quick barcode lookup API (/api/device/{barcode})"),
    spacer(),

    h2("6.7 Sales"),
    bullet("Create sale: scan/select device, enter customer details, set price, payment mode"),
    bullet("Sale number auto-generated from PostgreSQL sequence sale_number_seq (race-condition-safe)"),
    bullet("Invoice generated as PDF (Jinja2 + WeasyPrint or equivalent)"),
    bullet("Mark device as sold; stage moves to sold"),
    bullet("EMI / installment sale support with payment schedule"),
    bullet("Sale history with search by customer, device, date range"),
    spacer(),

    h2("6.8 Returns"),
    bullet("Process return against existing sale record"),
    bullet("Capture reason, condition notes"),
    bullet("Device stage reverts to returned; then transitions to iqc or scrapped"),
    bullet("Return auto-linked to original sale and customer"),
    spacer(),

    h2("6.9 Reports"),
    bullet("Stage summary report: device count per stage"),
    bullet("Lot-wise procurement report"),
    bullet("Sales report: by date range, by sales rep, by brand/model"),
    bullet("Revenue vs. cost analysis using device_costing"),
    bullet("Stage aging report: devices stuck in stage > SLA"),
    bullet("Export to Excel / CSV"),
    spacer(),

    h2("6.10 Bulk Upload"),
    bullet("Upload Excel template to bulk-register devices into a lot"),
    bullet("Validation: check required fields, flag duplicates"),
    bullet("Error report returned with row-level validation messages"),
    bullet("Max 500 devices per batch; performance verified at 307K records/sec"),
    spacer(),

    h2("6.11 Device Costing"),
    bullet("Per-device cost record: base_cost, parts_cost, labour_cost, total_cost"),
    bullet("Expected sale value for margin calculation"),
    bullet("Updated any time parts or labour are added during repair"),
    bullet("Feeds into revenue vs. cost reports"),
    spacer(),
    hr(),
    spacer(),
    para("NEW MODULES IN v3.0", { bold: true, size: 22, color: "1F3864" }),
    spacer(),

    // ── 6.12 ──
    h2("6.12 Inventory Location Management"),
    para("Manages physical locations within the facility, enabling precise shelf-level tracking of every device."),
    spacer(80),
    h3("6.12.1 Location Zones"),
    simpleTable(
      ["Zone Code", "Zone Name", "Use Case"],
      [
        ["workshop", "Workshop", "Active repair areas (L1/L2/L3 benches)"],
        ["warehouse", "Warehouse", "Storage racks for unprocessed / processed stock"],
        ["showroom", "Showroom", "Display-ready devices"],
        ["office", "Office", "Admin / management area"],
        ["transit", "Transit", "Devices in transit between zones"]
      ],
      [1500, 2000, 5860]
    ),
    spacer(),
    h3("6.12.2 Location Hierarchy"),
    bullet("Zone \u2192 Rack \u2192 Shelf \u2192 Bin"),
    bullet("Each bin has a capacity limit; system warns when full"),
    bullet("Labels auto-generated from zone-rack-shelf-bin (e.g. WH-R2-S3-B1)"),
    spacer(),
    h3("6.12.3 Device Assignment Operations"),
    simpleTable(
      ["Operation", "Description", "Who"],
      [
        ["Assign Device", "Place device into a specific bin location", "Warehouse, Admin, Manager"],
        ["Pick Up", "Mark device as picked up (vacates the bin record)", "Warehouse, Technicians"],
        ["Place Back", "Return device to assigned location after work", "Warehouse, Technicians"],
        ["Gap Alert", "System flags when assigned device is not present", "Auto (system check)"],
        ["Physical Audit", "Full location scan to verify actual vs. expected", "Admin, Warehouse"]
      ],
      [1800, 4500, 3060]
    ),
    spacer(),
    h3("6.12.4 API Endpoints"),
    simpleTable(
      ["Endpoint", "Method", "Description"],
      [
        ["/locations/api/device-location/{barcode}", "GET", "Return current location for a device"],
        ["/locations/api/gap-count", "GET", "Count of locations with gaps (assigned but missing)"],
        ["/locations/dashboard", "GET", "Zone-wise occupancy dashboard"],
        ["/locations/master", "GET/POST", "Location CRUD (admin)"],
        ["/locations/gaps", "GET", "List all gap alerts"],
        ["/locations/audit", "GET/POST", "Physical audit interface"],
        ["/locations/device/{id}", "GET", "Device location history"]
      ],
      [3400, 900, 5060]
    ),
    spacer(),

    // ── 6.13 ──
    h2("6.13 Stage Control & Aging"),
    para("Provides operations management visibility into device flow across stages with SLA-based aging alerts."),
    spacer(80),
    h3("6.13.1 Stage Control Dashboard"),
    bullet("Shows all active devices grouped by current stage"),
    bullet("Displays time-in-stage (days since last stage change)"),
    bullet("Color-coded: green (within SLA), amber (approaching), red (breached)"),
    bullet("Click-through to device detail from dashboard"),
    spacer(),
    h3("6.13.2 Aging Alerts"),
    bullet("SLA thresholds configurable per stage (e.g. IQC: 1 day, L1: 3 days, L2: 5 days)"),
    bullet("Devices exceeding SLA appear in aging alert list"),
    bullet("Dashboard widgets show alert counts per stage"),
    spacer(),
    h3("6.13.3 Admin Stage Override"),
    bullet("Admin/Super Admin can force-move a device to any stage, bypassing allowed_transitions"),
    bullet("Override reason required; logged to audit_logs and stage_history"),
    bullet("Override flagged visually in device stage history"),
    spacer(),
    simpleTable(
      ["URL", "Description"],
      [
        ["/stage-control", "Stage control dashboard with device counts per stage"],
        ["/stage-control/aging", "Aging alerts — devices exceeding SLA thresholds"]
      ],
      [3000, 6360]
    ),
    spacer(),

    // ── 6.14 ──
    h2("6.14 Market Intelligence"),
    para("Dashboard for tracking competitive market pricing by model and grade to inform pricing decisions."),
    spacer(80),
    bullet("Add market price entries: brand, model, grade, source, price, date observed"),
    bullet("View price trends per model over time (tabular)"),
    bullet("Compare OxyPC selling price vs. market average"),
    bullet("Export market price data to Excel"),
    bullet("URL: /market"),
    spacer(),

    // ── 6.15 ──
    h2("6.15 Dealer Management"),
    para("Manages B2B dealer relationships, follow-up schedules, and dealer-level sales history."),
    spacer(80),
    h3("6.15.1 Dealer Master"),
    bullet("Dealer record: name, company, phone, email, address, category (buyer/seller/both)"),
    bullet("Active / inactive status toggle"),
    spacer(),
    h3("6.15.2 Follow-up Tracker"),
    bullet("Log follow-up entries against a dealer with due date and outcome"),
    bullet("Due-today and overdue follow-ups surfaced on dashboard"),
    bullet("URL: /dealers/followups-due"),
    spacer(),
    h3("6.15.3 Dealer Sales History"),
    bullet("View all sales made to a dealer"),
    bullet("URL: /dealers"),
    spacer(),

    // ── 6.16 ──
    h2("6.16 Attendance"),
    para("Staff attendance log for tracking daily check-in / check-out."),
    spacer(80),
    bullet("Log attendance for any staff user by date"),
    bullet("Mark: Present, Absent, Half-Day, Leave"),
    bullet("Monthly attendance summary per employee"),
    bullet("Export to Excel"),
    bullet("URL: /attendance"),
    spacer(),

    // ── 6.17 ──
    h2("6.17 Telecalling"),
    para("Lead and telecalling activity log for pre-sales customer outreach."),
    spacer(80),
    bullet("Add leads: name, phone, interest (brand/model/budget), source"),
    bullet("Log call activities against each lead: date, outcome, next follow-up"),
    bullet("Lead status: new, contacted, interested, converted, lost"),
    bullet("URL: /telecalling"),
    spacer(),

    // ── 6.18 ──
    h2("6.18 WhatsApp Integration"),
    para("QR-based WhatsApp Web connection module for customer communication."),
    spacer(80),
    bullet("Connect WhatsApp via QR scan (Baileys / wa-service Node.js bridge)"),
    bullet("Send invoice links and sale confirmations to customers via WhatsApp"),
    bullet("Connection status indicator (connected / disconnected)"),
    bullet("QR refresh on disconnection"),
    bullet("URL: /whatsapp"),
    spacer(),

    // ── 6.19 ──
    h2("6.19 GRN (Goods Receipt Note) Register"),
    para("Dedicated GRN views separate from the lot management interface."),
    spacer(80),
    h3("6.19.1 GRN List"),
    bullet("Dedicated /grn route showing all GRN records (one per lot)"),
    bullet("Columns: GRN Number, Lot Number, Supplier, Date, Total Qty, Total Value, Status"),
    bullet("Search and filter by supplier, date range, status"),
    bullet("URL: /grn"),
    spacer(),
    h3("6.19.2 GRN Register per Lot"),
    bullet("View all devices registered against a specific lot"),
    bullet("Shows device barcode, brand, model, grade, stage, registration date"),
    bullet("Count of registered vs. expected (from line items)"),
    bullet("URL: /lots/{id}/register"),
    spacer(),
    h3("6.19.3 New GRN"),
    bullet("Create a new GRN / lot entry from the GRN module"),
    bullet("URL: /grn/new"),
    spacer(),

    // ── 6.20 ──
    h2("6.20 Lot Line Items"),
    para("Lots now support multiple specification line items, enabling mixed-spec purchase orders."),
    spacer(80),
    bullet("Each lot can have 1..N line items"),
    bullet("Line item captures full device specification: sub_category, brand, model, cpu, generation, RAM, storage, screen_size, grade"),
    bullet("unit_price and qty per line item for precise cost allocation"),
    bullet("Devices registered at IQC can be linked to a specific lot line item"),
    bullet("Line item totals aggregate to lot total value automatically"),
    spacer(),
    simpleTable(
      ["Field", "Type", "Required", "Notes"],
      [
        ["sub_category", "VARCHAR", "Yes", "Laptop / Desktop / Tablet / Monitor / etc."],
        ["brand", "VARCHAR", "Yes", "e.g. Dell, HP, Lenovo"],
        ["model", "VARCHAR", "Yes", "e.g. ThinkPad T480"],
        ["cpu", "VARCHAR", "No", "e.g. Intel Core i5"],
        ["generation", "VARCHAR", "No", "e.g. 8th Gen"],
        ["ram_gb", "INTEGER", "No", "0 if has_ram = false"],
        ["has_ram", "BOOLEAN", "Yes", "Whether device includes RAM"],
        ["storage_gb", "INTEGER", "No", "0 if has_storage = false"],
        ["storage_type", "VARCHAR", "No", "SSD / HDD / NVMe"],
        ["has_storage", "BOOLEAN", "Yes", "Whether device includes storage"],
        ["screen_size", "VARCHAR", "No", "e.g. 14 inch, 15.6 inch"],
        ["grade", "VARCHAR", "Yes", "A / B / C / D"],
        ["unit_price", "NUMERIC(10,2)", "Yes", "Purchase price per unit"],
        ["qty", "INTEGER", "Yes", "Quantity of this specification"],
        ["notes", "TEXT", "No", "Additional notes"]
      ],
      [1800, 1600, 1200, 4760]
    ),
    spacer(),

    // ── 6.21 ──
    h2("6.21 Bulk Upload"),
    bullet("Upload Excel/CSV to batch-register devices into a lot"),
    bullet("Template downloadable from UI"),
    bullet("Validates required fields, checks for duplicate barcodes"),
    bullet("Error report returned per row"),
    bullet("500-device batch tested at 307,000 records/sec insert rate"),
    bullet("URL: /bulk-upload"),
    spacer(),

    // ── 6.22 ──
    h2("6.22 Device Costing (Enhanced)"),
    bullet("device_costing table with unique device_id constraint (one record per device)"),
    bullet("Tracks: base_cost (purchase allocation), parts_cost, labour_cost"),
    bullet("total_cost = base_cost + parts_cost + labour_cost (computed)"),
    bullet("expected_sale_value for margin target"),
    bullet("Feeds into profit/loss reports"),
    pageBreak()
  ];
}

// ── SECTION 7: URL Route Map ──────────────────────────────────────────────────

function section7() {
  return [
    h1("7. URL Route Map"),
    para("Complete URL route map for all modules in v3.0. Routes marked [NEW] were added in v3.0."),
    spacer(100),
    simpleTable(
      ["URL Pattern", "Method(s)", "Module", "Access"],
      [
        ["/login", "GET, POST", "Authentication", "Public"],
        ["/logout", "POST", "Authentication", "Authenticated"],
        ["/dashboard", "GET", "Dashboard", "All Roles"],
        // Users
        ["/users", "GET", "User Mgmt", "Admin+"],
        ["/users/new", "GET, POST", "User Mgmt", "Admin+"],
        ["/users/{id}/edit", "GET, POST", "User Mgmt", "Admin+"],
        // Lots & GRN
        ["/lots", "GET", "Lot Mgmt", "Manager+"],
        ["/lots/new", "GET, POST", "Lot Mgmt", "Manager+"],
        ["/lots/{id}", "GET", "Lot Mgmt", "Manager+"],
        ["/lots/{id}/edit", "GET, POST", "Lot Mgmt", "Manager+"],
        ["/lots/{id}/register", "GET [NEW]", "GRN Register", "Manager+"],
        ["/grn", "GET [NEW]", "GRN List", "Manager+"],
        ["/grn/new", "GET, POST [NEW]", "New GRN", "Manager+"],
        // Devices
        ["/devices", "GET", "Inventory", "All Roles"],
        ["/devices/new", "GET, POST", "IQC Register", "L1, Admin+"],
        ["/devices/{id}", "GET", "Device Detail", "All Roles"],
        ["/devices/{id}/move", "GET, POST", "Stage Transition", "Role per stage"],
        ["/devices/{id}/edit", "GET, POST", "Edit Device", "Admin+"],
        ["/devices/{id}/costing", "GET, POST", "Costing", "Manager+"],
        // Sales
        ["/sales", "GET", "Sales History", "Sales+"],
        ["/sales/new", "GET, POST", "New Sale", "Sales+"],
        ["/sales/{id}", "GET", "Sale Detail", "Sales+"],
        ["/sales/{id}/invoice", "GET", "Invoice PDF", "Sales+"],
        // Returns
        ["/returns", "GET [was missing]", "Returns List", "Sales+"],
        ["/returns/new", "GET, POST [was missing]", "New Return", "Sales+"],
        ["/returns/{id}", "GET", "Return Detail", "Sales+"],
        // Reports
        ["/reports", "GET", "Reports Hub", "Manager+"],
        ["/reports/stage-summary", "GET", "Stage Report", "Manager+"],
        ["/reports/sales", "GET", "Sales Report", "Manager+"],
        ["/reports/lot", "GET", "Lot Report", "Manager+"],
        ["/reports/aging", "GET", "Aging Report", "Manager+"],
        // Bulk
        ["/bulk-upload", "GET, POST [NEW]", "Bulk Upload", "Manager+"],
        // Locations
        ["/locations/dashboard", "GET [NEW]", "Location Mgmt", "Warehouse+"],
        ["/locations/master", "GET, POST [NEW]", "Location CRUD", "Admin+"],
        ["/locations/gaps", "GET [NEW]", "Gap Alerts", "Admin+"],
        ["/locations/audit", "GET, POST [NEW]", "Physical Audit", "Admin+"],
        ["/locations/device/{id}", "GET [NEW]", "Device Location", "All Roles"],
        ["/locations/api/device-location/{barcode}", "GET [NEW]", "Location API", "Warehouse+"],
        ["/locations/api/gap-count", "GET [NEW]", "Gap Count API", "Warehouse+"],
        // Stage Control
        ["/stage-control", "GET [NEW]", "Stage Control", "Admin+"],
        ["/stage-control/aging", "GET [NEW]", "Aging Alerts", "Admin+"],
        // Market
        ["/market", "GET, POST [NEW]", "Market Intel", "Manager+"],
        // Dealers
        ["/dealers", "GET, POST [NEW]", "Dealer Mgmt", "Manager+"],
        ["/dealers/{id}", "GET", "Dealer Detail", "Manager+"],
        ["/dealers/followups-due", "GET [NEW]", "Due Follow-ups", "Manager+"],
        // Attendance
        ["/attendance", "GET, POST [NEW]", "Attendance", "Admin+"],
        // Telecalling
        ["/telecalling", "GET, POST [NEW]", "Telecalling", "Sales+"],
        // WhatsApp
        ["/whatsapp", "GET [NEW]", "WhatsApp", "Admin+"],
        // Customers
        ["/customers", "GET", "Customers", "Sales+"],
        ["/customers/{id}", "GET", "Customer Detail", "Sales+"]
      ],
      [3200, 1800, 1900, 2460]
    ),
    pageBreak()
  ];
}

// ── SECTION 8: Technical Architecture ────────────────────────────────────────

function section8() {
  return [
    h1("8. Technical Architecture"),
    h2("8.1 Application Structure"),
    simpleTable(
      ["Directory / File", "Purpose"],
      [
        ["main.py", "FastAPI app factory, middleware, exception handlers, router registration"],
        ["config.py", "Settings (database URL, secret key, app config)"],
        ["database.py", "asyncpg engine, session factory, connection pool setup"],
        ["auth/", "Authentication dependencies, session utilities, password hashing"],
        ["models/", "SQLAlchemy ORM models for all tables"],
        ["routers/", "FastAPI router files, one per functional module"],
        ["schemas/", "Pydantic request/response schemas"],
        ["services/", "Business logic layer (sales, transitions, costing)"],
        ["templates/", "Jinja2 HTML templates"],
        ["static/", "CSS, JS, images, Bootstrap"],
        ["alembic/", "Database migration scripts"],
        ["scripts/", "Seed scripts, utility scripts"]
      ],
      [3000, 6360]
    ),
    spacer(),
    h2("8.2 Exception Handling"),
    para("Global exception handlers are registered in main.py to produce consistent error responses:"),
    spacer(80),
    simpleTable(
      ["Exception Type", "HTTP Status", "Use Case"],
      [
        ["DBAPIError (UUID format)", "400 Bad Request", "Malformed UUID in URL parameter or body"],
        ["DBAPIError (other)", "500 Internal Server Error", "Unexpected database errors"],
        ["ProgrammingError", "500 Internal Server Error", "SQL programming errors (bad queries)"],
        ["DataError", "400 Bad Request", "Data type mismatch (e.g. string where integer expected)"],
        ["NoResultFound", "404 Not Found", "Record not found in query"],
        ["PermissionError", "403 Forbidden", "Role-based access denial"]
      ],
      [2800, 1800, 4760]
    ),
    spacer(),
    h2("8.3 Reliability & Concurrency"),
    h3("8.3.1 Sale Number Generation"),
    para("v2.0 used COUNT(*)+1 to generate sale numbers, which caused race conditions under concurrent load. v3.0 replaces this with a PostgreSQL sequence:"),
    spacer(80),
    bullet("Sequence name: sale_number_seq"),
    bullet("Monotonically increasing, gap-free under normal operation"),
    bullet("Atomic: no two concurrent transactions get the same number"),
    bullet("Generated via SELECT nextval('sale_number_seq') within the transaction"),
    spacer(),
    h3("8.3.2 Connection Pool"),
    simpleTable(
      ["Parameter", "Value", "Rationale"],
      [
        ["pool_size", "20", "Handles 20 concurrent requests without queuing"],
        ["max_overflow", "10", "Burst capacity up to 30 total connections"],
        ["pool_timeout", "30s", "Wait time before raising PoolTimeout"],
        ["pool_recycle", "1800s", "Recycle connections every 30 min to avoid stale connections"],
        ["pool_pre_ping", "True", "Test connection liveness before checkout"]
      ],
      [2000, 1500, 5860]
    ),
    spacer(),
    h3("8.3.3 Template Serialization"),
    para("Jinja2 model | tojson filter caused serialization failures for SQLAlchemy model objects. v3.0 uses explicit dict serialization in all templates:"),
    spacer(80),
    bullet("LotLineItem objects serialized to plain dicts before passing to template context"),
    bullet("JSON-serializable types only (str, int, float, bool, None) in template vars"),
    bullet("No ORM lazy-loading triggered inside Jinja2 rendering"),
    spacer(),
    h2("8.4 Security"),
    bullet("All passwords hashed with bcrypt (12 rounds)"),
    bullet("Session cookies: HttpOnly=True, SameSite=Lax, Secure=True (production)"),
    bullet("CSRF protection via itsdangerous signed state tokens"),
    bullet("SQL injection prevention: SQLAlchemy parameterized queries only"),
    bullet("File uploads: whitelist extension check (xlsx, csv only for bulk upload)"),
    bullet("Audit log captures all create/update/delete operations with old/new values"),
    pageBreak()
  ];
}

// ── SECTION 9: Integration Points ────────────────────────────────────────────

function section9() {
  return [
    h1("9. Integration Points"),
    h2("9.1 WhatsApp Integration (wa-service)"),
    para("A Node.js sidecar process (wa-service/) provides WhatsApp connectivity via the Baileys library."),
    spacer(80),
    simpleTable(
      ["Component", "Detail"],
      [
        ["Technology", "Node.js + Baileys (WhatsApp Web API)"],
        ["Connection Method", "QR code scan via browser UI"],
        ["Communication", "FastAPI \u2192 wa-service via local HTTP (localhost:3001)"],
        ["Session Persistence", "wa-service stores session keys locally"],
        ["Messages Sent", "Invoice links, sale confirmations, follow-up reminders"]
      ],
      [2500, 6860]
    ),
    spacer(),
    h2("9.2 Invoice Generation"),
    bullet("Jinja2 HTML template rendered server-side"),
    bullet("PDF conversion via WeasyPrint or browser print-to-PDF"),
    bullet("Invoice stored at configured path; link embedded in sale record"),
    bullet("Invoice number = sale_number (from PostgreSQL sequence)"),
    spacer(),
    h2("9.3 Barcode System"),
    bullet("Barcode generated at device registration (UUID-based or sequential)"),
    bullet("Barcode printed as label (Code 128 format)"),
    bullet("Barcode scanner input triggers device lookup via /api/device/{barcode}"),
    bullet("All stage transition and location assignment UIs support barcode scan input"),
    pageBreak()
  ];
}

// ── SECTION 10: Deployment ────────────────────────────────────────────────────

function section10() {
  return [
    h1("10. Deployment & Installation"),
    h2("10.1 Packaging"),
    bullet("Application packaged as a standalone Windows executable using PyInstaller"),
    bullet("Inno Setup installer wraps the executable for end-user installation"),
    bullet("PostgreSQL bundled or connected to existing instance via config.ini"),
    bullet("wa-service Node.js process started alongside main app via launcher.py"),
    spacer(),
    h2("10.2 Configuration"),
    simpleTable(
      ["Config Key", "Default", "Description"],
      [
        ["DATABASE_URL", "postgresql+asyncpg://...", "PostgreSQL connection string"],
        ["SECRET_KEY", "(generated)", "itsdangerous signing key"],
        ["APP_PORT", "8000", "HTTP server port"],
        ["WA_SERVICE_PORT", "3001", "WhatsApp service port"],
        ["INVOICE_PATH", "./invoices/", "Invoice PDF storage path"],
        ["LOG_LEVEL", "INFO", "Application log verbosity"]
      ],
      [2200, 2200, 4960]
    ),
    spacer(),
    h2("10.3 Database Setup"),
    bullet("Run alembic upgrade head to apply all migrations"),
    bullet("Run seed_master_new.py to populate stage_master and allowed_transitions"),
    bullet("Run seed_uat_users.py for UAT user accounts (remove before production)"),
    bullet("PostgreSQL sequence sale_number_seq created by migration"),
    pageBreak()
  ];
}

// ── SECTION 11: QA / UAT Summary ──────────────────────────────────────────────

function section11() {
  return [
    h1("11. QA / UAT Summary"),
    para("This section documents the quality assurance and user acceptance testing results for OxyPC v3.0."),
    spacer(),

    h2("11.1 UAT Overview"),
    simpleTable(
      ["Attribute", "Value"],
      [
        ["UAT Run ID", "UAT-TEST-RUN1"],
        ["UAT Completion Date", "2026-03-28"],
        ["Test Environment", "Windows 11, PostgreSQL 15, Python 3.11"],
        ["Tester", "OxyPC QA Team"],
        ["E2E UAT Result", "91 / 91 PASS (100%)"],
        ["Functional Test Result", "66 / 66 PASS (100%)"],
        ["Bugs Found During UAT", "4"],
        ["Bugs Fixed Before Sign-off", "4"],
        ["Overall Status", "PASS — Production Ready"]
      ],
      [3000, 6360]
    ),
    spacer(),

    h2("11.2 Test Coverage"),
    simpleTable(
      ["Test Suite", "Count", "PASS", "FAIL", "Coverage Area"],
      [
        ["Functional Tests (automated)", "66", "66", "0", "All 22 modules — API and business logic"],
        ["E2E UAT Scenarios", "91", "91", "0", "Full workflow from lot creation to sale"],
        ["Performance: Bulk Insert", "1", "1", "0", "500 devices inserted @ 307K records/sec"],
        ["Performance: Concurrent Sales", "1", "1", "0", "20 concurrent sales @ 14.4 sales/sec"],
        ["Total", "159", "159", "0", "\u2014"]
      ],
      [2800, 800, 800, 800, 4160]
    ),
    spacer(),

    h2("11.3 Bugs Found & Fixed"),
    simpleTable(
      ["#", "Bug Description", "Root Cause", "Fix Applied", "Severity"],
      [
        ["1", "Lot detail page crashed with JSON serialization error for line items", "Jinja2 | tojson on SQLAlchemy model instance", "Explicit dict serialization in template context", "High"],
        ["2", "Concurrent sales generated duplicate sale numbers", "COUNT(*)+1 race condition under concurrent inserts", "Replaced with PostgreSQL sequence sale_number_seq", "Critical"],
        ["3", "Cosmetic stage transitions missing from allowed_transitions seed", "Seed script did not include cleaning\u2192dry_sanding\u2192masking etc.", "Added all cosmetic stage transitions to seed_master_new.py", "High"],
        ["4", "Stage names in UI showed l1_repair, l2_repair, qc instead of l1, l2, qc_check", "Enum values in BRD v2.0 and UI labels used old names", "Corrected enum names in models, templates, and all BRD documentation", "Medium"]
      ],
      [400, 2500, 2200, 2000, 1260]
    ),
    spacer(),

    h2("11.4 Performance Benchmarks"),
    simpleTable(
      ["Benchmark", "Metric", "Result", "Status"],
      [
        ["Bulk Device Insert (500 devices)", "Insert throughput", "307,000 records/sec", "PASS"],
        ["Concurrent Sales (20 simultaneous)", "Sales throughput", "14.4 sales/sec", "PASS"],
        ["Single Device Stage Transition", "Response time", "<80ms (p99)", "PASS"],
        ["Inventory Search (10K devices)", "Query response", "<200ms (p99)", "PASS"],
        ["Invoice PDF Generation", "Response time", "<1.5 sec", "PASS"]
      ],
      [3000, 2200, 2200, 1960]
    ),
    spacer(),

    h2("11.5 UAT Sign-off"),
    para("UAT was completed on 2026-03-28. All 91 end-to-end test scenarios passed. All 4 bugs found during UAT were resolved and re-verified before sign-off. The system is approved for production deployment.", { bold: false }),
    spacer(80),
    simpleTable(
      ["Sign-off Item", "Status"],
      [
        ["All functional tests passing", "\u2713 PASS"],
        ["All E2E UAT scenarios passing", "\u2713 PASS"],
        ["All critical and high bugs resolved", "\u2713 FIXED"],
        ["Performance benchmarks met", "\u2713 PASS"],
        ["Security review completed", "\u2713 PASS"],
        ["Production deployment approval", "\u2713 APPROVED"]
      ],
      [4000, 5360]
    ),
    pageBreak()
  ];
}

// ── SECTION 12: Glossary ──────────────────────────────────────────────────────

function section12() {
  return [
    h1("12. Glossary"),
    simpleTable(
      ["Term", "Definition"],
      [
        ["IQC", "Incoming Quality Check — first stage when a device enters the system"],
        ["GRN", "Goods Receipt Note — document recording receipt of purchased devices"],
        ["Lot", "A purchase batch from a supplier, containing one or more device line items"],
        ["DeviceStage", "PostgreSQL enum defining all valid lifecycle stages for a device"],
        ["Stage Transition", "Movement of a device from one stage to another, recorded in stage_history"],
        ["Allowed Transition", "A permitted from_stage \u2192 to_stage pair stored in allowed_transitions table"],
        ["Stage Override", "Admin action bypassing allowed_transitions to force a stage change"],
        ["SLA", "Service Level Agreement — maximum days a device should remain in a stage"],
        ["Aging Alert", "Notification when a device exceeds its stage SLA"],
        ["Gap Alert", "Notification when a device assigned to a location is not physically present"],
        ["sale_number_seq", "PostgreSQL sequence that generates sequential, race-condition-safe sale numbers"],
        ["wa-service", "Node.js WhatsApp Web bridge process running alongside FastAPI"],
        ["Barcode", "Unique identifier printed as a label and used for scanning throughout workflow"],
        ["ZoneType", "Enum defining facility zones: workshop, warehouse, showroom, office, transit"],
        ["BRD", "Business Requirements Document — this document"]
      ],
      [2200, 7160]
    ),
    pageBreak()
  ];
}

// ── SECTION 13: Change Log ────────────────────────────────────────────────────

function section13() {
  return [
    h1("13. Document Change Log"),
    simpleTable(
      ["Version", "Date", "Author", "Summary of Changes"],
      [
        ["v1.0", "Jan 2026", "OxyPC Engineering", "Initial BRD — core lot, device, sales, and stage modules"],
        ["v2.0", "Feb 2026", "OxyPC Engineering", "Added returns, costing, reports, bulk upload; expanded role matrix; stage history detail"],
        ["v3.0", "Mar 2026", "OxyPC Engineering", "Production release: 11 new modules (6.12\u20136.22), data model additions, stage name corrections, reliability improvements (sequence, pool, serialization), UAT summary (91/91 PASS), corrected DeviceStage enum values throughout"]
      ],
      [900, 1200, 2200, 5060]
    )
  ];
}

// ── DOCUMENT ASSEMBLY ─────────────────────────────────────────────────────────

const doc = new Document({
  styles: {
    default: {
      document: { run: { font: FONT, size: 20 } }
    },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: FONT, color: "1F3864" },
        paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0 }
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: FONT, color: "2E4D8A" },
        paragraph: { spacing: { before: 280, after: 120 }, outlineLevel: 1 }
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 22, bold: true, font: FONT, color: "2E4D8A" },
        paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 2 }
      }
    ]
  },
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } }
        }, {
          level: 1, format: LevelFormat.BULLET, text: "\u25E6", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 1080, hanging: 360 } } }
        }]
      }
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 }
      }
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "1F3864" } },
          spacing: { before: 0, after: 80 },
          children: [
            new TextRun({ text: "OxyPC Inventory & Operations System  |  BRD v3.0  |  CONFIDENTIAL", font: FONT, size: 16, color: "888888" })
          ]
        })]
      })
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          border: { top: { style: BorderStyle.SINGLE, size: 4, color: "C0C0C0" } },
          spacing: { before: 80, after: 0 },
          tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
          children: [
            new TextRun({ text: "Page ", font: FONT, size: 16, color: "888888" }),
            new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: "888888" }),
            new TextRun({ text: " of ", font: FONT, size: 16, color: "888888" }),
            new TextRun({ children: [PageNumber.TOTAL_PAGES], font: FONT, size: 16, color: "888888" }),
            new TextRun({ text: "\tOxyPC Confidential — Internal Use Only", font: FONT, size: 16, color: "AAAAAA" })
          ]
        })]
      })
    },
    children: [
      ...coverPage(),
      ...section1(),
      ...section2(),
      ...section3(),
      ...section4(),
      ...section5(),
      ...section6(),
      ...section7(),
      ...section8(),
      ...section9(),
      ...section10(),
      ...section11(),
      ...section12(),
      ...section13()
    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync(
    "C:\\Users\\Pankaj.sehgal\\Claude\\Oxypc\\oxypc-inventory\\OxyPC_BRD_v3.0.docx",
    buffer
  );
  console.log("BRD v3.0 created successfully");
}).catch(err => {
  console.error("Error:", err);
  process.exit(1);
});
