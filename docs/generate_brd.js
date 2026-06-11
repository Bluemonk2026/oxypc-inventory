"use strict";
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak, TableOfContents,
  LevelFormat, Bookmark
} = require("docx");

// ── Helpers ──────────────────────────────────────────────────────────────────

const BORDER = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const BORDERS = { top: BORDER, bottom: BORDER, left: BORDER, right: BORDER };
const NO_BORDER = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const NO_BORDERS = { top: NO_BORDER, bottom: NO_BORDER, left: NO_BORDER, right: NO_BORDER };

function h1(text, bookmarkId) {
  const run = new TextRun({ text, bold: true, font: "Arial", size: 36, color: "2B6CB0" });
  const children = bookmarkId
    ? [new Bookmark({ id: bookmarkId, children: [run] })]
    : [run];
  return new Paragraph({ heading: HeadingLevel.HEADING_1, children, spacing: { before: 360, after: 180 } });
}

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    children: [new TextRun({ text, bold: true, font: "Arial", size: 28, color: "2D3748" })],
    spacing: { before: 240, after: 120 },
  });
}

function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    children: [new TextRun({ text, bold: true, font: "Arial", size: 24, color: "4A5568" })],
    spacing: { before: 200, after: 80 },
  });
}

function para(text, opts = {}) {
  return new Paragraph({
    children: [new TextRun({ text, font: "Arial", size: 22, ...opts })],
    spacing: { before: 80, after: 80 },
  });
}

function bullet(text) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    children: [new TextRun({ text, font: "Arial", size: 22 })],
    spacing: { before: 40, after: 40 },
  });
}

function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

function divider() {
  return new Paragraph({
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "2B6CB0", space: 1 } },
    spacing: { before: 120, after: 120 },
    children: [],
  });
}

function makeHeaderCell(text, width) {
  return new TableCell({
    borders: BORDERS,
    width: { size: width, type: WidthType.DXA },
    shading: { fill: "2B6CB0", type: ShadingType.CLEAR },
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({
      children: [new TextRun({ text: String(text), font: "Arial", size: 20, bold: true, color: "FFFFFF" })],
    })],
  });
}

function makeCell(text, width, shade = "FFFFFF") {
  return new TableCell({
    borders: BORDERS,
    width: { size: width, type: WidthType.DXA },
    shading: { fill: shade, type: ShadingType.CLEAR },
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({
      children: [new TextRun({ text: String(text || ""), font: "Arial", size: 20, color: "000000" })],
    })],
  });
}

// Generic data table
function dataTable(headers, rows, colWidths) {
  const totalWidth = colWidths.reduce((a, b) => a + b, 0);
  const headerRow = new TableRow({ children: headers.map((h, i) => makeHeaderCell(h, colWidths[i])) });
  const dataRows = rows.map((row, ri) =>
    new TableRow({
      children: row.map((cell, i) => makeCell(cell, colWidths[i], ri % 2 === 1 ? "F7FAFC" : "FFFFFF")),
    })
  );
  return new Table({
    width: { size: totalWidth, type: WidthType.DXA },
    columnWidths: colWidths,
    rows: [headerRow, ...dataRows],
  });
}

// Schema table
function schemaTable(columns) {
  const rows = columns.map(([col, type, notes]) => [col, type, notes || ""]);
  return dataTable(["Column", "Type / Constraint", "Notes"], rows, [2600, 2800, 3360]);
}

// Scorecard table with colour-coded score
function colorForScore(score) {
  const n = parseFloat(score);
  if (n >= 7.5) return "276749";
  if (n >= 5.0) return "B7791F";
  return "9B2C2C";
}

function scorecardTable(rows) {
  const headerRow = new TableRow({
    children: [
      makeHeaderCell("Layer / Framework", 3000),
      makeHeaderCell("Score", 900),
      makeHeaderCell("Status", 1100),
      makeHeaderCell("Key Finding", 3760),
    ],
  });
  const dataRows = rows.map(([layer, score, status, finding]) =>
    new TableRow({
      children: [
        new TableCell({
          borders: BORDERS, width: { size: 3000, type: WidthType.DXA },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          shading: { fill: "FFFFFF", type: ShadingType.CLEAR },
          children: [new Paragraph({ children: [new TextRun({ text: layer, font: "Arial", size: 20, bold: true })] })],
        }),
        new TableCell({
          borders: BORDERS, width: { size: 900, type: WidthType.DXA },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          shading: { fill: "FFFFFF", type: ShadingType.CLEAR },
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [new TextRun({ text: String(score), font: "Arial", size: 20, bold: true, color: colorForScore(score) })],
          })],
        }),
        new TableCell({
          borders: BORDERS, width: { size: 1100, type: WidthType.DXA },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          shading: { fill: colorForScore(score), type: ShadingType.CLEAR },
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [new TextRun({ text: status, font: "Arial", size: 20, bold: true, color: "FFFFFF" })],
          })],
        }),
        new TableCell({
          borders: BORDERS, width: { size: 3760, type: WidthType.DXA },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          shading: { fill: "FFFFFF", type: ShadingType.CLEAR },
          children: [new Paragraph({ children: [new TextRun({ text: finding, font: "Arial", size: 20 })] })],
        }),
      ],
    })
  );
  return new Table({
    width: { size: 8760, type: WidthType.DXA },
    columnWidths: [3000, 900, 1100, 3760],
    rows: [headerRow, ...dataRows],
  });
}

function codePara(text) {
  return new Paragraph({
    children: [new TextRun({ text, font: "Courier New", size: 18, color: "1A202C" })],
    spacing: { before: 20, after: 20 },
    indent: { left: 360 },
    shading: { fill: "EDF2F7", type: ShadingType.CLEAR },
  });
}

// ── Cover Page ────────────────────────────────────────────────────────────────

function coverPage() {
  return [
    new Paragraph({ spacing: { before: 1800 }, children: [] }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "OxyPC Inventory Management System", font: "Arial", size: 60, bold: true, color: "2B6CB0" })],
      spacing: { before: 0, after: 200 },
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "Business Requirements Document", font: "Arial", size: 44, color: "4A5568" })],
      spacing: { before: 0, after: 160 },
    }),
    divider(),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "Version 4.0  |  April 2026  |  CONFIDENTIAL", font: "Arial", size: 28, color: "718096" })],
      spacing: { before: 160, after: 1200 },
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "Prepared by: OxyPC Technology Team", font: "Arial", size: 24 })],
      spacing: { before: 0, after: 100 },
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "Classification: Internal Enterprise Use Only", font: "Arial", size: 24, italics: true, color: "9B2C2C" })],
      spacing: { before: 0, after: 100 },
    }),
    pageBreak(),
  ];
}

// ── Section 1: Executive Summary ─────────────────────────────────────────────

function section1() {
  return [
    h1("1. Executive Summary", "s1"),
    para("OxyPC Inventory Management System is a full-stack enterprise web application purpose-built for the ITAD (IT Asset Disposition) and refurbishment industry. It manages the complete lifecycle of pre-owned IT equipment from lot procurement through physical inspection, multi-level repair, quality certification, and final sale within a single integrated platform."),
    para(""),
    para("The system currently processes devices across 14 distinct operational stages, supports 11 user roles with granular RBAC enforcement, and integrates a CRM pipeline for both supplier sourcing and buyer opportunity management. As of April 2026 the platform has achieved a 5.6/10 compliance score against enterprise CLAUDE.md standards, with active remediation underway to reach a target of 8.3/10 before SaaS launch."),
    para(""),
    h2("1.1 System at a Glance"),
    dataTable(
      ["Attribute", "Detail"],
      [
        ["Application Type", "Web ERP: FastAPI + PostgreSQL 15 + Jinja2 + Bootstrap 5"],
        ["Current Deployment", "LAN Server: 192.168.7.247:8000 (Ethernet 5 NIC)"],
        ["Database", "PostgreSQL 15, 57 tables, 11 Alembic migrations"],
        ["User Roles", "11 roles: admin, inventory_manager, iqc_inspector, l1/l2/l3_engineer, qc_inspector, sales, sales_manager, telecaller, spare_parts_manager"],
        ["Live Modules", "IQC, Repair L1/L2/L3, QC, Stock/Lots, Sales, Dealers, CRM (Sourcing + Sales + Quotes), Spare Parts, Admin, Reports, Attendance, WhatsApp, Telecalling, Market Intel, Location Audit"],
        ["Device Stages", "14 stages: stock_in, iqc, l1, l2, l3, qc_check, ready_to_sale, sold, scrap, hold, dispatched, returned + cosmetic + transit"],
        ["Audit Trail", "Partial: covers approx. 35% of write operations (Sprint 16+ target: 100%)"],
        ["Security", "JWT httponly cookie, bcrypt, CSRF verify, 5/min login rate limit, 5-attempt 15-min lockout"],
        ["Compliance Score", "5.6/10 (April 2026) => Target: 8.3/10 (Q3 2026)"],
        ["Total DB Tables", "57 tables across all modules"],
      ],
      [2800, 5960]
    ),
    pageBreak(),
  ];
}

// ── Section 2: Business Objectives ───────────────────────────────────────────

function section2() {
  return [
    h1("2. Business Objectives", "s2"),
    dataTable(
      ["#", "Objective", "Business Metric"],
      [
        ["1", "Full device lifecycle traceability from lot purchase to sale with serial/barcode tracking at every stage", "Zero untraceable devices; full audit trail on all write operations"],
        ["2", "Real-time lot P&L: buying cost + parts + labour vs revenue => gross margin % per lot", "GM% per lot visible on dashboard; updated on every sale"],
        ["3", "Throughput maximisation: reduce device-days in each stage; identify stuck and dead-stock items", "Days-in-stage tracked; alert badge when >30 days stuck in one stage"],
        ["4", "Grade-driven pricing: auto-populate expected sale value from grade-price matrix; scrap trigger when cost >= 70% of expected sale", "Auto-scrap alert when total_cost >= 0.70 x expected_sale_value"],
        ["5", "B2B sales pipeline: dealer orders, credit limits, telecalling, CRM opportunities with WhatsApp invoice dispatch", "Outstanding receivables and overdue count on dashboard"],
        ["6", "R2V3 compliance readiness: IQC cosmetic grading, data wipe tracking, grade category capture", "R2V3 grade category field captured at IQC for all devices"],
        ["7", "Multi-tenant SaaS readiness: tenant column on users; schema-level isolation planned for v2", "Single codebase serves multiple ITAD operators by Q4 2026"],
      ],
      [400, 5000, 3360]
    ),
    para(""),
    h2("2.1 Key Business Rules"),
    bullet("A device cannot be sold unless current_stage = ready_to_sale (enforced by AllowedTransition DB table)"),
    bullet("Stage transitions are enforced by a finite state machine (validate_transition()) - no hardcoded stage logic in application code"),
    bullet("Lot buying_price is always pre-tax; GST (SGST/CGST/IGST) tracked separately on lot_line_items"),
    bullet("Device cost = lot buying_price / qty + spare parts consumed + repair attempt labour cost"),
    bullet("Scrap warning fires when total_cost >= 70% of expected_sale_value (SCRAP_WARNING_RATIO constant)"),
    bullet("Dealer credit limit enforced at order creation: order blocked if outstanding > credit_limit"),
    bullet("Login lockout: 5 failed attempts within 15 minutes => account locked for 15 minutes"),
    bullet("Admin stage-control UI allows adding/removing transitions without code changes or redeployment"),
    pageBreak(),
  ];
}

// ── Section 3: Module Descriptions ───────────────────────────────────────────

function section3() {
  return [
    h1("3. Module Descriptions", "s3"),

    h2("3.1 Authentication & User Management"),
    para("Role-based access control via JWT cookie (HS256, httponly, samesite=strict). 11 roles enforced through require_roles() FastAPI dependency on every protected route. Login events and failed-login attempts are written to login_logs table. Account lockout: 5 failed attempts in 15 minutes triggers a 15-minute lockout."),
    dataTable(
      ["Route", "Method", "Description", "Roles"],
      [
        ["/auth/login", "GET/POST", "Login page + JWT cookie issuance", "All"],
        ["/auth/logout", "POST", "Cookie deletion + redirect (CSRF verified)", "All"],
        ["/admin/users", "GET", "User list with role filter", "admin"],
        ["/admin/users/new", "GET/POST", "Create user + assign role", "admin"],
        ["/admin/users/{id}/edit", "GET/POST", "Edit user / toggle active status", "admin"],
      ],
      [2000, 900, 3500, 2360]
    ),
    para(""),

    h2("3.2 IQC - Incoming Quality Control"),
    para("First stage of device processing. IQC inspector registers each device from a lot and captures hardware specifications plus 50+ cosmetic and functional inspection fields. Device enters the system at stage='iqc'. Barcode must be globally unique across all devices."),
    dataTable(
      ["Key Feature", "Details"],
      [
        ["Hardware capture", "Brand, model, CPU, generation, RAM (GB), storage (GB/type), HDD, screen size, battery health %, BIOS password"],
        ["Cosmetic inspection", "14 screen condition fields, 20 panel (A/B/C/D) fields, keyboard (4), speaker, touchpad (5), ports HDMI/USB/audio"],
        ["R2V3 grading", "r2v3_grade_category captured for compliance readiness"],
        ["Barcode lookup", "JSON API at /iqc/lookup for barcode scanner quick-check"],
        ["Device pricing", "Auto-populated from LotLineItem.unit_price; fallback to lot average"],
      ],
      [2400, 6360]
    ),
    para(""),

    h2("3.3 Repair Pipeline - L1 / L2 / L3"),
    para("Three-tier repair pipeline. Each level creates repair_job and repair_attempt records. Parts consumed are logged to spare_parts_consumption. Stage transitions are validated through the FSM."),
    dataTable(
      ["Stage", "Scope", "Typical Actions"],
      [
        ["L1 - Basic Service", "Cleaning + diagnostics", "Dust cleaning, CMOS battery, thermal paste, RAM swap, HDD swap, basic diagnostics"],
        ["L2 - Component Replace", "Hardware replacement", "Screen replacement, keyboard, touchpad, battery, charger port, fan"],
        ["L3 - Complex Repair", "Board-level", "Motherboard repair, BGA rework, power section, GPU issues"],
      ],
      [1800, 2000, 4960]
    ),
    para(""),

    h2("3.4 QC - Quality Check"),
    para("Final pass/fail gate before a device reaches ready_to_sale. Inspector scores four dimensions: battery, screen, keyboard, body. Grade assigned (A/B/C/D/E/Scrap). Device moves to ready_to_sale on pass. Multiple QC attempt tracking supported. On pass, expected_sale_value auto-populated from grade-price matrix (Sprint 16)."),
    para(""),

    h2("3.5 Stock Management & GRN"),
    para("Lot-level inventory view. Each lot represents a batch purchase with a buying price and quantity. GRN (Goods Receipt Note) workflow validates lot arrival. Stock list shows per-lot device counts, sold counts, and P&L aggregation. Sprint 16 replaces the ORM aggregation with a PostgreSQL VIEW (vw_lot_pl)."),
    para(""),

    h2("3.6 Sales"),
    para("Retail and walk-in sale of individual devices. Records sale_price, customer details (name, phone, state), payment mode, and invoice number. Triggers device stage change to 'sold'. Returns workflow re-enters device at a designated stage. Sale number auto-generated (S-YEAR-NNNN)."),
    para(""),

    h2("3.7 Dealer Management"),
    para("B2B dealer relationship module with full financial lifecycle. Credit limit enforced at order creation. WhatsApp invoice dispatch integrated. Ageing statement and CSV ledger export available."),
    dataTable(
      ["Sub-module", "Key Features"],
      [
        ["Dealer Profile", "Credit limit, GSTIN, state, assigned sales rep, dealer type (retail/bulk/trader), status"],
        ["Dealer Orders", "Multi-item orders, invoice generation, payment tracking, due date alerts"],
        ["Credit Notes", "Issue credit note against order; apply to future order reducing due_amount"],
        ["Call Log", "Record calls with outcome, items discussed, quote given, next follow-up date, WhatsApp sent flag"],
        ["Ageing Report", "Outstanding by age bucket (0-30 / 31-60 / 61-90 / 90+ days)"],
        ["Statement Export", "Full ledger as CSV with all orders, payments, credit notes"],
      ],
      [2400, 6360]
    ),
    para(""),

    h2("3.8 CRM - Sourcing Pipeline"),
    para("Manages inbound supplier leads for bulk lot purchases. Deals progress through stages: lead => qualified => inspection => negotiation => po_issued => received => won/lost. Links to a Lot record when stock is received. CRM activities track every interaction. Deal number auto-generated (SD-YEAR-NNNN)."),
    para(""),

    h2("3.9 CRM - Sales Opportunities"),
    para("Manages outbound buyer leads and bulk sale opportunities. Links to quotes and individual sales. Tracks required specs, budget per unit, required grade, expected close date, and estimated deal value. Opportunity number auto-generated (OPP-YEAR-NNNN)."),
    para(""),

    h2("3.10 CRM - Quotes & Purchase Orders"),
    para("Formal quote generation for buyers (crm_quotes + crm_quote_items). Purchase order issuance to suppliers (crm_purchase_orders + crm_po_line_items). Grade-Price Matrix (crm_grade_price_matrix) provides min/max buy price, target sell price, and minimum margin % per device type + grade combination."),
    para(""),

    h2("3.11 Spare Parts"),
    para("Manages spare parts inventory used in repair operations. Stock-in from purchases updates qty_in_stock. Stock-out via repair job consumption decrements qty_in_stock. Low-stock alerts trigger when qty_in_stock <= min_stock_alert. Spare parts ledger maintains full movement history with cost tracking."),
    para(""),

    h2("3.12 Reports"),
    para("Management-only module (inventory_manager, sales_manager, admin). Key reports: Lot P&L, Stage-wise inventory snapshot, Sales revenue summary, Repair cost per device, Spare parts consumption, Dealer outstanding. All reports have CSV export. P&L and revenue reports now paginated."),
    para(""),

    h2("3.13 Admin, Stage Control & Attendance"),
    para("User management (create/edit/disable/role change). Stage transition control: add or remove allowed transitions from the UI without code changes. Master data management for dropdown values. App settings key-value store. Attendance check-in/check-out with IP capture and daily summary."),
    para(""),

    h2("3.14 WhatsApp Integration"),
    para("Browser-based WhatsApp session management for sending invoices and promotional broadcasts to dealer groups. Groups can be tagged and categorised. Broadcast log tracks sent count, failed count, and status per message campaign."),
    para(""),

    h2("3.15 Telecalling"),
    para("Tracks telecalling sessions by agent with daily targets (default 50 calls). Individual call records capture product interest, quantity required, budget, next follow-up date, and WhatsApp sent status. Follow-ups due today appear as a count on the dashboard."),
    para(""),

    h2("3.16 Market Intelligence"),
    para("Captures market availability listings (buy/sell) from WhatsApp groups and dealer networks. Records brand, model, grade, price per unit, dealer source, and message text. Used for competitive pricing intelligence and identifying sourcing opportunities."),
    para(""),

    h2("3.17 Inventory Location & Cycle Count"),
    para("Storage location management: zones (warehouse/floor), unit types (shelf/rack/bin), and slots. Devices are checked in/out of locations via barcode scan. Location gap report identifies devices not assigned to any location. Cycle count audit sessions compare expected vs. found counts."),
    pageBreak(),
  ];
}

// ── Section 4: Stage Flow ─────────────────────────────────────────────────────

function section4() {
  return [
    h1("4. Device Lifecycle - Stage Flow", "s4"),
    h2("4.1 End-to-End Flow Diagram"),
    codePara("                    ===  OxyPC Device Lifecycle  ==="),
    codePara(""),
    codePara("  [SUPPLIER]                                              [BUYER]"),
    codePara("      |                                                      |"),
    codePara("  CRM Sourcing Deal                                   CRM Sales Opp"),
    codePara("  lead->qualified->inspection->negotiation->po_issued  lead->quote->won"),
    codePara("      |                                                      |"),
    codePara("  Lot Created (GRN) ─────────────────────────────────> Sale Created"),
    codePara("      |                                                      ^"),
    codePara("      v                                                      |"),
    codePara("  [stock_in] ─── inventory_manager assigns lot to IQC       |"),
    codePara("      |                                                      |"),
    codePara("      v                                                      |"),
    codePara("   [iqc] ─── IQC Inspector: register device + 50-field      |"),
    codePara("      |         cosmetic inspection + R2V3 grade             |"),
    codePara("      v                                                      |"),
    codePara("    [l1] ─── L1 Engineer: clean + diagnose + RAM/HDD swap   |"),
    codePara("      |                                                      |"),
    codePara("      v                                                      |"),
    codePara("    [l2] ─── L2 Engineer: screen / keyboard / battery       |"),
    codePara("      |                                                      |"),
    codePara("      v                                                      |"),
    codePara("    [l3] ─── L3 Engineer: board-level repair                |"),
    codePara("      |                                                      |"),
    codePara("      v                                                      |"),
    codePara(" [qc_check] ─── QC Inspector: score (battery/screen/        |"),
    codePara("      |           keyboard/body) + assign grade A-E          |"),
    codePara("      v  PASS                                                |"),
    codePara(" [ready_to_sale] ─────────────────────────────────────────>-+"),
    codePara(""),
    codePara("  Special stages:"),
    codePara("  [scrap]      device cost >= 70% of expected sale, or QC fail threshold"),
    codePara("  [hold]       pending parts / approval / inspection decision"),
    codePara("  [dispatched] bulk B2B dispatch (not individual retail)"),
    codePara("  [returned]   customer return -> re-enters at designated stage"),
    para(""),
    h2("4.2 Stage Transition Rules"),
    para("All transitions governed by the allowed_transitions table. Admin can add/remove transitions from the Stage Control UI without code changes. The validate_transition() function enforces this table on every stage move."),
    dataTable(
      ["From Stage", "Valid Next Stages", "Who Can Move"],
      [
        ["stock_in", "iqc", "inventory_manager, admin"],
        ["iqc", "l1, l2, l3, qc_check, scrap, hold", "iqc_inspector, admin"],
        ["l1", "l2, l3, qc_check, scrap, hold", "l1_engineer, admin"],
        ["l2", "l1, l3, qc_check, scrap, hold", "l2_engineer, admin"],
        ["l3", "l2, qc_check, scrap, hold", "l3_engineer, admin"],
        ["qc_check", "ready_to_sale, l1, l2, l3, scrap, hold", "qc_inspector, admin"],
        ["ready_to_sale", "sold, hold, l1, l2, l3", "sales, sales_manager, admin"],
        ["hold", "iqc, l1, l2, l3, qc_check, scrap", "admin"],
        ["sold", "returned", "sales_manager, admin"],
        ["returned", "iqc, l1, l2, l3, qc_check", "inventory_manager, admin"],
      ],
      [2000, 3200, 3560]
    ),
    pageBreak(),
  ];
}

// ── Section 5: Dashboard Data Sources ────────────────────────────────────────

function section5() {
  return [
    h1("5. Dashboard - Data Sources & Update Workflows", "s5"),
    para("The dashboard is computed fresh on every page load with no caching layer. All metrics are live database queries. The table below maps every dashboard metric to the exact operational workflow that updates it."),
    para(""),
    h2("5.1 Dashboard Metric Map"),
    dataTable(
      ["Metric", "DB Query", "Updated By (Which Workflow)"],
      [
        ["Stage Counts (iqc, l1, l2... sold)", "GROUP BY devices.current_stage", "Any stage movement: IQC register -> L1/L2/L3 complete -> QC pass/fail -> Sale created"],
        ["Category Counts (Laptop / Desktop / TFT x stage)", "GROUP BY sub_category, current_stage", "Same as above - any device stage change updates both"],
        ["Available for Sale (ready_to_sale count)", "COUNT devices WHERE stage = ready_to_sale", "QC inspector marks device PASS -> stage auto-moves to ready_to_sale"],
        ["Today's Sales", "COUNT sales WHERE sold_at::date = today", "Sales module: new sale created at /sales/new"],
        ["Month Revenue", "SUM sale_price WHERE sold_at >= 1st of month", "Sales module: each new sale adds to running sum"],
        ["Lot P&L Table (buying/parts/labour/revenue/GM%)", "5 batch queries via GROUP BY on lots, devices, sales, spare_parts_consumption, repair_attempts", "Buying price: Lot created via GRN. Revenue: Sale created. Parts cost: Repair engineer issues spare part. Labour: Repair attempt cost saved"],
        ["Low Stock Alerts", "spare_parts WHERE qty_in_stock <= min_stock_alert", "Spare parts module: stock consumed in repair decrements qty_in_stock"],
        ["Dealer Outstanding Total", "SUM dealer_orders.due_amount WHERE status IN (pending, confirmed, delivered)", "Dealer module: order created adds to outstanding; payment recorded reduces due_amount"],
        ["Dealer Overdue Count", "COUNT dealer_orders WHERE due_amount > 0 AND payment_due_date < NOW()", "Becomes overdue automatically when payment_due_date passes with no payment"],
        ["Today's Follow-ups", "dealer_calls.next_followup_date + crm_activities.next_followup (not done)", "Sales rep logs a dealer call with next_followup_date; or CRM activity logged with next_followup"],
        ["Location Gap Count", "Devices not assigned to any storage_location", "Location module: barcode scanned to a storage unit clears the device from gap list"],
        ["Recent Stage Movements", "Last 10 stage_movements JOIN devices", "Every stage move writes a stage_movements record with from_stage, to_stage, moved_by, moved_at"],
        ["Role Queue (user-specific)", "Role-dependent count e.g. L1 engineer sees only l1 count", "Respective workflow: IQC register, repair complete, QC, sale etc."],
      ],
      [2200, 2600, 3960]
    ),
    para(""),
    h2("5.2 Per-Role Dashboard View"),
    dataTable(
      ["Role", "Metrics Shown"],
      [
        ["admin", "ALL: full stage counts, all role queues, lot P&L, dealer financials, low stock, location gaps, recent movements"],
        ["inventory_manager", "stock_in count, lot count, location gaps, low stock count, recent stage movements"],
        ["iqc_inspector", "IQC pending count"],
        ["l1_engineer", "L1 queue count"],
        ["l2_engineer", "L2 queue count"],
        ["l3_engineer", "L3 queue count"],
        ["qc_inspector", "QC pending count"],
        ["sales / telecaller", "ready_to_sale count, today's sales count, month revenue"],
        ["sales_manager", "ready_to_sale, today's sales, month revenue, dealer outstanding, dealer overdue count, dealer credit notes this month"],
        ["spare_parts_manager", "Low stock count, total parts value, today's consumption count"],
      ],
      [2400, 6360]
    ),
    para(""),
    h2("5.3 Lot P&L Calculation - Detailed Flow"),
    para("Every row in the Lot P&L table on the dashboard is built from 5 aggregation queries. Here is exactly how each number gets into the database:"),
    dataTable(
      ["P&L Component", "Entry Point", "Who Enters It"],
      [
        ["Buying Price (Investment)", "lots.buying_price set at lot creation", "inventory_manager creates lot via /stock/new or /grn/submit"],
        ["Parts Cost", "spare_parts_consumption.total_cost where lot_id matches", "l1/l2/l3 engineer issues spare part to repair job in Spare Parts module"],
        ["Labour Cost", "repair_attempts.cost where device.lot_id matches", "l1/l2/l3 engineer saves repair attempt with time spent and labour cost"],
        ["Revenue", "sales.sale_price joined to devices.lot_id", "sales / sales_manager creates sale via /sales/new; customer pays"],
        ["Gross Profit", "Calculated: revenue - buying - parts - labour", "Auto-computed on dashboard load; no manual entry required"],
        ["Gross Margin %", "profit / revenue x 100 (shown as 0% until first sale)", "Auto-computed; updates immediately on every new sale in the lot"],
      ],
      [2600, 2600, 3560]
    ),
    para("NOTE: These are currently raw ORM aggregation queries on every dashboard load. Sprint 16 Task T3 replaces them with a PostgreSQL VIEW (vw_lot_pl) to eliminate repeated computation and improve performance."),
    pageBreak(),
  ];
}

// ── Section 6: Schema ─────────────────────────────────────────────────────────

function section6() {
  return [
    h1("6. Database Schema - All 57 Tables", "s6"),
    para("Total tables: 57 | Database: PostgreSQL 15 | All PKs: UUID | Migrations: Alembic (11 versioned) | Naming: snake_case"),
    para(""),

    h2("6.1 User & Auth Tables (3 tables)"),
    h3("users"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["username", "varchar(50) UNIQUE", "Indexed - primary login key"],
      ["full_name", "varchar(100)", ""],
      ["password_hash", "varchar(200)", "bcrypt 12 rounds"],
      ["role", "varchar(50)", "admin / sales / iqc_inspector / etc."],
      ["status", "bool", "false = account disabled"],
      ["last_login", "datetime", "Updated on every successful login"],
      ["tenant", "varchar(50)", "Indexed - multi-tenant key (future SaaS)"],
    ]),
    para(""),
    h3("login_logs"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["user_id", "uuid [FK -> users]", ""],
      ["action", "varchar(50)", "login / login_failed / logout"],
      ["ip_address", "varchar(50)", ""],
      ["timestamp", "datetime", ""],
    ]),
    para(""),
    h3("user_permissions"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["user_id", "uuid [FK -> users]", ""],
      ["permission", "varchar(100)", "Fine-grained permission string"],
      ["granted", "bool", ""],
      ["granted_by", "varchar(50)", ""],
    ]),
    para(""),

    h2("6.2 Lot & GRN Tables (2 tables)"),
    h3("lots"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["lot_number", "varchar(20) UNIQUE", "Indexed - LOT-2026-001 format"],
      ["supplier_name", "varchar(200)", ""],
      ["grn_system_number", "varchar(50)", "Auto-generated GRN reference"],
      ["invoice_no / invoice_date", "varchar/datetime", "Supplier invoice"],
      ["invoice_value", "decimal(14,2)", "Total invoice value"],
      ["taxable_amount / sgst / cgst / igst", "decimal", "GST breakdown"],
      ["buying_price", "decimal(12,2)", "Total lot cost (pre-tax, NOT including GST)"],
      ["qty", "int", "Expected quantity of devices"],
      ["purchase_date", "datetime", ""],
    ]),
    para(""),
    h3("lot_line_items"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["lot_id", "uuid [FK -> lots]", "Indexed"],
      ["sub_category", "varchar(50)", "Laptop / Desktop / TFT"],
      ["brand / model / cpu / generation", "varchar", ""],
      ["ram_gb / storage_gb / storage_type / screen_size / grade", "various", ""],
      ["unit_price", "decimal(12,2)", "Price per unit in this line item"],
      ["qty", "int", "Quantity in this line"],
    ]),
    para(""),

    h2("6.3 Device & Stage Tables (4 tables)"),
    h3("devices"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["barcode", "varchar(100) UNIQUE", "Indexed - physical barcode sticker"],
      ["lot_id", "uuid [FK -> lots]", ""],
      ["brand / model / device_type", "varchar", "Indexed"],
      ["cpu / generation / ram_gb / storage_gb", "varchar/int", "Hardware specs from IQC"],
      ["battery_health_pct", "int", "0-100%"],
      ["bios_password", "bool", ""],
      ["grade", "varchar(10)", "Set at QC; A/B/C/D/E/Scrap"],
      ["current_stage", "varchar(30)", "Indexed - primary workflow state"],
      ["floor / warehouse", "varchar", "Physical location"],
      ["device_price", "decimal(12,2)", "Unit cost from lot or line item"],
      ["lot_line_item_id", "uuid [FK -> lot_line_items]", "Optional - for granular costing"],
      ["updated_at", "datetime", "Indexed - used for ageing calculations"],
    ]),
    para(""),
    h3("stage_movements"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["device_id", "uuid [FK -> devices]", ""],
      ["from_stage / to_stage", "varchar(30)", ""],
      ["moved_by", "varchar(50)", "Username of person who moved it"],
      ["moved_at / exited_at", "datetime", "Used for dwell time calculation"],
    ]),
    para(""),
    h3("device_aging"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["device_id", "uuid UNIQUE", "Indexed"],
      ["days_in_stage", "int", "Days in current stage"],
      ["total_days", "int", "Total days in system since IQC"],
      ["is_stuck", "bool", "Flag: exceeded per-stage threshold"],
      ["is_dead_stock", "bool", "Flag: >90 days total in system"],
    ]),
    para(""),
    h3("device_costing"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["device_id", "uuid UNIQUE", "Indexed - one record per device"],
      ["base_cost", "decimal(12,2)", "From lot buying_price / qty"],
      ["parts_cost", "decimal(12,2)", "Sum of spare_parts_consumption for this device"],
      ["labour_cost", "decimal(12,2)", "Sum of repair_attempt.cost for this device"],
      ["total_cost", "decimal(12,2)", "base + parts + labour"],
      ["expected_sale_value", "decimal(12,2)", "From crm_grade_price_matrix (Sprint 16 auto-populate)"],
    ]),
    para(""),

    h2("6.4 Inspection Tables (2 tables)"),
    h3("iqc_inspections"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["device_id", "uuid UNIQUE", "One inspection per device"],
      ["inspector_name", "varchar(100)", ""],
      ["power_on / all_ok / bios_password", "varchar(5)", "Yes / No flags"],
      ["status", "varchar(50)", "Functional status description"],
      ["r2v3_grade_category", "varchar(10)", "R2V3 compliance grade"],
      ["screen_* (14 fields)", "varchar", "dot/line/functional/discoloration/patch/broken/flickering/scratch/loose/missing/hinge_broken/colour_spread/keyboard_mark/hard_press"],
      ["panel_a/b/c/d_* (20 fields)", "varchar", "scratch/broken/missing/dent/colour_fade per panel"],
      ["keyboard_* (4 fields)", "varchar", "working/colour_fade/key_missing/hard_press"],
      ["speaker_status / touchpad_* (5) / port_* (3) / wifi/webcam/hdd_*/battery_*/dvd_drive", "varchar", "Remaining peripheral and port fields"],
    ]),
    para(""),
    h3("qc_checks"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["device_id", "uuid [FK -> devices]", "Indexed"],
      ["inspector_name", "varchar(100)", ""],
      ["battery_score / screen_score / keyboard_score / body_score", "int each", "Scoring dimensions 0-100"],
      ["total_score", "int", "Sum of all four scores"],
      ["result", "varchar(10)", "pass / fail"],
      ["grade", "varchar(5)", "A / B / C / D / E / Scrap"],
      ["attempt_number", "int", "QC retry count for this device"],
      ["send_to_stage", "varchar(20)", "Next stage: ready_to_sale, l1, l2, l3, scrap"],
    ]),
    para(""),

    h2("6.5 Repair Tables (3 tables)"),
    h3("repair_jobs"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["device_id", "uuid [FK -> devices]", "Indexed"],
      ["stage", "varchar(5)", "l1 / l2 / l3 - Indexed"],
      ["engineer_name / team_name", "varchar", ""],
      ["started_at / completed_at", "datetime", ""],
      ["faults", "text", "Fault description"],
      ["dust_cleaning / cmos_battery_change / thermal_paste", "varchar(20)", "Basic service checkboxes"],
      ["ram_removed_gb / ram_added_gb / hdd_removed / hdd_added", "varchar", "Component swap tracking"],
      ["final_status", "varchar(30)", "passed / failed / escalated / scrapped"],
    ]),
    para(""),
    h3("repair_attempts"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["device_id", "uuid [FK -> devices]", "Indexed"],
      ["repair_job_id", "uuid [FK -> repair_jobs]", ""],
      ["level", "int", "1 / 2 / 3 - repair tier"],
      ["attempt_no", "int", "Attempt count per device per level"],
      ["cost", "decimal(10,2)", "Labour cost for this attempt - feeds lot P&L"],
      ["time_spent", "int", "Minutes spent"],
      ["outcome", "varchar(30)", ""],
    ]),
    para(""),
    h3("ram_tracking"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["action", "varchar(20)", "add / remove / transfer"],
      ["device_id / destination_device_id", "uuid", "Source and destination devices"],
      ["ram_gb / ram_type", "int/varchar", ""],
    ]),
    para(""),

    h2("6.6 Sales Tables (2 tables)"),
    h3("sales"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["sale_number", "varchar(20) UNIQUE", "Indexed - S-2026-0001"],
      ["device_id", "uuid [FK -> devices]", ""],
      ["sale_price", "decimal(12,2)", ""],
      ["customer_name / phone / state", "varchar", ""],
      ["payment_mode", "varchar(20)", "cash / UPI / bank / credit"],
      ["sold_by", "varchar(50)", "Indexed"],
      ["sold_at", "datetime", ""],
    ]),
    para(""),
    h3("returns"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["sale_id / device_id", "uuid [FK]", "Indexed"],
      ["return_date", "datetime", ""],
      ["reason", "text", ""],
      ["action_taken", "varchar(30)", "restock / repair / scrap"],
      ["reentered_stage", "varchar(50)", "Stage device returns to on restock"],
      ["refund_amount", "decimal(12,2)", ""],
    ]),
    para(""),

    h2("6.7 Spare Parts Tables (4 tables)"),
    h3("spare_parts"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["part_code", "varchar(20) UNIQUE", "Indexed"],
      ["name", "varchar(150)", ""],
      ["category", "varchar(30)", "Screen / RAM / HDD / Battery / etc."],
      ["unit_price", "decimal(10,2)", ""],
      ["qty_in_stock", "int", "Current stock level - decremented on consumption"],
      ["min_stock_alert", "int", "Dashboard alert when qty_in_stock <= this"],
    ]),
    h3("spare_parts_purchases"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["part_id", "uuid [FK -> spare_parts]", ""],
      ["qty / unit_price / total_price", "int/decimal", ""],
      ["supplier / invoice_no", "varchar", ""],
      ["purchase_date", "datetime", ""],
    ]),
    h3("spare_parts_consumption"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["device_id / lot_id", "uuid [FK optional]", "Which device/lot used the part"],
      ["part_id", "uuid [FK -> spare_parts]", ""],
      ["qty_used", "int", ""],
      ["unit_cost / total_cost", "decimal", "Cost feeds device_costing.parts_cost"],
      ["stage", "varchar(20)", "Which repair stage consumed it: l1/l2/l3"],
    ]),
    h3("spare_parts_ledger"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["part_id", "uuid [FK]", "Indexed"],
      ["entry_type", "varchar(10)", "IN / OUT"],
      ["qty / cost_per_unit / total_cost", "int/decimal", ""],
      ["reference_type / reference_id", "varchar", "repair_job / purchase / adjustment"],
    ]),
    para(""),

    h2("6.8 Dealer Tables (4 tables)"),
    h3("dealers"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["dealer_code", "varchar(20) UNIQUE", "Indexed"],
      ["business_name", "varchar(200)", ""],
      ["phone / whatsapp_number / email / gstin", "varchar", ""],
      ["dealer_type", "varchar(30)", "retail / bulk / trader"],
      ["credit_limit", "decimal(14,2)", "Max outstanding allowed"],
      ["outstanding_amount", "decimal(14,2)", "Denormalised sum of open orders"],
      ["assigned_to", "varchar(50)", "Assigned sales rep username"],
    ]),
    h3("dealer_orders"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["dealer_id", "uuid [FK -> dealers]", ""],
      ["order_number", "varchar(30) UNIQUE", ""],
      ["total_amount / paid_amount / due_amount", "decimal(14,2)", "Financial tracking"],
      ["payment_due_date", "datetime", "Overdue check threshold"],
      ["status", "varchar(20)", "pending / confirmed / delivered / paid"],
    ]),
    h3("dealer_credit_notes"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["credit_number", "varchar(30) UNIQUE", "Indexed"],
      ["dealer_id / order_id", "uuid [FK]", "Indexed"],
      ["amount", "decimal(14,2)", ""],
      ["is_applied", "bool", "Has this credit been applied to an order"],
      ["applied_to_order_id", "uuid", "Which order it was applied against"],
    ]),
    h3("dealer_calls / dealer_assignments"),
    schemaTable([
      ["dealer_calls.id", "uuid [PK]", ""],
      ["dealer_id / called_by", "uuid/varchar", ""],
      ["call_type / call_mode / call_outcome", "varchar", "outbound/inbound, phone/WA/visit"],
      ["next_followup_date", "datetime", "Indexed - appears in dashboard follow-up count"],
      ["dealer_assignments.assigned_to", "varchar(50)", "Current sales rep assignment history"],
    ]),
    para(""),

    h2("6.9 CRM Tables (8 tables)"),
    h3("crm_contacts"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["contact_code", "varchar(20) UNIQUE", "Indexed"],
      ["contact_type", "varchar(20)", "supplier / buyer / both"],
      ["company_name", "varchar(200)", "Indexed"],
      ["phone / whatsapp / email / gstin / pan", "varchar", ""],
      ["credit_limit / outstanding", "decimal(14,2)", ""],
      ["assigned_to", "varchar(50)", ""],
    ]),
    h3("crm_sourcing_deals"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["deal_number", "varchar(30) UNIQUE", "Indexed - SD-2026-0001"],
      ["contact_id", "uuid [FK -> crm_contacts]", "Indexed"],
      ["title", "varchar(300)", ""],
      ["source_type / device_type / material_type", "varchar", ""],
      ["est_quantity", "int", ""],
      ["asking_price_unit/total / our_offer_unit/total", "decimal", "Negotiation price fields"],
      ["stage", "varchar(30)", "Indexed - lead/qualified/inspection/negotiation/po_issued/received/won/lost"],
      ["linked_lot_id", "uuid [FK -> lots]", "Set when stock received (lot created)"],
      ["priority", "varchar(10)", "low / medium / high / urgent"],
    ]),
    h3("crm_sales_opportunities"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["opp_number", "varchar(30) UNIQUE", "Indexed"],
      ["contact_id", "uuid [FK -> crm_contacts]", "Indexed"],
      ["device_type / grade_required / budget_per_unit", "varchar/decimal", ""],
      ["stage", "varchar(30)", "lead / contacted / quoted / negotiation / won / lost"],
      ["estimated_value", "decimal(14,2)", ""],
      ["expected_close_date", "date", ""],
    ]),
    h3("crm_quotes + crm_quote_items"),
    schemaTable([
      ["crm_quotes.quote_number", "varchar(30) UNIQUE", "Indexed"],
      ["contact_id / valid_until / total_amount", "uuid/date/decimal", ""],
      ["status", "varchar(20)", "draft / sent / accepted / rejected"],
      ["crm_quote_items.line_number / quantity / unit_price / total_price", "int/decimal", "One row per device type in quote"],
    ]),
    h3("crm_grade_price_matrix"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["device_type", "varchar(100)", "Indexed - Laptop / Desktop / TFT etc."],
      ["grade", "varchar(10)", "A / B / C / D / E"],
      ["brand", "varchar(50)", "Optional brand-specific override"],
      ["min_buy_price / max_buy_price", "decimal(10,2)", "Buy price range for negotiation"],
      ["target_sell", "decimal(10,2)", "Expected sale value - feeds expected_sale_value (Sprint 16)"],
      ["min_margin_pct", "decimal(5,2)", "Floor margin % (default 15%)"],
    ]),
    h3("crm_activities"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["contact_id / deal_id", "uuid [FK]", "Indexed"],
      ["deal_type", "varchar(20)", "sourcing / sales"],
      ["activity_type", "varchar(20)", "call / email / meeting / note / demo"],
      ["summary", "text", ""],
      ["next_followup", "datetime", "Indexed - appears in dashboard follow-up count"],
      ["followup_done", "bool", "Indexed - cleared when follow-up completed"],
    ]),
    h3("crm_purchase_orders + crm_po_line_items"),
    schemaTable([
      ["crm_purchase_orders.po_number", "varchar(30) UNIQUE", "Indexed"],
      ["deal_id / contact_id / total_amount", "uuid/decimal", ""],
      ["status", "varchar(20)", "draft / sent / confirmed / delivered"],
      ["crm_po_line_items.description / quantity / unit_price / total_price", "text/int/decimal", ""],
    ]),
    para(""),

    h2("6.10 Admin / Config Tables (4 tables)"),
    h3("stage_master + allowed_transitions"),
    schemaTable([
      ["stage_master.name", "varchar(50) UNIQUE", "Machine name: iqc, l1, l2, etc."],
      ["stage_master.label / sequence", "varchar/int", "Display name and sort order"],
      ["allowed_transitions.from_stage / to_stage", "varchar(50)", "UNIQUE pair - defines valid stage moves"],
    ]),
    h3("master_data"),
    schemaTable([
      ["id", "uuid [PK]", ""],
      ["category", "varchar(50)", "Indexed - dropdown category key"],
      ["value", "varchar(200)", "UNIQUE per category"],
      ["is_active", "bool", ""],
    ]),
    h3("app_settings"),
    schemaTable([
      ["key", "varchar(50) [PK]", "Setting key e.g. company_name"],
      ["value", "text", "Setting value"],
      ["updated_by / updated_at", "varchar/datetime", ""],
    ]),
    para(""),

    h2("6.11 Supporting / Operational Tables (14 tables)"),
    dataTable(
      ["Table", "Purpose", "Key Columns"],
      [
        ["audit_logs", "Append-only audit trail for all write operations", "user_id, action, table_name, record_id, old_value, new_value, timestamp (Indexed)"],
        ["storage_locations", "Physical warehouse zones, units, slots", "zone, unit_type, unit_id (UNIQUE), slot, capacity"],
        ["device_location_logs", "Device check-in/out to storage locations", "device_id, location_id, action, actor_name, logged_at (Indexed)"],
        ["inventory_audits", "Cycle count audit sessions", "audit_number (UNIQUE), zone_filter, expected_count, found_count, missing_count"],
        ["audit_scan_items", "Individual barcode scans during cycle count", "audit_id, device_id, barcode_scanned, scan_status, scanned_at"],
        ["stock_transfers", "Device transfers between warehouses", "device_id (Indexed), transfer_type, from_warehouse, to_warehouse, transfer_date"],
        ["attendance", "Staff check-in/check-out with IP", "user_id (Indexed), date (Indexed), check_in, check_out, check_in_ip, status"],
        ["telecalling_sessions", "Daily telecalling session summary per agent", "agent_username, total_calls, connected_calls, orders_placed, target_calls"],
        ["telecalling_records", "Individual call record with product interest", "phone, call_outcome, next_followup, quantity_required, budget, called_by"],
        ["whatsapp_sessions", "WhatsApp connection state per user", "username (UNIQUE), phone_number, status, connected_at"],
        ["whatsapp_messages", "All sent/received WhatsApp messages", "sent_by, recipient_phone, message_type, status, direction, sent_at"],
        ["whatsapp_groups", "WhatsApp groups for broadcast campaigns", "group_wa_id (UNIQUE), group_name, group_category, participant_count"],
        ["whatsapp_broadcasts", "Bulk broadcast campaign log", "broadcast_name, total_recipients, sent_count, failed_count, status"],
        ["market_availability", "Market price intel from WA groups/dealers", "brand, model, grade, price_per_unit, dealer_id, source_message_text, is_active"],
        ["supplier_payments", "Payments made to suppliers", "contact_id, lot_id, po_id, amount, payment_mode, payment_date"],
        ["customer_receipts", "Payments received from customers/dealers", "contact_id, dealer_id, sale_id, dealer_order_id, amount, receipt_date"],
        ["qa_requirements", "QA requirements registry", "req_code, title, source (PRD/UAT/etc.), priority, status, module"],
        ["qa_test_cases", "Test case library", "tc_code, title, type (Functional/RBAC/API/etc.), is_automated"],
        ["qa_test_executions", "Test run results", "test_case_id, status (Pass/Fail/Blocked), build_version, environment"],
        ["qa_defects", "Defect tracking", "defect_code, severity, priority (P0-P3), status (New/In Progress/Fixed/Closed)"],
      ],
      [2400, 2400, 3960]
    ),
    pageBreak(),
  ];
}

// ── Section 7: Gap Analysis ────────────────────────────────────────────────────

function section7() {
  return [
    h1("7. Gap Analysis - CLAUDE.md Compliance Audit (April 2026)", "s7"),
    para("Full audit conducted 2026-04-29. Scope: MCS 5-Layer, 7-Layer As-Is, Database-First Standards, Testing Strategy, Build Governance, Audit Trail Coverage, Pre-Commitment Profitability Gate."),
    para(""),
    h2("7.1 Overall Compliance Scorecard"),
    scorecardTable([
      ["L1 - Business Process", "6.5", "YELLOW", "IQC entry + lot creation write no audit log; admin bypass not logged distinctly"],
      ["L2 - Database / Schema", "6.0", "YELLOW", "No soft-delete, no stored procedures, no PostgreSQL views"],
      ["L3 - API / Backend", "5.0", "YELLOW", "2N+1 in stock.py fixed; no /api/v1/ versioning; no pagination on some routes"],
      ["L4 - UI / UX", "7.0", "YELLOW", "RBAC in templates correct; inline role checks removed in Sprint 15"],
      ["L5 - Security", "6.5", "YELLOW", "Fixed: .env secrets, rate limit, CSRF, bcrypt, lockout. Open: JWT revocation"],
      ["L6 - Deployment / DevOps", "3.5", "RED", "No CI pipeline, no cloud backup, no rollback runbook, no systemd service"],
      ["L7 - Financial / Reporting", "5.5", "YELLOW", "P&L correct; no margin floor config, no variance tracking"],
      ["Testing Strategy", "3.0", "RED", "API tests absent, RBAC tests absent, no CI, conftest added Sprint 15"],
      ["Audit Trail", "4.5", "RED", "~35% of write operations audited; user privilege changes untracked"],
      ["Pre-Commitment Profitability", "3.5", "RED", "No Deal Calculator, no margin floor table, no ACCEPT/RENEGOTIATE/DECLINE"],
      ["Build Governance", "4.0", "RED", "No change request template, no API versioning, no rollback runbook"],
      ["OVERALL", "5.6", "YELLOW", "3 RED areas require remediation before production. Target: 8.3 by Q3 2026"],
    ]),
    para(""),
    h2("7.2 Sprint 15 - Completed Fixes (April 2026)"),
    dataTable(
      ["Fix #", "Issue Resolved", "Status"],
      [
        ["1", "pytest + conftest.py + test DB fixture added to requirements.txt - enables all future API and RBAC testing", "DONE"],
        ["2", "2N+1 query loop in stock.py lot list (201 DB calls per page) replaced with single GROUP BY query", "DONE"],
        ["3", "Pagination (page/per_page) added to IQC, Stock, Repair, QC, Sales, Dealers list routes", "DONE"],
        ["4", "Audit log added for: user create/edit/disable, IQC device registration, lot creation, CRM deal create", "DONE"],
        ["5", "All 8 inline role checks in dealers.py replaced with Depends(require_roles()) / Depends(require_sales_mgr())", "DONE"],
        ["6", "Failed-login counter + 15-minute account lockout after 5 failed attempts in 15-minute window", "DONE"],
      ],
      [600, 5200, 1000]
    ),
    para(""),
    h2("7.3 Sprint 16 - Yellow Tier Gaps (In Progress)"),
    dataTable(
      ["#", "Gap", "Effort", "Task"],
      [
        ["7", "No PostgreSQL view for lot P&L - repeated ORM aggregation on every dashboard load (5 separate queries)", "3h", "T3"],
        ["8", "No /api/v1/ versioning prefix on routers/api.py - breaking change risk when multiple clients exist", "1h", "T1"],
        ["9", "No soft-delete pattern - db.delete() used throughout; deleted devices, lots, users leave no trail", "4h", "T2"],
        ["10", "expected_sale_value is always NULL - auto-scrap and margin warning engine never fire", "1 sprint", "T4"],
        ["11", "No rollback runbook for Alembic migrations - downgrade stubs exist but undocumented", "2h", "T6"],
        ["RBAC", "No automated test verifies role X cannot access route Y", "1 sprint", "T5"],
      ],
      [400, 4400, 1000, 800]
    ),
    para(""),
    h2("7.4 Stage 2 Gaps (SaaS Launch Readiness)"),
    bullet("Pre-Commitment Profitability Gate: margin floor check, ACCEPT/RENEGOTIATE/DECLINE verdict on every sourcing deal commit"),
    bullet("margin_floor_config table with effective dates: replace hardcoded SCRAP_WARNING_RATIO = 0.70 Python constant"),
    bullet("Immutable deal versioning: renegotiation creates a new CRMSourcingDeal version; original preserved read-only"),
    bullet("Row-level security policies in PostgreSQL: DB-layer RBAC, not just application layer"),
    bullet("Post-decision variance tracking: actuals vs. estimates on sourcing deals feed grade-price matrix refinement"),
    bullet("CI/CD pipeline: GitHub Actions running pytest on every push and PR"),
    bullet("Cloud backup: nightly pg_dump to offsite storage with 7-day retention and quarterly restore test"),
    bullet("JWT revocation / session blacklist: invalidate compromised tokens before 60-min TTL expires"),
    bullet("VAPT (Vulnerability Assessment and Penetration Test) before public SaaS launch"),
    pageBreak(),
  ];
}

// ── Section 8: Roadmap ────────────────────────────────────────────────────────

function section8() {
  return [
    h1("8. Feature Roadmap", "s8"),
    h2("8.1 Sprint 16 - Yellow Tier Remediation (Current)"),
    para("Plan file: docs/superpowers/plans/2026-04-29-sprint16-audit-yellow-tier.md"),
    dataTable(
      ["Task", "Description", "Files Changed", "Effort"],
      [
        ["T1 - API Versioning", "Add /api/v1/ prefix to routers/api.py; update all Jinja2 template AJAX fetch calls", "routers/api.py, templates/**/*.html", "1h"],
        ["T2 - Soft Delete", "Alembic migration: add deleted_at (datetime) + is_active (bool) to devices, lots, users. Update all db.delete() call sites to soft-delete pattern", "migrations/*, models/device.py, models/lot.py, models/user.py, ~8 router files", "4h"],
        ["T3 - vw_lot_pl VIEW", "CREATE OR REPLACE VIEW vw_lot_pl in PostgreSQL; dashboard queries this view; reports.py updated to use the view", "migrations/*, routers/dashboard.py, routers/reports.py", "3h"],
        ["T4 - expected_sale_value", "New function set_expected_sale_value_from_matrix() in services/cost_engine.py: brand-specific lookup first, fallback to device_type+grade. Called from routers/qc.py on QC pass", "services/cost_engine.py, routers/qc.py", "1 sprint"],
        ["T5 - RBAC API Tests", "async_client fixture with override_get_db in tests/conftest.py; 15 test cases in tests/test_rbac.py verifying role-based access control boundaries", "tests/conftest.py, tests/test_rbac.py", "1 sprint"],
        ["T6 - Migration Runbook", "Markdown document: per-migration rollback procedure, data impact assessment, pre/post validation SQL for all 11 migrations", "docs/migration-runbook.md", "2h"],
      ],
      [1800, 3000, 2400, 800]
    ),
    para(""),
    h2("8.2 Sprint 17-18 - Planned"),
    dataTable(
      ["Feature", "Description", "Priority"],
      [
        ["Pre-Commitment Profitability Gate", "Margin floor check on CRM sourcing deal commit: calculate GM%, compare to floor, return ACCEPT/RENEGOTIATE/DECLINE", "HIGH"],
        ["margin_floor_config table", "DB-stored floor config with effective dates, replacing hardcoded SCRAP_WARNING_RATIO constant", "HIGH"],
        ["Full audit trail coverage", "Audit log on ALL write operations: user privilege changes, spare parts consumption, lot edits", "HIGH"],
        ["Immutable deal versioning", "Renegotiation creates new CRMSourcingDeal version; original preserved read-only with version number", "MEDIUM"],
        ["JWT revocation", "Session blacklist table or Redis TTL-based revocation for compromised tokens", "MEDIUM"],
        ["CI/CD pipeline", "GitHub Actions: run pytest on every PR; block merge on test failure", "MEDIUM"],
        ["Cloud backup", "Nightly pg_dump to cloud storage; 7-day retention; quarterly restore test and runbook", "MEDIUM"],
      ],
      [2800, 4000, 960]
    ),
    para(""),
    h2("8.3 Stage 2 - SaaS Launch Readiness"),
    dataTable(
      ["Feature", "Description"],
      [
        ["Multi-tenant schema routing", "Separate PostgreSQL schema per tenant; tenant column on users table already in place"],
        ["Row-level security", "PostgreSQL RLS policies enforcing data isolation at DB level, not just application"],
        ["ESG / Compliance module", "R2V3 certificates, data wipe certificates, recycling tonnage reports, disposal compliance"],
        ["OEM Partner Portal", "Read-only customer portal for enterprise clients to track their assets through lifecycle"],
        ["Post-decision variance tracking", "Actuals vs. estimate on every sourcing deal; feeds grade-price matrix refinement engine"],
        ["AI Intelligence Layer", "Price prediction, sourcing recommendation, anomaly detection via read-only replica + pgvector"],
        ["OpenAPI spec export", "Auto-publish /openapi.json; generate client SDKs for OEM partner integrations"],
        ["VAPT", "Vulnerability Assessment and Penetration Test before public SaaS launch"],
      ],
      [2800, 5960]
    ),
    pageBreak(),
  ];
}

// ── Section 9: RBAC Matrix ────────────────────────────────────────────────────

function section9() {
  return [
    h1("9. RBAC Permission Matrix", "s9"),
    para("Role enforcement via FastAPI Depends(require_roles()) on every protected route. Admin can access all routes. Enforcement is application-layer only (DB row-level security planned for Stage 2)."),
    para(""),
    dataTable(
      ["Module / Route", "admin", "inv_mgr", "iqc_insp", "l1", "l2", "l3", "qc_insp", "sales", "sales_mgr", "tcaller", "parts_mgr"],
      [
        ["IQC Register + List", "Y", "Y", "Y", "-", "-", "-", "-", "-", "-", "-", "-"],
        ["L1 Repair", "Y", "-", "-", "Y", "-", "-", "-", "-", "-", "-", "-"],
        ["L2 Repair", "Y", "-", "-", "-", "Y", "-", "-", "-", "-", "-", "-"],
        ["L3 Repair", "Y", "-", "-", "-", "-", "Y", "-", "-", "-", "-", "-"],
        ["QC Check", "Y", "Y", "Y", "-", "-", "-", "Y", "-", "-", "-", "-"],
        ["Stock / Lots / GRN", "Y", "Y", "-", "-", "-", "-", "-", "-", "-", "-", "-"],
        ["Sales / Invoice", "Y", "-", "-", "-", "-", "-", "-", "Y", "Y", "Y", "-"],
        ["Returns", "Y", "-", "-", "-", "-", "-", "-", "-", "Y", "-", "-"],
        ["Dealers - View", "Y", "-", "-", "-", "-", "-", "-", "Y", "Y", "-", "-"],
        ["Dealers - Orders", "Y", "-", "-", "-", "-", "-", "-", "Y", "Y", "-", "-"],
        ["Dealers - Credit Notes", "Y", "-", "-", "-", "-", "-", "-", "-", "Y", "-", "-"],
        ["CRM Sourcing", "Y", "Y", "-", "-", "-", "-", "-", "-", "Y", "-", "-"],
        ["CRM Sales Opp", "Y", "-", "-", "-", "-", "-", "-", "Y", "Y", "Y", "-"],
        ["CRM Quotes / PO", "Y", "Y", "-", "-", "-", "-", "-", "-", "Y", "-", "-"],
        ["Spare Parts", "Y", "-", "-", "Y", "Y", "Y", "-", "-", "-", "-", "Y"],
        ["Reports", "Y", "Y", "-", "-", "-", "-", "-", "-", "Y", "-", "-"],
        ["Admin / Users", "Y", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-"],
        ["Stage Control", "Y", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-"],
        ["Attendance", "Y", "Y", "Y", "Y", "Y", "Y", "Y", "Y", "Y", "Y", "Y"],
        ["Telecalling", "Y", "-", "-", "-", "-", "-", "-", "Y", "Y", "Y", "-"],
        ["WhatsApp", "Y", "-", "-", "-", "-", "-", "-", "Y", "Y", "-", "-"],
        ["Market Intel", "Y", "Y", "-", "-", "-", "-", "-", "Y", "Y", "-", "-"],
      ],
      [2400, 500, 600, 600, 500, 500, 500, 600, 500, 600, 600, 680]
    ),
    pageBreak(),
  ];
}

// ── Section 10: Security ───────────────────────────────────────────────────────

function section10() {
  return [
    h1("10. Security Architecture", "s10"),
    h2("10.1 Authentication Stack"),
    bullet("JWT HS256 token issued on login, stored as httponly samesite=strict cookie (JavaScript cannot read it)"),
    bullet("Token TTL: ACCESS_TOKEN_EXPIRE_MINUTES (default 60 minutes, configurable via .env)"),
    bullet("bcrypt password hashing with 12 rounds"),
    bullet("5-attempt login lockout: 5 failed attempts in 15-minute window triggers 15-minute block (via login_logs counter)"),
    bullet("Rate limit: 5 POST /auth/login per minute per IP via slowapi"),
    bullet("CSRF token (64-char hex) set as readable JS cookie; verified on every POST route via Depends(verify_csrf)"),
    para(""),
    h2("10.2 Secrets Management"),
    bullet("All secrets in .env (gitignored): SECRET_KEY, DATABASE_URL, BACKUP credentials"),
    bullet("config.py reads exclusively from os.environ - no hardcoded values"),
    bullet("OXYPC_DEBUG=1 gates detailed error stack traces; set to 0 on production"),
    para(""),
    h2("10.3 Known Open Risks"),
    dataTable(
      ["Risk", "Severity", "Status", "Sprint Target"],
      [
        ["JWT has no revocation mechanism - compromised token valid for full 60-min TTL", "Medium", "Open", "17"],
        ["HS256 symmetric JWT - SECRET_KEY leak allows forging tokens for any role", "Low", "Accepted risk", "17"],
        ["RBAC is application-layer only - no PostgreSQL row-level security policies", "Medium", "Open", "Stage 2"],
        ["No PII field-level encryption on users/dealers/crm_contacts tables", "Medium", "Open", "Stage 2"],
        ["No VAPT performed - unknown vulnerability surface", "High", "Open", "Before production"],
        ["Admin stage FSM bypass not logged as a distinct audit event", "Medium", "Open", "17"],
        ["No session invalidation on role change or account disable", "Medium", "Open", "17"],
      ],
      [3400, 1100, 1200, 1060]
    ),
    pageBreak(),
  ];
}

// ── Section 11: Tech Stack ────────────────────────────────────────────────────

function section11() {
  return [
    h1("11. Technical Stack", "s11"),
    dataTable(
      ["Component", "Technology", "Version / Notes"],
      [
        ["Backend Framework", "FastAPI", "Python 3.12 - async, dependency injection, auto OpenAPI at /docs"],
        ["ORM", "SQLAlchemy 2.0", "AsyncSession pattern; async_scoped_session for request isolation"],
        ["Database", "PostgreSQL 15", "Local install on server; pgvector extension ready for future AI layer"],
        ["Migrations", "Alembic", "11 versioned migrations; alembic upgrade head on deploy"],
        ["Template Engine", "Jinja2 + Bootstrap 5", "Server-side rendered HTML; no SPA framework"],
        ["Authentication", "python-jose + passlib", "JWT HS256 + bcrypt 12 rounds"],
        ["Rate Limiting", "slowapi", "5/min on POST /auth/login"],
        ["DB Connection Pool", "SQLAlchemy async pool", "pool_size=20, max_overflow=10, pool_pre_ping=True"],
        ["PDF Generation", "WeasyPrint + Jinja2", "Invoice and compliance report PDF generation"],
        ["WhatsApp", "Custom session library", "Browser-based WA session for message dispatch"],
        ["Process Server", "Uvicorn", "Current: uvicorn main:app --host 0.0.0.0 --port 8000"],
        ["Testing (Sprint 16)", "pytest + httpx", "conftest.py with async_client fixture and transactional test DB"],
        ["Schema Management", "dbdiagram.io (DBML)", "Single source of truth for all table definitions"],
      ],
      [2200, 2600, 3960]
    ),
    pageBreak(),
  ];
}

// ── Section 12: Deployment ────────────────────────────────────────────────────

function section12() {
  return [
    h1("12. Deployment & Configuration", "s12"),
    h2("12.1 Current Server Configuration"),
    dataTable(
      ["Parameter", "Current Value", "Notes"],
      [
        ["Server IP (LAN)", "192.168.7.247", "Ethernet 5 NIC - verify with ipconfig if changed"],
        ["Port", "8000", "Windows Firewall inbound rule required (run as Admin)"],
        ["Process Management", "Uvicorn (direct)", "No systemd / NSSM service - manual restart needed"],
        ["Database", "PostgreSQL on localhost:5432", "DATABASE_URL in .env"],
        ["Token TTL", "60 minutes (default)", "Set ACCESS_TOKEN_EXPIRE_MINUTES in .env"],
        ["Debug Mode", "OXYPC_DEBUG=0 (production)", "Set to 1 for stack traces in development"],
        ["Backup", "pg_dump cron (local only)", "No offsite backup - Sprint 17 critical action"],
        ["WiFi Status", "Wi-Fi 6 adapter disconnected", "Use Ethernet IP 192.168.7.247 for LAN access"],
      ],
      [2400, 2800, 3560]
    ),
    para(""),
    h2("12.2 Required .env Variables"),
    codePara("DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/oxypc_db"),
    codePara("SECRET_KEY=<generate: python -c \"import secrets; print(secrets.token_hex(32))\">"),
    codePara("ACCESS_TOKEN_EXPIRE_MINUTES=60"),
    codePara("OXYPC_DEBUG=0"),
    codePara("BACKUP_DB_NAME=oxypc_db"),
    codePara("BACKUP_DIR=C:/backups/oxypc"),
    para(""),
    h2("12.3 LAN Access Setup"),
    para("Run these commands as Administrator on the server machine:"),
    codePara("# 1. Find current server IP"),
    codePara("ipconfig | findstr IPv4"),
    codePara(""),
    codePara("# 2. Add Windows Firewall rule"),
    codePara("netsh advfirewall firewall add rule name=\"OxyPC Port 8000\" dir=in action=allow protocol=TCP localport=8000"),
    codePara(""),
    codePara("# 3. Start server"),
    codePara("cd C:\\Users\\Pankaj.sehgal\\Claude\\Oxypc\\oxypc-inventory"),
    codePara("python -m uvicorn main:app --host 0.0.0.0 --port 8000"),
    para("Client devices connect to: http://<server-IP>:8000 (not localhost)"),
    pageBreak(),
  ];
}

// ── Section 13: Appendix ──────────────────────────────────────────────────────

function section13() {
  return [
    h1("13. Appendix", "s13"),
    h2("13.1 Audit Score History"),
    dataTable(
      ["Layer", "Apr 26", "Apr 28", "Apr 29 (Current)", "Target"],
      [
        ["L1 Business Process", "6.0", "7.0", "6.5", "8.0"],
        ["L2 Database / Schema", "5.5", "6.0", "6.0", "8.0"],
        ["L3 API / Backend", "4.0", "4.5", "5.0", "8.0"],
        ["L4 UI / UX", "5.5", "7.0", "7.0", "8.0"],
        ["L5 Security", "3.5", "3.5", "6.5", "8.5"],
        ["L6 Deployment / DevOps", "3.0", "3.5", "3.5", "8.0"],
        ["L7 Financial / Reporting", "5.0", "5.5", "5.5", "8.5"],
        ["OVERALL", "4.9", "5.3", "5.6", "8.3"],
      ],
      [2600, 1200, 1200, 1600, 1200]
    ),
    para(""),
    h2("13.2 Module to File Mapping"),
    dataTable(
      ["Module", "Router File", "Model File(s)", "Template Directory"],
      [
        ["Auth", "routers/auth.py", "models/user.py", "login.html"],
        ["IQC", "routers/iqc.py", "models/device.py, models/iqc_inspection.py", "templates/iqc/"],
        ["Repair L1/L2/L3", "routers/repair.py", "models/device.py, models/engines.py", "templates/repair/"],
        ["QC", "routers/qc.py", "models/device.py, models/qc.py", "templates/qc/"],
        ["Stock / Lots", "routers/stock.py, grn.py", "models/lot.py", "templates/stock/, grn/"],
        ["Sales", "routers/sales.py", "models/sales.py", "templates/sales/"],
        ["Dealers", "routers/dealers.py", "models/dealers.py", "templates/dealers/"],
        ["CRM Sourcing", "routers/crm_sourcing.py", "models/crm.py", "templates/crm/sourcing/"],
        ["CRM Sales Opp", "routers/crm_sales.py", "models/crm.py", "templates/crm/sales/"],
        ["CRM Quotes", "routers/crm_quotes.py", "models/crm.py", "templates/crm/quotes/"],
        ["CRM Price Matrix", "routers/crm_price_matrix.py", "models/crm.py", "templates/crm/price_matrix/"],
        ["Spare Parts", "routers/spare_parts.py", "models/spare_parts.py", "templates/spare_parts/"],
        ["Reports", "routers/reports.py", "multiple", "templates/reports/"],
        ["Admin", "routers/admin.py", "models/user.py", "templates/admin/"],
        ["Dashboard", "routers/dashboard.py", "multiple", "templates/dashboard.html"],
        ["Attendance", "routers/attendance.py", "models/user.py", "templates/attendance/"],
        ["WhatsApp", "routers/whatsapp.py", "models/whatsapp.py", "templates/whatsapp/"],
        ["Telecalling", "routers/telecalling.py", "models/crm.py", "templates/telecalling/"],
        ["Market Intel", "routers/market.py", "models/crm.py", "templates/market/"],
        ["Location Audit", "routers/inventory_location.py", "models/location.py", "templates/location/"],
        ["API (JSON)", "routers/api.py", "multiple", "—"],
        ["Accounts", "routers/accounts.py", "models/dealers.py", "templates/accounts/"],
      ],
      [2200, 2400, 2200, 1960]
    ),
    para(""),
    h2("13.3 Document Version History"),
    dataTable(
      ["Version", "Date", "Changes"],
      [
        ["v1.0", "Jan 2026", "Initial BRD - core IQC, Repair, QC, Sales modules"],
        ["v2.0", "Mar 2026", "Added CRM, Dealer, WhatsApp, Telecalling modules"],
        ["v3.0", "Apr 26 2026", "Post-audit update - security fixes, performance fixes, pagination"],
        ["v4.0", "Apr 29 2026", "Sprint 15 complete; Sprint 16 plan; full 57-table schema; dashboard workflow map; RBAC matrix; complete gap analysis"],
      ],
      [800, 1400, 6560]
    ),
  ];
}

// ── Build Document ────────────────────────────────────────────────────────────

const doc = new Document({
  numbering: {
    config: [{
      reference: "bullets",
      levels: [{
        level: 0,
        format: LevelFormat.BULLET,
        text: "•",
        alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } },
      }],
    }],
  },
  styles: {
    default: {
      document: { run: { font: "Arial", size: 22 } },
    },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: "2B6CB0" },
        paragraph: { spacing: { before: 360, after: 180 }, outlineLevel: 0 },
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: "2D3748" },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 },
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: "4A5568" },
        paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 2 },
      },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 },
      },
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "2B6CB0", space: 1 } },
          children: [
            new TextRun({ text: "OxyPC Inventory Management System  |  BRD v4.0  |  CONFIDENTIAL  |  April 2026", font: "Arial", size: 18, color: "4A5568" }),
          ],
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          border: { top: { style: BorderStyle.SINGLE, size: 4, color: "2B6CB0", space: 1 } },
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: "Page ", font: "Arial", size: 18, color: "718096" }),
            new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 18, color: "718096" }),
            new TextRun({ text: " of ", font: "Arial", size: 18, color: "718096" }),
            new TextRun({ children: [PageNumber.TOTAL_PAGES], font: "Arial", size: 18, color: "718096" }),
          ],
        })],
      }),
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
      ...section13(),
    ],
  }],
});

Packer.toBuffer(doc).then(buf => {
  const out = "C:/Users/Pankaj.sehgal/Claude/Oxypc/oxypc-inventory/docs/OxyPC_BRD_v4_Complete.docx";
  fs.writeFileSync(out, buf);
  console.log("BRD written => " + out);
  console.log("Size: " + (buf.length / 1024).toFixed(0) + " KB");
}).catch(err => {
  console.error("FAILED:", err.message);
  process.exit(1);
});
