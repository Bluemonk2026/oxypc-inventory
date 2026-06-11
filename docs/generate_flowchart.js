"use strict";
const {
  Document, Packer, Paragraph, Table, TableRow, TableCell,
  TextRun, AlignmentType, WidthType, BorderStyle, ShadingType,
  PageOrientation, VerticalAlign, PageBreak
} = require("docx");
const fs = require("fs");

// ─── Constants ───────────────────────────────────────────────────────────────
const CONTENT_W = 15398; // DXA (16838 - 1440 margins)

// Colors (no #)
const C = {
  navy:      "1565C0",
  teal:      "00897B",
  orange:    "E65100",
  green:     "2E7D32",
  purple:    "6A1B9A",
  grey:      "455A64",
  pink:      "880E4F",
  white:     "FFFFFF",
  lightBlue: "E3F2FD",
  lightGreen:"E8F5E9",
  lightOrange:"FFF3E0",
  lightPurple:"F3E5F5",
  lightPink: "FCE4EC",
  lightTeal: "E0F2F1",
  lightGrey: "ECEFF1",
  greenCheck:"C8E6C9",
  black:     "000000",
  border:    "CCCCCC",
};

// ─── Border helpers ───────────────────────────────────────────────────────────
const bdr = (color = C.border) => ({ style: BorderStyle.SINGLE, size: 4, color });
const borders = (color = C.border) => ({
  top: bdr(color), bottom: bdr(color), left: bdr(color), right: bdr(color),
});
const noBorders = () => ({
  top: { style: BorderStyle.NONE, size: 0, color: C.white },
  bottom: { style: BorderStyle.NONE, size: 0, color: C.white },
  left: { style: BorderStyle.NONE, size: 0, color: C.white },
  right: { style: BorderStyle.NONE, size: 0, color: C.white },
});

// ─── Cell / Paragraph helpers ─────────────────────────────────────────────────
function shade(fill) {
  return { fill, type: ShadingType.CLEAR, color: "auto" };
}

function cell(text, {
  fill = C.white, textColor = C.black, bold = false,
  width = 0, align = AlignmentType.LEFT,
  vertAlign = VerticalAlign.CENTER, fontSize = 18,
  colSpan = 1,
} = {}) {
  const opts = {
    shading: shade(fill),
    borders: borders(C.border),
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    verticalAlign: vertAlign,
    children: [new Paragraph({
      alignment: align,
      children: [new TextRun({ text, color: textColor, bold, size: fontSize, font: "Arial" })],
    })],
  };
  if (width) opts.width = { size: width, type: WidthType.DXA };
  if (colSpan > 1) opts.columnSpan = colSpan;
  return new TableCell(opts);
}

function headerCell(text, fill = C.navy, width = 0, colSpan = 1) {
  return cell(text, { fill, textColor: C.white, bold: true, width, align: AlignmentType.CENTER, fontSize: 18, colSpan });
}

function arrowCell(width = 300) {
  return cell("→", { fill: C.white, textColor: C.grey, bold: true, width, align: AlignmentType.CENTER, fontSize: 20 });
}

function row(...cells) { return new TableRow({ children: cells }); }

function spacerRow(cols, fill = C.white) {
  return new TableRow({
    children: [new TableCell({
      columnSpan: cols,
      borders: noBorders(),
      shading: shade(fill),
      children: [new Paragraph({ children: [new TextRun({ text: "", size: 8 })] })],
    })],
  });
}

function sectionHeaderRow(text, fill, cols, colWidths) {
  return new TableRow({
    children: [new TableCell({
      columnSpan: cols,
      shading: shade(fill),
      borders: borders(fill),
      margins: { top: 100, bottom: 100, left: 140, right: 140 },
      children: [new Paragraph({
        children: [new TextRun({ text, color: C.white, bold: true, size: 20, font: "Arial" })],
      })],
    })],
  });
}

// ─── Page heading helper ──────────────────────────────────────────────────────
function pageTitle(title, subtitle = "") {
  const items = [
    new Paragraph({
      alignment: AlignmentType.LEFT,
      spacing: { before: 0, after: 120 },
      children: [new TextRun({ text: title, color: C.navy, bold: true, size: 36, font: "Arial" })],
    }),
  ];
  if (subtitle) {
    items.push(new Paragraph({
      alignment: AlignmentType.LEFT,
      spacing: { before: 0, after: 240 },
      children: [new TextRun({ text: subtitle, color: C.grey, size: 22, font: "Arial" })],
    }));
  } else {
    items.push(new Paragraph({ spacing: { after: 200 }, children: [new TextRun("")] }));
  }
  return items;
}

function pb() { return new Paragraph({ children: [new PageBreak()] }); }

// ─── PAGE 1: COVER ────────────────────────────────────────────────────────────
function makeCover() {
  return [
    new Paragraph({ spacing: { before: 2400, after: 400 }, alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "OxyPC Refurbishment ERP", color: C.navy, bold: true, size: 72, font: "Arial" })] }),
    new Paragraph({ spacing: { before: 0, after: 300 }, alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "Complete Application Flow", color: C.navy, bold: true, size: 56, font: "Arial" })] }),
    new Paragraph({ spacing: { before: 0, after: 600 }, alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "End-to-End Process Maps for All 12 Modules", color: C.teal, size: 36, font: "Arial" })] }),
    // Divider line using border on paragraph
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 600 },
      border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: C.teal, space: 4 } },
      children: [new TextRun({ text: "", size: 4 })],
    }),
    new Paragraph({ spacing: { before: 0, after: 200 }, alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "27 April 2026", color: C.grey, size: 28, font: "Arial" })] }),
    new Paragraph({ spacing: { before: 0, after: 200 }, alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "OxyPC Technologies", color: C.grey, size: 24, font: "Arial" })] }),
    new Paragraph({ spacing: { before: 0, after: 200 }, alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "CONFIDENTIAL — INTERNAL USE ONLY", color: C.orange, bold: true, size: 22, font: "Arial" })] }),
    pb(),
  ];
}

// ─── PAGE 2: MODULE OVERVIEW ──────────────────────────────────────────────────
function makeModuleOverview() {
  const colW = Math.floor(CONTENT_W / 4);
  const cols = [colW, colW, colW, CONTENT_W - colW * 3];

  // Helper for a module cell
  const mc = (text, fill) => new TableCell({
    shading: shade(fill),
    borders: borders(C.white),
    margins: { top: 160, bottom: 160, left: 140, right: 140 },
    width: { size: colW, type: WidthType.DXA },
    verticalAlign: VerticalAlign.CENTER,
    children: [
      new Paragraph({ alignment: AlignmentType.CENTER,
        children: [new TextRun({ text, color: C.white, bold: true, size: 22, font: "Arial" })] }),
    ],
  });

  const moduleTable = new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: cols,
    rows: [
      // Header row
      new TableRow({ children: [
        new TableCell({ columnSpan: 4, shading: shade(C.navy), borders: borders(C.navy),
          margins: { top: 120, bottom: 120, left: 140, right: 140 },
          children: [new Paragraph({ alignment: AlignmentType.CENTER,
            children: [new TextRun({ text: "OxyPC ERP — 12 Core Modules", color: C.white, bold: true, size: 28, font: "Arial" })] })] }),
      ] }),
      // Category labels
      new TableRow({ children: [
        new TableCell({ shading: shade(C.navy), borders: borders(C.navy), margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ alignment: AlignmentType.CENTER,
            children: [new TextRun({ text: "CORE OPERATIONS", color: C.white, bold: true, size: 18, font: "Arial" })] })] }),
        new TableCell({ shading: shade(C.teal), borders: borders(C.teal), margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ alignment: AlignmentType.CENTER,
            children: [new TextRun({ text: "FINANCIAL", color: C.white, bold: true, size: 18, font: "Arial" })] })] }),
        new TableCell({ shading: shade(C.orange), borders: borders(C.orange), margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ alignment: AlignmentType.CENTER,
            children: [new TextRun({ text: "CRM", color: C.white, bold: true, size: 18, font: "Arial" })] })] }),
        new TableCell({ shading: shade(C.grey), borders: borders(C.grey), margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ alignment: AlignmentType.CENTER,
            children: [new TextRun({ text: "SUPPORT / ADMIN", color: C.white, bold: true, size: 18, font: "Arial" })] })] }),
      ] }),
      // Row 1
      new TableRow({ children: [mc("Lot & GRN", C.navy), mc("Dealers", C.teal), mc("CRM Contacts", C.orange), mc("WhatsApp", C.grey)] }),
      // Row 2
      new TableRow({ children: [mc("IQC", C.navy), mc("Accounts", C.teal), mc("Sourcing Pipeline", C.orange), mc("Market Intel", C.grey)] }),
      // Row 3
      new TableRow({ children: [mc("Repair", C.navy), mc("Reports", C.teal), mc("Sales Pipeline", C.orange), mc("Attendance", C.grey)] }),
      // Row 4
      new TableRow({ children: [mc("QC", C.navy),
        new TableCell({ shading: shade(C.lightGrey), borders: borders(C.white),
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "", size: 18 })] })] }),
        new TableCell({ shading: shade(C.lightGrey), borders: borders(C.white),
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "", size: 18 })] })] }),
        mc("Admin", C.grey)] }),
      // Row 5
      new TableRow({ children: [mc("Stock", C.navy),
        new TableCell({ shading: shade(C.lightGrey), borders: borders(C.white),
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "", size: 18 })] })] }),
        new TableCell({ shading: shade(C.lightGrey), borders: borders(C.white),
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "", size: 18 })] })] }),
        mc("Settings", C.grey)] }),
      // Row 6
      new TableRow({ children: [mc("Sales", C.navy),
        new TableCell({ columnSpan: 3, shading: shade(C.lightGrey), borders: borders(C.white),
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ children: [new TextRun({ text: "", size: 18 })] })] }),
      ] }),
    ],
  });

  return [
    ...pageTitle("Module Overview — 12 Core Modules", "Color-coded by functional category"),
    moduleTable,
    pb(),
  ];
}

// ─── PAGE 3: DEVICE LIFECYCLE ─────────────────────────────────────────────────
function makeLifecycleFlow() {
  // Swim-lane table: col 0 = lane label, cols 1-N = steps
  // We'll use 8 columns: label | step | → | step | → | step | → | outcome
  const labelW = 1600;
  const arrowW = 400;
  const remaining = CONTENT_W - labelW - arrowW * 3;
  const stepW = Math.floor(remaining / 4);
  const lastW = CONTENT_W - labelW - arrowW * 3 - stepW * 3;
  const colWidths = [labelW, stepW, arrowW, stepW, arrowW, stepW, arrowW, lastW];

  function laneHeader(text, fill) {
    return new TableCell({
      shading: shade(fill),
      borders: borders(fill),
      margins: { top: 100, bottom: 100, left: 120, right: 120 },
      width: { size: labelW, type: WidthType.DXA },
      verticalAlign: VerticalAlign.CENTER,
      children: [new Paragraph({ alignment: AlignmentType.CENTER,
        children: [new TextRun({ text, color: C.white, bold: true, size: 17, font: "Arial" })] })],
    });
  }

  function stepCell(text, fill, width, textColor = C.black) {
    return new TableCell({
      shading: shade(fill),
      borders: borders(C.border),
      margins: { top: 80, bottom: 80, left: 100, right: 100 },
      width: { size: width, type: WidthType.DXA },
      verticalAlign: VerticalAlign.CENTER,
      children: [new Paragraph({ alignment: AlignmentType.CENTER,
        children: [new TextRun({ text, color: textColor, bold: false, size: 17, font: "Arial" })] })],
    });
  }

  function arrowCellW(width = arrowW, fill = C.white) {
    return new TableCell({
      shading: shade(fill),
      borders: { top: { style: BorderStyle.NONE, size: 0, color: C.white }, bottom: { style: BorderStyle.NONE, size: 0, color: C.white }, left: { style: BorderStyle.NONE, size: 0, color: C.white }, right: { style: BorderStyle.NONE, size: 0, color: C.white } },
      margins: { top: 60, bottom: 60, left: 40, right: 40 },
      width: { size: width, type: WidthType.DXA },
      verticalAlign: VerticalAlign.CENTER,
      children: [new Paragraph({ alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "→", color: C.grey, bold: true, size: 22, font: "Arial" })] })],
    });
  }

  const tableTitle = new TableRow({
    children: [new TableCell({
      columnSpan: 8,
      shading: shade(C.navy),
      borders: borders(C.navy),
      margins: { top: 120, bottom: 120, left: 160, right: 160 },
      children: [new Paragraph({ alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "FLOW 1 — DEVICE LIFECYCLE (PURCHASE TO SALE)", color: C.white, bold: true, size: 24, font: "Arial" })] })],
    })],
  });

  const swimTable = new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: colWidths,
    rows: [
      tableTitle,
      // Lane 1: Purchase
      new TableRow({ children: [
        laneHeader("PURCHASE\nTEAM", C.navy),
        stepCell("GRN Creation", C.lightBlue, stepW),
        arrowCellW(arrowW, C.lightBlue),
        stepCell("Lot Registration", C.lightBlue, stepW),
        arrowCellW(arrowW, C.lightBlue),
        stepCell("Line Items Entry", C.lightBlue, stepW),
        arrowCellW(arrowW, C.lightBlue),
        stepCell("Advance to IQC", C.lightBlue, lastW),
      ] }),
      // Lane 2: IQC
      new TableRow({ children: [
        laneHeader("IQC\nINSPECTOR", C.green),
        stepCell("Device Scan", C.lightGreen, stepW),
        arrowCellW(arrowW, C.lightGreen),
        stepCell("IQC Form (60+ fields)", C.lightGreen, stepW),
        arrowCellW(arrowW, C.lightGreen),
        stepCell("Grade Assignment", C.lightGreen, stepW),
        arrowCellW(arrowW, C.lightGreen),
        stepCell("C0→Stock\nC3/C4→L1 Repair\nC5→Scrap", C.lightGreen, lastW),
      ] }),
      // Lane 3: Repair
      new TableRow({ children: [
        laneHeader("REPAIR\nENGINEERS", C.orange),
        stepCell("L1 Repair", C.lightOrange, stepW),
        arrowCellW(arrowW, C.lightOrange),
        stepCell("L2 Repair\n(if escalated)", C.lightOrange, stepW),
        arrowCellW(arrowW, C.lightOrange),
        stepCell("L3 Repair\n(if escalated)", C.lightOrange, stepW),
        arrowCellW(arrowW, C.lightOrange),
        stepCell("Pass→QC\nEscalate→Next Level\nScrap / Parts-only", C.lightOrange, lastW),
      ] }),
      // Lane 4: QC
      new TableRow({ children: [
        laneHeader("QC\nINSPECTOR", C.purple),
        stepCell("QC Score\n(battery/screen/\nkeyboard/body 0-10)", C.lightPurple, stepW),
        arrowCellW(arrowW, C.lightPurple),
        stepCell("Grade\n(A / B / C / D)", C.lightPurple, stepW),
        arrowCellW(arrowW, C.lightPurple),
        stepCell("Outcome Decision", C.lightPurple, stepW),
        arrowCellW(arrowW, C.lightPurple),
        stepCell("Pass→Ready to Sale\nFail→Back to L1\nCosmetic→Cleaning", C.lightPurple, lastW),
      ] }),
      // Lane 5: Cosmetic
      new TableRow({ children: [
        laneHeader("COSMETIC\nTEAM", C.pink),
        stepCell("Cleaning &\nDry Sanding", C.lightPink, stepW),
        arrowCellW(arrowW, C.lightPink),
        stepCell("Masking &\nPainting", C.lightPink, stepW),
        arrowCellW(arrowW, C.lightPink),
        stepCell("Water Sanding\n& Final QC", C.lightPink, stepW),
        arrowCellW(arrowW, C.lightPink),
        stepCell("Ready to Sale", C.lightPink, lastW),
      ] }),
      // Lane 6: Sales
      new TableRow({ children: [
        laneHeader("SALES\nTEAM", C.teal),
        stepCell("Device in\nReady-to-Sale", C.lightTeal, stepW),
        arrowCellW(arrowW, C.lightTeal),
        stepCell("Sale Record\n(price/customer/\npayment)", C.lightTeal, stepW),
        arrowCellW(arrowW, C.lightTeal),
        stepCell("Invoice\nGenerated", C.lightTeal, stepW),
        arrowCellW(arrowW, C.lightTeal),
        stepCell("SOLD\n─────\nReturn→Re-IQC\nor Scrap", C.lightTeal, lastW),
      ] }),
    ],
  });

  return [
    ...pageTitle("Flow 1 — Device Lifecycle (Purchase to Sale)", "Primary process: from lot purchase through grading, repair, QC, and sale"),
    swimTable,
    pb(),
  ];
}

// ─── PAGE 4: DEALER & FINANCE FLOW ───────────────────────────────────────────
function makeDealerFlow() {
  const col1W = Math.floor(CONTENT_W * 0.35);
  const col2W = CONTENT_W - col1W;
  const colWidths = [col1W, col2W];

  function sRow(text, fill, textColor = C.white) {
    return new TableRow({ children: [
      new TableCell({ columnSpan: 2, shading: shade(fill), borders: borders(fill),
        margins: { top: 100, bottom: 100, left: 140, right: 140 },
        children: [new Paragraph({ children: [new TextRun({ text, color: textColor, bold: true, size: 20, font: "Arial" })] })] }),
    ] });
  }

  function dRow(step, detail, stepFill = C.lightBlue) {
    return new TableRow({ children: [
      new TableCell({ shading: shade(stepFill), borders: borders(C.border),
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        width: { size: col1W, type: WidthType.DXA },
        verticalAlign: VerticalAlign.CENTER,
        children: [new Paragraph({ children: [new TextRun({ text: step, color: C.black, bold: true, size: 18, font: "Arial" })] })] }),
      new TableCell({ shading: shade(C.white), borders: borders(C.border),
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        width: { size: col2W, type: WidthType.DXA },
        verticalAlign: VerticalAlign.CENTER,
        children: [new Paragraph({ children: [new TextRun({ text: detail, color: C.black, size: 18, font: "Arial" })] })] }),
    ] });
  }

  function hRow(s, d) {
    return new TableRow({ children: [
      new TableCell({ shading: shade(C.lightBlue), borders: borders(C.border), margins: { top: 80, bottom: 80, left: 120, right: 120 }, width: { size: col1W, type: WidthType.DXA },
        children: [new Paragraph({ children: [new TextRun({ text: s, color: C.navy, bold: true, size: 18, font: "Arial" })] })] }),
      new TableCell({ shading: shade(C.white), borders: borders(C.border), margins: { top: 80, bottom: 80, left: 120, right: 120 }, width: { size: col2W, type: WidthType.DXA },
        children: [new Paragraph({ children: [new TextRun({ text: d, color: C.black, size: 18, font: "Arial" })] })] }),
    ] });
  }

  const t = new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: colWidths,
    rows: [
      // Title
      new TableRow({ children: [new TableCell({ columnSpan: 2, shading: shade(C.navy), borders: borders(C.navy),
        margins: { top: 120, bottom: 120, left: 160, right: 160 },
        children: [new Paragraph({ alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "FLOW 2 — DEALER MANAGEMENT & FINANCIAL RECONCILIATION", color: C.white, bold: true, size: 24, font: "Arial" })] })] }) ] }),
      // Column headers
      new TableRow({ children: [
        new TableCell({ shading: shade(C.navy), borders: borders(C.navy), margins: { top: 80, bottom: 80, left: 120, right: 120 }, width: { size: col1W, type: WidthType.DXA },
          children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "STEP", color: C.white, bold: true, size: 18, font: "Arial" })] })] }),
        new TableCell({ shading: shade(C.navy), borders: borders(C.navy), margins: { top: 80, bottom: 80, left: 120, right: 120 }, width: { size: col2W, type: WidthType.DXA },
          children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "DETAIL", color: C.white, bold: true, size: 18, font: "Arial" })] })] }),
      ] }),
      // DEALER MASTER section
      sRow("1. DEALER MASTER", C.navy),
      dRow("Register Dealer", "Name / GSTIN / Credit Limit / Contact / Bank Details"),
      dRow("Dealer Profile Created", "Available for Orders, Payments & Credit Notes"),
      // DEALER ORDERS
      sRow("2. DEALER ORDERS", C.teal),
      dRow("Create Order", "Select Dealer → Add Line Items (devices / spare parts)"),
      dRow("Confirm Order", "Status: PENDING → CONFIRMED"),
      dRow("Deliver", "Status: CONFIRMED → DELIVERED → dispatch record created"),
      dRow("Invoice Print (GST)", "GET /dealers/{id}/orders/{oid}/invoice — Tax invoice with GSTIN"),
      // PAYMENTS
      sRow("3. PAYMENTS & RECONCILIATION", C.green),
      dRow("Customer Payment Received", "Record receipt → Link to Dealer Order"),
      dRow("Auto-decrement due_amount", "due_amount = total_amount - sum(payments)"),
      dRow("Status → PAID", "Triggered when due_amount reaches 0"),
      dRow("Credit Note Applied", "Credit note → Decrement due_amount on open order"),
      // AGEING
      sRow("4. AGEING ANALYSIS", C.orange),
      dRow("Dealer Outstanding Balance", "Real-time balance across all open orders"),
      dRow("Ageing Buckets", "Current | 1-30 days | 31-60 days | 61-90 days | 90+ days"),
      dRow("Ageing Report", "Full receivables report → CSV Export available"),
    ],
  });

  return [
    ...pageTitle("Flow 2 — Dealer Management & Financial Reconciliation", "Dealer registration, orders, GST invoicing, payment reconciliation, and ageing"),
    t,
    pb(),
  ];
}

// ─── PAGE 5: CRM FLOW ─────────────────────────────────────────────────────────
function makeCRMFlow() {
  const col1W = Math.floor(CONTENT_W * 0.36);
  const col2W = Math.floor(CONTENT_W * 0.24);
  const col3W = CONTENT_W - col1W - col2W;
  const colWidths = [col1W, col2W, col3W];

  function crmCell(lines, fill, textColor = C.black, bold = false) {
    return new TableCell({
      shading: shade(fill),
      borders: borders(C.border),
      margins: { top: 80, bottom: 80, left: 120, right: 120 },
      verticalAlign: VerticalAlign.TOP,
      children: lines.map(l => new Paragraph({
        spacing: { after: 60 },
        children: [new TextRun({ text: l, color: textColor, bold, size: 17, font: "Arial" })],
      })),
    });
  }

  const t = new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: colWidths,
    rows: [
      // Title
      new TableRow({ children: [new TableCell({ columnSpan: 3, shading: shade(C.navy), borders: borders(C.navy),
        margins: { top: 120, bottom: 120, left: 160, right: 160 },
        children: [new Paragraph({ alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "FLOW 3 — CRM: SOURCING & SALES PIPELINE", color: C.white, bold: true, size: 24, font: "Arial" })] })] }) ] }),
      // Column headers
      new TableRow({ children: [
        new TableCell({ shading: shade(C.orange), borders: borders(C.orange), margins: { top: 100, bottom: 100, left: 120, right: 120 }, width: { size: col1W, type: WidthType.DXA },
          children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "SOURCING (Supplier)", color: C.white, bold: true, size: 20, font: "Arial" })] })] }),
        new TableCell({ shading: shade(C.grey), borders: borders(C.grey), margins: { top: 100, bottom: 100, left: 120, right: 120 }, width: { size: col2W, type: WidthType.DXA },
          children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "ACTIVITIES LOG", color: C.white, bold: true, size: 20, font: "Arial" })] })] }),
        new TableCell({ shading: shade(C.teal), borders: borders(C.teal), margins: { top: 100, bottom: 100, left: 120, right: 120 }, width: { size: col3W, type: WidthType.DXA },
          children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "SALES (Buyer)", color: C.white, bold: true, size: 20, font: "Arial" })] })] }),
      ] }),
      // Row 1: Entry points
      new TableRow({ children: [
        crmCell(["Contact (Supplier) →", "Create Sourcing Deal"], "FFF8E1"),
        crmCell(["Every interaction logged:", "Call / WhatsApp / Visit", "Email / Meeting"], C.lightGrey),
        crmCell(["Contact (Buyer) →", "Create Sales Opportunity"], "E0F7FA"),
      ] }),
      // Row 2: Stages
      new TableRow({ children: [
        crmCell([
          "PIPELINE STAGES:",
          "1. lead",
          "2. contacted",
          "3. inspection",
          "4. quoted",
          "5. negotiation",
          "6. agreed",
          "7. po_raised",
          "8. received",
          "9. WON / LOST",
        ], "FFF3E0"),
        crmCell([
          "next_followup assigned",
          "",
          "Linked to:",
          "- Contact record",
          "- Deal / Opportunity",
          "",
          "Reminders &",
          "overdue alerts",
        ], C.lightGrey),
        crmCell([
          "PIPELINE STAGES:",
          "1. lead",
          "2. contacted",
          "3. requirement",
          "4. availability",
          "5. quoted",
          "6. negotiation",
          "7. confirmed",
          "8. invoiced",
          "9. delivered",
          "10. payment",
          "11. WON / LOST",
        ], C.lightTeal),
      ] }),
      // Row 3: WON outcomes
      new TableRow({ children: [
        crmCell([
          "On WON:",
          "Create Lot →",
          "deal.linked_lot_id = lot.id",
          "",
          "Pricing Calculator:",
          "buying_price + margin",
          "→ ACCEPT",
          "→ RENEGOTIATE",
          "→ DECLINE",
        ], "FFE0B2"),
        crmCell([
          "Activity Types:",
          "- call",
          "- whatsapp",
          "- visit",
          "- email",
          "- meeting",
        ], C.lightGrey),
        crmCell([
          "On WON:",
          "Link to Sale record",
          "opp.linked_sale_ids[]",
          "",
          "Quote Lifecycle:",
          "Draft → Sent →",
          "Negotiating →",
          "Accepted / Rejected /",
          "Expired",
        ], "B2EBF2"),
      ] }),
    ],
  });

  return [
    ...pageTitle("Flow 3 — CRM: Sourcing & Sales Pipeline", "Supplier sourcing deals, buyer opportunities, activity logging, and quote management"),
    t,
    pb(),
  ];
}

// ─── PAGE 6: SYSTEM ARCHITECTURE ─────────────────────────────────────────────
function makeArchFlow() {
  const labelW = 2000;
  const compW = Math.floor((CONTENT_W - labelW) / 3);
  const lastW = CONTENT_W - labelW - compW * 2;
  const colWidths = [labelW, compW, compW, lastW];

  function archLayerHeader(label, fill) {
    return new TableCell({
      shading: shade(fill),
      borders: borders(fill),
      margins: { top: 100, bottom: 100, left: 120, right: 120 },
      width: { size: labelW, type: WidthType.DXA },
      verticalAlign: VerticalAlign.CENTER,
      children: [new Paragraph({ alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: label, color: C.white, bold: true, size: 18, font: "Arial" })] })],
    });
  }

  function archCell(text, fill, width, textColor = C.white) {
    return new TableCell({
      shading: shade(fill),
      borders: borders(C.border),
      margins: { top: 100, bottom: 100, left: 120, right: 120 },
      width: { size: width, type: WidthType.DXA },
      verticalAlign: VerticalAlign.CENTER,
      children: [new Paragraph({ alignment: AlignmentType.CENTER,
        children: [new TextRun({ text, color: textColor, bold: false, size: 18, font: "Arial" })] })],
    });
  }

  function arrowRow(cols) {
    return new TableRow({ children: [
      new TableCell({ columnSpan: cols, shading: shade(C.white), borders: noBorders(),
        margins: { top: 20, bottom: 20, left: 120, right: 120 },
        children: [new Paragraph({ alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "↕  data flow  ↕", color: C.grey, size: 16, font: "Arial" })] })] }),
    ] });
  }

  // Slightly lighter fills for component cells
  const fills = {
    navy:   "1976D2",
    teal:   "00ACC1",
    purple: "7B1FA2",
    green:  "388E3C",
    orange: "F57C00",
    grey:   "607D8B",
  };

  const t = new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: colWidths,
    rows: [
      // Title
      new TableRow({ children: [new TableCell({ columnSpan: 4, shading: shade(C.navy), borders: borders(C.navy),
        margins: { top: 120, bottom: 120, left: 160, right: 160 },
        children: [new Paragraph({ alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "SYSTEM ARCHITECTURE & INTEGRATION MAP", color: C.white, bold: true, size: 24, font: "Arial" })] })] }) ] }),
      // Layer 1
      new TableRow({ children: [
        archLayerHeader("LAYER 1\nUSERS / CLIENTS", C.navy),
        archCell("Browser (LAN)\nWeb UI", fills.navy, compW),
        archCell("OxyQC EXE\n(M2M API Key Auth)", fills.navy, compW),
        archCell("WhatsApp Business\n(QR session)", fills.navy, lastW),
      ] }),
      arrowRow(4),
      // Layer 2
      new TableRow({ children: [
        archLayerHeader("LAYER 2\nAPPLICATION", C.teal),
        archCell("FastAPI\n(4 workers, port 8000)", fills.teal, compW),
        archCell("Uvicorn\n(ASGI Server)", fills.teal, compW),
        archCell("SlowAPI\n(Rate Limiter)", fills.teal, lastW),
      ] }),
      arrowRow(4),
      // Layer 3
      new TableRow({ children: [
        archLayerHeader("LAYER 3\nMIDDLEWARE", C.purple),
        archCell("JWT Auth\n(cookie-based)", fills.purple, compW),
        archCell("CSRF Protection\n(26 routers)", fills.purple, compW),
        archCell("RBAC\n(11 roles)", fills.purple, lastW),
      ] }),
      arrowRow(4),
      // Layer 4
      new TableRow({ children: [
        archLayerHeader("LAYER 4\nDATA", C.green),
        archCell("PostgreSQL 15\n(35+ tables)", fills.green, compW),
        archCell("asyncpg\n(async driver)", fills.green, compW),
        archCell("SQLAlchemy 2.0\n(ORM)", fills.green, lastW),
      ] }),
      arrowRow(4),
      // Layer 5
      new TableRow({ children: [
        archLayerHeader("LAYER 5\nINTEGRATIONS", C.orange),
        archCell("Node.js WA Service\n(port 3001)", fills.orange, compW),
        archCell("whatsapp-web.js\n(WA session mgmt)", fills.orange, compW),
        archCell("OxyQC API Key\n(device grading EXE)", fills.orange, lastW),
      ] }),
      arrowRow(4),
      // Layer 6
      new TableRow({ children: [
        archLayerHeader("LAYER 6\nINFRASTRUCTURE", C.grey),
        archCell("Windows PC / Mini PC\n(on-premise)", fills.grey, compW),
        archCell("config.ini\n(gitignored secrets)", fills.grey, compW),
        archCell("backups/ folder\n(pg_dump + scheduled)", fills.grey, lastW),
      ] }),
    ],
  });

  return [
    ...pageTitle("System Architecture & Integration Map", "6-layer technical stack: from client interfaces to on-premise infrastructure"),
    t,
    pb(),
  ];
}

// ─── PAGE 7: RBAC MATRIX ──────────────────────────────────────────────────────
function makeRBACMatrix() {
  const modules = ["Dashboard", "Lots/GRN", "IQC", "Repair", "QC", "Stock", "Sales", "Dealers", "Accounts", "CRM", "Reports", "Admin"];
  const roles = [
    { name: "admin",               perms: [1,1,1,1,1,1,1,1,1,1,1,1] },
    { name: "inventory_manager",   perms: [1,1,1,1,1,1,1,1,1,0,1,0] },
    { name: "iqc_inspector",       perms: [1,1,1,0,0,0,0,0,0,0,0,0] },
    { name: "l1_engineer",         perms: [1,0,0,1,0,0,0,0,0,0,0,0] },
    { name: "l2_engineer",         perms: [1,0,0,1,0,0,0,0,0,0,0,0] },
    { name: "l3_engineer",         perms: [1,0,0,1,0,0,0,0,0,0,0,0] },
    { name: "qc_inspector",        perms: [1,0,0,0,1,0,0,0,0,0,0,0] },
    { name: "sales",               perms: [1,0,0,0,0,1,1,1,0,1,1,0] },
    { name: "spare_parts_manager", perms: [1,0,0,1,0,1,0,0,0,0,0,0] },
    { name: "telecaller",          perms: [1,0,0,0,0,0,0,0,0,1,0,0] },
    { name: "crm_manager",         perms: [1,0,0,0,0,0,1,1,0,1,1,0] },
  ];

  const roleColW = 2000;
  const modColW = Math.floor((CONTENT_W - roleColW) / modules.length);
  const lastModW = CONTENT_W - roleColW - modColW * (modules.length - 1);
  const colWidths = [roleColW, ...modules.map((_, i) => i < modules.length - 1 ? modColW : lastModW)];

  function modHeader(text, width) {
    return new TableCell({
      shading: shade(C.navy),
      borders: borders(C.navy),
      margins: { top: 60, bottom: 60, left: 60, right: 60 },
      width: { size: width, type: WidthType.DXA },
      verticalAlign: VerticalAlign.CENTER,
      children: [new Paragraph({ alignment: AlignmentType.CENTER,
        children: [new TextRun({ text, color: C.white, bold: true, size: 15, font: "Arial" })] })],
    });
  }

  function permCell(has, width) {
    return new TableCell({
      shading: shade(has ? C.greenCheck : C.white),
      borders: borders(C.border),
      margins: { top: 60, bottom: 60, left: 40, right: 40 },
      width: { size: width, type: WidthType.DXA },
      verticalAlign: VerticalAlign.CENTER,
      children: [new Paragraph({ alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: has ? "✓" : "—", color: has ? C.green : C.grey, bold: has, size: 18, font: "Arial" })] })],
    });
  }

  const headerRow = new TableRow({ children: [
    new TableCell({ shading: shade(C.navy), borders: borders(C.navy), margins: { top: 60, bottom: 60, left: 120, right: 120 }, width: { size: roleColW, type: WidthType.DXA },
      children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "ROLE", color: C.white, bold: true, size: 18, font: "Arial" })] })] }),
    ...modules.map((m, i) => modHeader(m, i < modules.length - 1 ? modColW : lastModW)),
  ] });

  const dataRows = roles.map(r => new TableRow({ children: [
    new TableCell({ shading: shade(C.lightGrey), borders: borders(C.border), margins: { top: 60, bottom: 60, left: 120, right: 120 }, width: { size: roleColW, type: WidthType.DXA },
      children: [new Paragraph({ children: [new TextRun({ text: r.name, color: C.black, bold: false, size: 16, font: "Arial" })] })] }),
    ...r.perms.map((p, i) => permCell(p === 1, i < modules.length - 1 ? modColW : lastModW)),
  ] }));

  const t = new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: colWidths,
    rows: [
      new TableRow({ children: [new TableCell({ columnSpan: modules.length + 1, shading: shade(C.navy), borders: borders(C.navy),
        margins: { top: 120, bottom: 120, left: 160, right: 160 },
        children: [new Paragraph({ alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "ROLE-BASED ACCESS CONTROL MATRIX — 11 Roles × 12 Modules", color: C.white, bold: true, size: 24, font: "Arial" })] })] }) ] }),
      new TableRow({ children: [new TableCell({ columnSpan: modules.length + 1, shading: shade(C.lightGrey), borders: borders(C.border),
        margins: { top: 60, bottom: 60, left: 140, right: 140 },
        children: [new Paragraph({ children: [new TextRun({ text: "✓ = Access Granted (green cell)   |   — = No Access   |   All calculations enforced server-side via RBAC middleware", color: C.grey, size: 16, font: "Arial" })] })] }) ] }),
      headerRow,
      ...dataRows,
    ],
  });

  return [
    ...pageTitle("Role-Based Access Control Matrix", "11 roles x 12 modules — access permissions enforced at API and middleware level"),
    t,
  ];
}

// ─── ASSEMBLE DOCUMENT ────────────────────────────────────────────────────────
const doc = new Document({
  styles: {
    default: {
      document: { run: { font: "Arial", size: 20, color: C.black } },
    },
  },
  sections: [{
    properties: {
      page: {
        size: {
          width: 16838,
          height: 11906,
          orientation: PageOrientation.LANDSCAPE,
        },
        margin: { top: 720, bottom: 720, left: 720, right: 720 },
      },
    },
    children: [
      ...makeCover(),
      ...makeModuleOverview(),
      ...makeLifecycleFlow(),
      ...makeDealerFlow(),
      ...makeCRMFlow(),
      ...makeArchFlow(),
      ...makeRBACMatrix(),
    ],
  }],
});

// ─── WRITE FILE ───────────────────────────────────────────────────────────────
Packer.toBuffer(doc).then(buffer => {
  const outPath = "OxyPC_AppFlow.docx";
  fs.writeFileSync(outPath, buffer);
  const stats = fs.statSync(outPath);
  console.log("Success! File written:", outPath);
  console.log("File size:", (stats.size / 1024).toFixed(1), "KB");
}).catch(err => {
  console.error("Error generating document:", err);
  process.exit(1);
});
