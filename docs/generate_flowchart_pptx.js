"use strict";
// OxyPC Inventory ERP — Professional Flowchart PPTX
// Generator: PptxGenJS 4.x
// Run: node generate_flowchart_pptx.js

const pptxgen = require("pptxgenjs");
const fs = require("fs");

const OUTPUT = String.raw`C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory\docs\OxyPC_Flowchart.pptx`;

// ── Palette (no # prefix) ──────────────────────────────────────────────────
const C = {
  navy:    "1565C0",   // Start/End, borders
  navyDk: "0D3B7A",   // darker navy for accents
  white:   "FFFFFF",
  orange:  "E65100",   // Decision diamonds
  amber:   "F57F17",   // Repair
  green:   "2E7D32",   // QC
  purple:  "6A1B9A",   // Cosmetic
  teal:    "00695C",   // Sales
  red:     "C62828",   // Scrap
  grey:    "546E7A",   // neutral/lost
  lightBg: "EEF4FC",   // slide bg tint
  black:   "212121",
};

// ── Helper: fresh shadow ───────────────────────────────────────────────────
const mkShadow = () => ({ type: "outer", blur: 4, offset: 2, angle: 135, color: "000000", opacity: 0.18 });

// ── Flowchart helpers ──────────────────────────────────────────────────────
function box(slide, x, y, w, h, text, fillColor, textColor = "FFFFFF", fontSize = 9, bold = true) {
  slide.addShape("roundRect", {
    x, y, w, h,
    fill: { color: fillColor },
    line: { color: fillColor === "FFFFFF" ? C.navy : fillColor, width: 1.5 },
    rectRadius: 0.08,
    shadow: mkShadow(),
  });
  slide.addText(text, {
    x, y, w, h,
    align: "center", valign: "middle",
    fontSize, bold,
    color: textColor,
    wrap: true,
    margin: 3,
  });
}

function processBox(slide, x, y, w, h, text, fontSize = 9) {
  // White fill, navy border, navy text
  slide.addShape("roundRect", {
    x, y, w, h,
    fill: { color: "FFFFFF" },
    line: { color: C.navy, width: 1.5 },
    rectRadius: 0.08,
    shadow: mkShadow(),
  });
  slide.addText(text, {
    x, y, w, h,
    align: "center", valign: "middle",
    fontSize, bold: true,
    color: C.navy,
    wrap: true,
    margin: 3,
  });
}

function oval(slide, x, y, w, h, text, fillColor = C.navy, textColor = "FFFFFF", fontSize = 9) {
  slide.addShape("ellipse", {
    x, y, w, h,
    fill: { color: fillColor },
    line: { color: fillColor, width: 1 },
    shadow: mkShadow(),
  });
  slide.addText(text, {
    x, y, w, h,
    align: "center", valign: "middle",
    fontSize, bold: true,
    color: textColor,
    wrap: true,
    margin: 2,
  });
}

function diamond(slide, x, y, w, h, text, fillColor = C.orange, fontSize = 8) {
  slide.addShape("diamond", {
    x, y, w, h,
    fill: { color: fillColor },
    line: { color: fillColor, width: 1.5 },
    shadow: mkShadow(),
  });
  slide.addText(text, {
    x, y, w, h,
    align: "center", valign: "middle",
    fontSize, bold: true,
    color: "FFFFFF",
    wrap: true,
    margin: 2,
  });
}

function arrow(slide, x1, y1, x2, y2, color = C.navy) {
  slide.addShape("line", {
    x: x1, y: y1, w: x2 - x1, h: y2 - y1,
    line: { color, width: 1.2, endArrowType: "arrow" },
  });
}

function arrowV(slide, x, y1, y2, color = C.navy) {
  arrow(slide, x, y1, x, y2, color);
}

function arrowH(slide, x1, x2, y, color = C.navy) {
  arrow(slide, x1, y, x2, y, color);
}

function label(slide, x, y, w, h, text, color = C.grey, fontSize = 7.5) {
  slide.addText(text, {
    x, y, w, h,
    align: "center", valign: "middle",
    fontSize, bold: false,
    color,
    wrap: true,
    margin: 1,
  });
}

// ── Slide title banner ────────────────────────────────────────────────────
function slideTitle(slide, title, subtitle = "") {
  slide.addShape("rect", {
    x: 0, y: 0, w: 13.33, h: 0.48,
    fill: { color: C.navy },
    line: { color: C.navy, width: 0 },
  });
  slide.addText(title + (subtitle ? "  |  " + subtitle : ""), {
    x: 0.18, y: 0, w: 13.0, h: 0.48,
    align: "left", valign: "middle",
    fontSize: 14, bold: true, color: "FFFFFF",
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// MAIN
// ══════════════════════════════════════════════════════════════════════════════
const prs = new pptxgen();
prs.layout = "LAYOUT_WIDE"; // 13.3" × 7.5"
prs.title = "OxyPC Refurbishment ERP — Process Flowcharts";
prs.author = "OxyPC";

// ─────────────────────────────────────────────────────────────────────────────
// SLIDE 1 — Cover
// ─────────────────────────────────────────────────────────────────────────────
{
  const sl = prs.addSlide();
  sl.background = { color: C.navy };

  // Decorative accent stripe
  sl.addShape("rect", {
    x: 0, y: 4.9, w: 13.33, h: 0.06,
    fill: { color: C.orange },
    line: { color: C.orange, width: 0 },
  });

  // Logo placeholder circle
  sl.addShape("ellipse", {
    x: 5.9, y: 0.9, w: 1.53, h: 1.53,
    fill: { color: "FFFFFF", transparency: 85 },
    line: { color: "FFFFFF", width: 2 },
  });
  sl.addText("OPC", {
    x: 5.9, y: 0.9, w: 1.53, h: 1.53,
    align: "center", valign: "middle",
    fontSize: 22, bold: true, color: "FFFFFF",
  });

  sl.addText("OxyPC Refurbishment ERP", {
    x: 1, y: 2.7, w: 11.33, h: 1.0,
    align: "center", valign: "middle",
    fontSize: 40, bold: true, color: "FFFFFF",
    charSpacing: 1,
  });

  sl.addText("Complete Application Process Flowcharts", {
    x: 1, y: 3.75, w: 11.33, h: 0.55,
    align: "center", valign: "middle",
    fontSize: 18, bold: false, color: "CADCFC",
    italic: true,
  });

  sl.addText("27 April 2026", {
    x: 1, y: 4.4, w: 11.33, h: 0.38,
    align: "center", valign: "middle",
    fontSize: 13, bold: false, color: "CADCFC",
  });

  // Slide index legend strip
  const slides = [
    { n: "2", t: "Device Lifecycle" },
    { n: "3", t: "Dealer & Finance" },
    { n: "4", t: "CRM Pipelines" },
    { n: "5", t: "System Architecture" },
    { n: "6", t: "RBAC Matrix" },
  ];
  const bw = 2.0, startX = 1.17, sy = 5.5;
  slides.forEach((s, i) => {
    sl.addShape("roundRect", {
      x: startX + i * (bw + 0.26), y: sy, w: bw, h: 0.65,
      fill: { color: "FFFFFF", transparency: 82 },
      line: { color: "FFFFFF", width: 1 },
      rectRadius: 0.08,
    });
    sl.addText([
      { text: `Slide ${s.n}`, options: { bold: true, breakLine: true, fontSize: 10, color: "FFFFFF" } },
      { text: s.t, options: { bold: false, fontSize: 8, color: "CADCFC" } },
    ], { x: startX + i * (bw + 0.26), y: sy, w: bw, h: 0.65, align: "center", valign: "middle", margin: 2 });
  });

  sl.addText("Confidential — Internal Use Only", {
    x: 0, y: 7.2, w: 13.33, h: 0.3,
    align: "center", valign: "middle",
    fontSize: 8, color: "7BA7D4", italic: true,
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// SLIDE 2 — Device Lifecycle Main Flow
// ─────────────────────────────────────────────────────────────────────────────
{
  const sl = prs.addSlide();
  sl.background = { color: C.lightBg };
  slideTitle(sl, "Device Lifecycle — Main Flow", "GRN → IQC → Repair → QC → Sale");

  // ── COLUMN A: Intake flow (x center ~1.0) ─────────────────────────────────
  const ax = 0.12, aw = 2.0;
  const ac = ax + aw / 2; // center x for arrows
  let ay = 0.58;
  const rowH = 0.42, gap = 0.13;

  function nextY() { const y = ay; ay += rowH + gap; return y; }

  // START oval
  oval(sl, ax, nextY(), aw, rowH, "START: GRN / Material Received", C.navy, "FFFFFF", 8);
  arrowV(sl, ac, ay, ay + gap - 0.02); ay += gap;

  processBox(sl, ax, nextY(), aw, rowH, "Supplier Invoice & Lot Registration", 8);
  arrowV(sl, ac, ay, ay + gap - 0.02); ay += gap;

  processBox(sl, ax, nextY(), aw, rowH, "Device Barcoding & Line Items", 8);
  arrowV(sl, ac, ay, ay + gap - 0.02); ay += gap;

  processBox(sl, ax, nextY(), aw, rowH, "Advance to IQC", 8);
  arrowV(sl, ac, ay, ay + gap - 0.02); ay += gap;

  // IQC Diamond
  const iqcDY = nextY();
  diamond(sl, ax, iqcDY, aw, rowH + 0.1, "IQC Inspection\n(60+ checks)", C.orange, 7.5);
  ay += 0.1; // diamond is taller
  arrowV(sl, ac, ay, ay + gap - 0.02); ay += gap;

  // Grade C0 → Stock In (stays in col A, then goes to QC)
  const stockY = nextY();
  box(sl, ax, stockY, aw, rowH, "Move to Stock In\n(Grade C0 Pass)", C.green, "FFFFFF", 7.5);
  // label C0 Pass
  label(sl, ax - 0.05, stockY - 0.18, aw + 0.1, 0.22, "Grade C0 (Pass)→", C.green, 7);

  // Arrow from Stock In down to QC
  arrowV(sl, ac, stockY + rowH, stockY + rowH + gap - 0.02);

  // Grade C3/C4 branch arrow → col B (right)
  arrowH(sl, ax + aw, iqcDY + (rowH + 0.1) / 2, ax + aw + 0.15, C.amber);
  label(sl, ax + aw + 0.02, iqcDY + (rowH + 0.1) / 2 - 0.2, 0.8, 0.2, "C3/C4→", C.amber, 6.5);

  // Grade C5 Scrap branch arrow → far left down
  arrowH(sl, ax, iqcDY + (rowH + 0.1) / 2, ax - 0.5, C.red);
  const scrapIqcY = iqcDY + rowH;
  box(sl, ax - 0.72, iqcDY + (rowH + 0.1) / 2 - rowH / 2, 0.72, rowH, "SCRAP\n(C5)", C.red, "FFFFFF", 7);
  label(sl, ax - 0.72, iqcDY - 0.2, 0.72, 0.22, "C5 Scrap", C.red, 6.5);

  // QC box (in col A, below Stock In)
  const qcBoxY = stockY + rowH + gap;
  box(sl, ax, qcBoxY, aw, rowH, "QC Inspection\n(Battery/Screen/Kbd/Body)", C.green, "FFFFFF", 7.5);
  arrowV(sl, ac, qcBoxY + rowH, qcBoxY + rowH + gap - 0.02);

  // QC Decision
  const qcDecY = qcBoxY + rowH + gap;
  diamond(sl, ax, qcDecY, aw, rowH + 0.1, "QC Result?", C.orange, 8);

  // Pass → Ready to Sale (col A continues)
  arrowV(sl, ac, qcDecY + rowH + 0.1, qcDecY + rowH + 0.1 + gap - 0.02);
  const rtsY = qcDecY + rowH + 0.1 + gap;
  box(sl, ax, rtsY, aw, rowH, "Ready to Sale", C.teal, "FFFFFF", 8);
  label(sl, ax + aw + 0.02, qcDecY + (rowH + 0.1) * 0.4, 0.9, 0.2, "Pass (A/B/C/D)↓", C.teal, 6.5);

  arrowV(sl, ac, rtsY + rowH, rtsY + rowH + gap - 0.02);
  const saleY = rtsY + rowH + gap;
  box(sl, ax, saleY, aw, rowH, "Sale\n(Price / Customer / Payment)", C.teal, "FFFFFF", 7.5);
  arrowV(sl, ac, saleY + rowH, saleY + rowH + gap - 0.02);

  const retDecY = saleY + rowH + gap;
  diamond(sl, ax, retDecY, aw, rowH + 0.1, "Return?", C.orange, 8);
  arrowV(sl, ac, retDecY + rowH + 0.1, retDecY + rowH + 0.1 + gap - 0.02);
  oval(sl, ax, retDecY + rowH + 0.1 + gap, aw, rowH, "SOLD ✓ — End", C.navy, "FFFFFF", 8);
  label(sl, ax + aw, retDecY + (rowH + 0.1) * 0.3, 0.5, 0.2, "No↓", C.navy, 7);

  // Return → back to IQC
  const retY = retDecY + (rowH + 0.1) / 2;
  arrowH(sl, ax + aw / 2 + 0.02, ax - 0.72, retY + 0.15, C.red);
  label(sl, ax - 0.72, retY - 0.05, 0.72, 0.25, "Yes→Return→IQC", C.red, 6);

  // Cosmetic fail arrow from QC decision → col C
  arrowH(sl, ax + aw, qcDecY + (rowH + 0.1) / 2, ax + aw + 2.5, C.purple);
  label(sl, ax + aw + 0.04, qcDecY - 0.18, 1.2, 0.2, "Cosmetic Fail→", C.purple, 6.5);

  // Functional fail → back to L1
  arrowH(sl, ax + aw / 2, ax + aw / 2 + 0.0, qcDecY + rowH + 0.1, C.amber);

  // ── COLUMN B: Repair Escalation (x ~2.35) ─────────────────────────────────
  const bx = 2.35, bw2 = 2.05;
  const bc = bx + bw2 / 2;
  let by = iqcDY; // align start with IQC row

  // L1 Repair
  const l1Y = by;
  box(sl, bx, l1Y, bw2, rowH, "L1 Repair (Basic)", C.amber, "FFFFFF", 8);
  arrowV(sl, bc, l1Y + rowH, l1Y + rowH + gap - 0.02);

  const l1DecY = l1Y + rowH + gap;
  diamond(sl, bx, l1DecY, bw2, rowH + 0.08, "L1 Outcome?", C.orange, 7.5);

  // Pass → QC (arrow left back to col A QC)
  arrowH(sl, bx, ax + aw, qcBoxY + rowH / 2, C.green);
  label(sl, bx + 0.02, l1DecY - 0.2, bw2 - 0.04, 0.22, "Pass→QC", C.green, 6.5);

  // Scrap branch
  box(sl, bx + bw2 + 0.08, l1DecY, 0.7, rowH, "SCRAP", C.red, "FFFFFF", 7);
  arrowH(sl, bx + bw2, bx + bw2 + 0.08, l1DecY + rowH / 2, C.red);
  label(sl, bx + bw2 + 0.01, l1DecY - 0.18, 0.8, 0.2, "Scrap→", C.red, 6.5);

  // Escalate → L2
  arrowV(sl, bc, l1DecY + rowH + 0.08, l1DecY + rowH + 0.08 + gap - 0.02);
  const l2Y = l1DecY + rowH + 0.08 + gap;
  box(sl, bx, l2Y, bw2, rowH, "L2 Repair (Intermediate)", C.amber, "FFFFFF", 8);
  label(sl, bx - 0.05, l1DecY + (rowH + 0.08) * 0.5, 0.5, 0.2, "Escalate↓", C.amber, 6.5);
  arrowV(sl, bc, l2Y + rowH, l2Y + rowH + gap - 0.02);

  const l2DecY = l2Y + rowH + gap;
  diamond(sl, bx, l2DecY, bw2, rowH + 0.08, "L2 Outcome?", C.orange, 7.5);

  // Pass → QC
  arrowH(sl, bx, ax + aw, qcBoxY + rowH / 2 + 0.04, C.green);
  label(sl, bx + 0.02, l2DecY - 0.2, bw2 - 0.04, 0.22, "Pass→QC", C.green, 6.5);

  // Scrap
  box(sl, bx + bw2 + 0.08, l2DecY, 0.7, rowH, "SCRAP", C.red, "FFFFFF", 7);
  arrowH(sl, bx + bw2, bx + bw2 + 0.08, l2DecY + rowH / 2, C.red);

  // Escalate → L3
  arrowV(sl, bc, l2DecY + rowH + 0.08, l2DecY + rowH + 0.08 + gap - 0.02);
  const l3Y = l2DecY + rowH + 0.08 + gap;
  box(sl, bx, l3Y, bw2, rowH, "L3 Repair (Advanced)", C.amber, "FFFFFF", 8);
  arrowV(sl, bc, l3Y + rowH, l3Y + rowH + gap - 0.02);

  const l3DecY = l3Y + rowH + gap;
  diamond(sl, bx, l3DecY, bw2, rowH + 0.08, "L3 Outcome?", C.orange, 7.5);

  // Pass → QC
  arrowH(sl, bx, ax + aw, qcBoxY + rowH / 2 + 0.08, C.green);
  label(sl, bx + 0.02, l3DecY - 0.2, bw2 - 0.04, 0.22, "Pass→QC", C.green, 6.5);

  // Scrap
  box(sl, bx + bw2 + 0.08, l3DecY, 0.7, rowH, "SCRAP", C.red, "FFFFFF", 7);
  arrowH(sl, bx + bw2, bx + bw2 + 0.08, l3DecY + rowH / 2, C.red);

  // ── COLUMN C: Cosmetic Pipeline (x ~5.0) ─────────────────────────────────
  const cx = 5.0, cw = 1.75;
  const cosY = qcDecY - 0.1;
  let cty = cosY;
  const cosSteps = ["Cleaning", "Dry Sanding", "Masking", "Painting", "Water Sanding", "Final QC"];
  const cc = cx + cw / 2;

  sl.addText("Cosmetic Pipeline", {
    x: cx, y: cty - 0.22, w: cw, h: 0.22,
    align: "center", fontSize: 7, bold: true, color: C.purple,
  });

  cosSteps.forEach((step, i) => {
    const color = step === "Final QC" ? C.green : C.purple;
    box(sl, cx, cty, cw, rowH, step, color, "FFFFFF", 7.5);
    if (i < cosSteps.length - 1) {
      arrowV(sl, cc, cty + rowH, cty + rowH + gap - 0.02);
    }
    cty += rowH + gap;
  });

  // Final QC diamond
  const fqcDecY = cty;
  diamond(sl, cx, fqcDecY, cw, rowH + 0.08, "Final QC?", C.orange, 7.5);

  // Pass → Ready to Sale (arrow left)
  arrowH(sl, cx, ax + aw, rtsY + rowH / 2, C.teal);
  label(sl, cx + 0.02, fqcDecY - 0.2, cw - 0.04, 0.2, "Pass→Ready to Sale", C.teal, 6.5);

  // Fail → back to Cleaning (arrow up the column)
  arrowH(sl, cx + cw / 2, cx + cw + 0.12, fqcDecY + (rowH + 0.08) / 2, C.red);
  sl.addShape("line", {
    x: cx + cw + 0.12, y: cosY + rowH / 2,
    w: 0, h: fqcDecY + (rowH + 0.08) / 2 - (cosY + rowH / 2),
    line: { color: C.red, width: 1.2, endArrowType: "none", beginArrowType: "none" },
  });
  arrowH(sl, cx + cw + 0.12, cx + cw / 2 + 0.04, cosY + rowH / 2, C.red);
  label(sl, cx + cw + 0.04, fqcDecY - 0.2, 0.5, 0.2, "Fail→", C.red, 6.5);

  // ── COLUMN D: Spare Parts Branch (x ~7.0) ────────────────────────────────
  const dx = 7.1, dw = 2.0;
  const dc = dx + dw / 2;
  let dy = 0.58;

  sl.addText("SPARE PARTS BRANCH", {
    x: dx, y: dy - 0.01, w: dw, h: 0.22,
    align: "center", fontSize: 7, bold: true, color: C.grey,
    italic: true,
  });
  dy += 0.22;

  diamond(sl, dx, dy, dw, rowH + 0.1, "Parts Not\nAvailable (PNA)?", C.orange, 7);
  dy += rowH + 0.1 + gap;

  box(sl, dx, dy, dw, rowH, "Spare Parts Planning", C.grey, "FFFFFF", 7.5);
  arrowV(sl, dc, dy + rowH, dy + rowH + gap - 0.02);
  dy += rowH + gap;

  box(sl, dx, dy, dw, rowH, "Check Inventory", C.grey, "FFFFFF", 7.5);
  arrowV(sl, dc, dy + rowH, dy + rowH + gap - 0.02);
  dy += rowH + gap;

  diamond(sl, dx, dy, dw, rowH + 0.1, "Part Available?", C.orange, 7.5);
  const pnaDecY = dy;
  dy += rowH + 0.1 + gap;

  // Yes branch → Assign Part
  box(sl, dx, dy, dw, rowH, "Assign Part to Engineer", C.green, "FFFFFF", 7.5);
  arrowV(sl, dc, pnaDecY + rowH + 0.1, dy, C.green);
  label(sl, dx + dw + 0.02, pnaDecY + 0.15, 0.4, 0.2, "Yes↓", C.green, 6.5);

  // No branch → PO
  const noX = dx + dw + 0.1;
  arrowH(sl, dx + dw, noX, pnaDecY + (rowH + 0.1) / 2, C.navy);
  label(sl, dx + dw + 0.02, pnaDecY - 0.2, 0.5, 0.2, "No→", C.navy, 6.5);
  box(sl, noX, pnaDecY, 1.95, rowH + 0.55, "Create PO →\nGRN →\nUpdate Inventory", C.navy, "FFFFFF", 7);
  arrowH(sl, noX + 0.975, dx + dw / 2, dy + rowH / 2, C.navy);

  // ── Legend (bottom right) ─────────────────────────────────────────────────
  const legends = [
    { color: C.navy,   label: "Start/End / Stock" },
    { color: C.amber,  label: "Repair Steps" },
    { color: C.green,  label: "QC / Pass" },
    { color: C.purple, label: "Cosmetic" },
    { color: C.teal,   label: "Sales" },
    { color: C.orange, label: "Decision" },
    { color: C.red,    label: "Scrap / Return" },
  ];
  let lx = 9.3, ly = 5.8;
  sl.addText("Legend:", {
    x: lx, y: ly - 0.22, w: 3.8, h: 0.22,
    fontSize: 8, bold: true, color: C.black,
  });
  legends.forEach((lg) => {
    sl.addShape("rect", { x: lx, y: ly, w: 0.22, h: 0.22, fill: { color: lg.color }, line: { color: lg.color, width: 0 } });
    sl.addText(lg.label, { x: lx + 0.28, y: ly, w: 1.7, h: 0.22, fontSize: 7, color: C.black, valign: "middle" });
    lx += 1.88;
    if (lx > 12.5) { lx = 9.3; ly += 0.28; }
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// SLIDE 3 — Dealer & Finance Flow
// ─────────────────────────────────────────────────────────────────────────────
{
  const sl = prs.addSlide();
  sl.background = { color: C.lightBg };
  slideTitle(sl, "Dealer & Finance Flow", "Order → Invoice → Payment → Reconciliation");

  // Main flow — left column
  const ax = 0.25, aw = 2.3;
  const ac = ax + aw / 2;
  let ay = 0.65;
  const rh = 0.4, g = 0.12;

  function nxt() { const y = ay; ay += rh + g; return y; }
  function nxtD() { const y = ay; ay += rh + 0.1 + g; return y; }

  oval(sl, ax, nxt(), aw, rh, "START: Register Dealer", C.navy, "FFFFFF", 8);
  arrowV(sl, ac, ay, ay + g - 0.02); ay += g;
  processBox(sl, ax, nxt(), aw, rh, "Set Credit Limit & GSTIN", 8);
  arrowV(sl, ac, ay, ay + g - 0.02); ay += g;
  processBox(sl, ax, nxt(), aw, rh, "Create Dealer Order", 8);
  arrowV(sl, ac, ay, ay + g - 0.02); ay += g;
  processBox(sl, ax, nxt(), aw, rh, "Add Line Items (Devices/Parts)", 8);
  arrowV(sl, ac, ay, ay + g - 0.02); ay += g;

  const confDecY = nxtD();
  diamond(sl, ax, confDecY, aw, rh + 0.1, "Order Confirmed?", C.orange, 8);

  // No → Edit/Cancel (right branch)
  arrowH(sl, ax + aw, ax + aw + 0.12, confDecY + (rh + 0.1) / 2, C.red);
  box(sl, ax + aw + 0.12, confDecY, 1.2, rh, "Edit / Cancel", C.red, "FFFFFF", 7.5);
  label(sl, ax + aw + 0.04, confDecY - 0.2, 0.6, 0.2, "No→", C.red, 6.5);

  // Yes → continues
  label(sl, ax - 0.04, confDecY + rh + 0.1 - 0.02, aw + 0.08, 0.2, "Yes↓", C.green, 6.5);
  arrowV(sl, ac, confDecY + rh + 0.1, confDecY + rh + 0.1 + g - 0.02); ay = confDecY + rh + 0.1 + g;

  processBox(sl, ax, nxt(), aw, rh, "Mark Delivered", 8);
  arrowV(sl, ac, ay, ay + g - 0.02); ay += g;
  box(sl, ax, nxt(), aw, rh, "Generate Invoice (GST auto-calc)", C.navy, "FFFFFF", 7.5);
  arrowV(sl, ac, ay, ay + g - 0.02); ay += g;
  processBox(sl, ax, nxt(), aw, rh, "Send Payment Reminder (WhatsApp)", 8);
  arrowV(sl, ac, ay, ay + g - 0.02); ay += g;
  processBox(sl, ax, nxt(), aw, rh, "Customer Receipt Entry", 8);
  arrowV(sl, ac, ay, ay + g - 0.02); ay += g;
  processBox(sl, ax, nxt(), aw, rh, "Link Receipt → Dealer Order", 8);
  arrowV(sl, ac, ay, ay + g - 0.02); ay += g;
  processBox(sl, ax, nxt(), aw, rh, "Auto-decrement Due Amount", 8);
  arrowV(sl, ac, ay, ay + g - 0.02); ay += g;

  const dueDecY = nxtD();
  diamond(sl, ax, dueDecY, aw, rh + 0.1, "Due Amount = 0?", C.orange, 8);

  // No → Ageing Report (right branch)
  arrowH(sl, ax + aw, ax + aw + 0.12, dueDecY + (rh + 0.1) / 2, C.red);
  box(sl, ax + aw + 0.12, dueDecY, 1.5, rh, "Ageing Report\n— Follow Up", C.red, "FFFFFF", 7.5);
  label(sl, ax + aw + 0.04, dueDecY - 0.2, 0.6, 0.2, "No→", C.red, 6.5);

  // Yes → PAID
  arrowV(sl, ac, dueDecY + rh + 0.1, dueDecY + rh + 0.1 + g - 0.02); ay = dueDecY + rh + 0.1 + g;
  label(sl, ax - 0.04, dueDecY + rh + 0.1 - 0.02, aw + 0.08, 0.2, "Yes↓", C.green, 6.5);
  box(sl, ax, nxt(), aw, rh, "Order Status = PAID ✓", C.green, "FFFFFF", 8);
  arrowV(sl, ac, ay, ay + g - 0.02); ay += g;

  const cnDecY = nxtD();
  diamond(sl, ax, cnDecY, aw, rh + 0.1, "Credit Note Exists?", C.orange, 8);

  // Yes → Apply Credit Note
  arrowH(sl, ax + aw, ax + aw + 0.12, cnDecY + (rh + 0.1) / 2, C.teal);
  box(sl, ax + aw + 0.12, cnDecY, 1.5, rh, "Apply Credit Note\n→ Reduce Due", C.teal, "FFFFFF", 7.5);
  label(sl, ax + aw + 0.04, cnDecY - 0.2, 0.5, 0.2, "Yes→", C.teal, 6.5);

  // No → END
  arrowV(sl, ac, cnDecY + rh + 0.1, cnDecY + rh + 0.1 + g - 0.02); ay = cnDecY + rh + 0.1 + g;
  label(sl, ax - 0.04, cnDecY + rh + 0.1 - 0.02, aw + 0.08, 0.2, "No↓", C.navy, 6.5);
  oval(sl, ax, ay, aw, rh, "END — Order Closed", C.navy, "FFFFFF", 8);

  // ── RIGHT SIDE: Ageing Table ───────────────────────────────────────────────
  const tx = 4.2, ty = 0.65, tw = 8.9;
  sl.addText("Receivables Ageing Buckets", {
    x: tx, y: ty, w: tw, h: 0.32,
    align: "center", fontSize: 11, bold: true, color: C.navy,
  });

  const ageHeaders = ["Bucket", "Current\n(0-30d)", "31-60d", "61-90d", "91-120d", "120+d\n(Bad Debt)"];
  const ageColors = ["1565C0", "2E7D32", "F57F17", "E65100", "C62828", "880E4F"];
  const ageRows = [
    ["Example A", "₹2,50,000", "₹80,000", "₹40,000", "₹15,000", "₹5,000"],
    ["Example B", "₹1,20,000", "₹30,000", "₹10,000", "₹0", "₹0"],
    ["Example C", "₹3,00,000", "₹1,50,000", "₹60,000", "₹25,000", "₹12,000"],
    ["TOTAL", "₹6,70,000", "₹2,60,000", "₹1,10,000", "₹40,000", "₹17,000"],
  ];

  const colW = [1.4, 1.3, 1.3, 1.3, 1.3, 1.3];
  const tableRows = [
    ageHeaders.map((h, i) => ({
      text: h,
      options: {
        fill: { color: ageColors[i] || "1565C0" },
        color: "FFFFFF",
        bold: true,
        fontSize: 9,
        align: "center",
        valign: "middle",
      },
    })),
    ...ageRows.map((row, ri) =>
      row.map((cell, ci) => ({
        text: cell,
        options: {
          fill: { color: ri === ageRows.length - 1 ? "E3F2FD" : (ri % 2 === 0 ? "FFFFFF" : "F5F9FF") },
          color: ri === ageRows.length - 1 ? C.navy : (ci === 0 ? C.navy : C.black),
          bold: ri === ageRows.length - 1 || ci === 0,
          fontSize: 8.5,
          align: ci === 0 ? "left" : "center",
          valign: "middle",
        },
      }))
    ),
  ];

  sl.addTable(tableRows, {
    x: tx, y: ty + 0.38, w: tw, h: 2.0,
    border: { pt: 0.5, color: "CADCFC" },
    colW,
  });

  // Explanation text boxes
  const explanations = [
    { x: tx, y: ty + 2.55, w: tw, h: 0.28, text: "Overdue follow-ups triggered automatically via WhatsApp at 31d, 61d, 91d milestones. Accounts >120d flagged as Bad Debt for write-off review." },
  ];
  explanations.forEach(e => {
    sl.addText(e.text, {
      x: e.x, y: e.y, w: e.w, h: e.h,
      fontSize: 8, color: C.grey, italic: true,
      align: "left", valign: "middle", wrap: true,
    });
  });

  // Finance KPI cards
  const kpis = [
    { label: "Avg Collection Days", value: "28d", color: C.green },
    { label: "Outstanding >60d", value: "₹1.5L", color: C.orange },
    { label: "Bad Debt Ratio", value: "0.6%", color: C.red },
    { label: "Active Dealers", value: "47", color: C.navy },
  ];
  kpis.forEach((k, i) => {
    const kx = tx + i * 2.24, ky = ty + 3.0, kw = 2.1, kh = 0.95;
    sl.addShape("roundRect", {
      x: kx, y: ky, w: kw, h: kh,
      fill: { color: k.color },
      line: { color: k.color, width: 0 },
      rectRadius: 0.1,
      shadow: mkShadow(),
    });
    sl.addText([
      { text: k.value, options: { bold: true, fontSize: 22, breakLine: true, color: "FFFFFF" } },
      { text: k.label, options: { bold: false, fontSize: 8, color: "FFFFFF" } },
    ], { x: kx, y: ky, w: kw, h: kh, align: "center", valign: "middle", margin: 4 });
  });

  // GSTIN process note
  sl.addShape("roundRect", {
    x: tx, y: ty + 4.1, w: tw, h: 0.75,
    fill: { color: "FFF8E1" },
    line: { color: C.amber, width: 1 },
    rectRadius: 0.08,
  });
  sl.addText([
    { text: "GST Compliance Notes: ", options: { bold: true, color: C.amber } },
    { text: "• Invoice auto-calculates IGST/CGST/SGST based on buyer state vs seller state  • GSTIN validated at dealer registration  • HSN codes linked to product master  • Monthly GSTR-1 export supported", options: { bold: false, color: C.black } },
  ], { x: tx + 0.1, y: ty + 4.1, w: tw - 0.2, h: 0.75, fontSize: 8, valign: "middle", wrap: true });
}

// ─────────────────────────────────────────────────────────────────────────────
// SLIDE 4 — CRM Flow: Sourcing & Sales Pipelines
// ─────────────────────────────────────────────────────────────────────────────
{
  const sl = prs.addSlide();
  sl.background = { color: C.lightBg };
  slideTitle(sl, "CRM Flow — Sourcing & Sales Pipelines", "Dual pipeline with activity tracking");

  const rh = 0.38, g = 0.1;

  // ── LEFT: Sourcing Pipeline ───────────────────────────────────────────────
  const Lx = 0.18, Lw = 2.8, Lc = Lx + Lw / 2;
  let Ly = 0.62;

  sl.addShape("rect", { x: Lx - 0.08, y: 0.54, w: Lw + 0.16, h: 6.75, fill: { color: "E8F4FD" }, line: { color: C.navy, width: 1 }, shadow: mkShadow() });
  sl.addText("SOURCING PIPELINE", { x: Lx, y: 0.56, w: Lw, h: 0.22, align: "center", fontSize: 9, bold: true, color: C.navy });

  oval(sl, Lx, Ly, Lw, rh, "New Supplier Contact", C.navy, "FFFFFF", 8);
  Ly += rh + g;
  arrowV(sl, Lc, Ly, Ly + g - 0.01); Ly += g;

  processBox(sl, Lx, Ly, Lw, rh, "Sourcing Deal Created", 8);
  Ly += rh + g;
  arrowV(sl, Lc, Ly, Ly + g - 0.01); Ly += g;

  const srcStages = ["lead", "contacted", "inspection", "quoted", "negotiation", "agreed", "po_raised", "received"];
  const srcColors = ["546E7A","1565C0","00695C","F57F17","E65100","2E7D32","6A1B9A","1565C0"];
  srcStages.forEach((stage, i) => {
    box(sl, Lx, Ly, Lw, rh, stage.toUpperCase(), srcColors[i], "FFFFFF", 7.5);
    Ly += rh;
    if (i < srcStages.length - 1) {
      arrowV(sl, Lc, Ly, Ly + g - 0.01);
      Ly += g;
    }
  });

  Ly += g;
  arrowV(sl, Lc, Ly, Ly + g - 0.01); Ly += g;
  diamond(sl, Lx, Ly, Lw, rh + 0.1, "Deal Outcome?", C.orange, 8);
  const srcDecY = Ly;
  Ly += rh + 0.1 + g;

  // WON
  arrowV(sl, Lc, srcDecY + rh + 0.1, Ly, C.green);
  label(sl, Lc - 0.5, srcDecY + rh + 0.05, 0.5, 0.18, "WON↓", C.green, 6.5);
  box(sl, Lx, Ly, Lw, rh, "Create Lot + Link to Deal", C.green, "FFFFFF", 7.5);

  // LOST branch
  const lostX = Lx + Lw + 0.1;
  arrowH(sl, Lx + Lw, lostX, srcDecY + (rh + 0.1) / 2, C.red);
  box(sl, lostX, srcDecY, 1.4, rh, "Log Reason\n+ Archive", C.grey, "FFFFFF", 7.5);
  label(sl, Lx + Lw + 0.02, srcDecY - 0.2, 0.6, 0.2, "LOST→", C.red, 6.5);

  // ── MIDDLE: Activity Log connector ───────────────────────────────────────
  const mx = 4.35;
  sl.addShape("rect", {
    x: mx - 0.08, y: 0.54, w: 2.55, h: 6.75,
    fill: { color: "FFF3E0" },
    line: { color: C.amber, width: 1 },
    shadow: mkShadow(),
  });
  sl.addText("ACTIVITY LOG\n(Every Stage)", {
    x: mx, y: 0.58, w: 2.4, h: 0.38,
    align: "center", fontSize: 9, bold: true, color: C.amber,
  });

  const activities = ["Log Call / WhatsApp", "Log Site Visit", "Log Email", "Set Next Follow-up", "Attach Documents", "Update Stage", "Record Deal Value", "Track Conversion"];
  activities.forEach((act, i) => {
    const ay2 = 1.06 + i * 0.74;
    sl.addShape("roundRect", {
      x: mx, y: ay2, w: 2.4, h: 0.58,
      fill: { color: "FFFFFF" },
      line: { color: C.amber, width: 1 },
      rectRadius: 0.06,
      shadow: mkShadow(),
    });
    sl.addText(act, { x: mx, y: ay2, w: 2.4, h: 0.58, align: "center", valign: "middle", fontSize: 8, color: C.black });
    if (i < activities.length - 1) {
      arrowV(sl, mx + 1.2, ay2 + 0.58, ay2 + 0.74, C.amber);
    }
  });

  // Arrows from both pipelines to activity log
  arrowH(sl, Lx + Lw, mx - 0.08, 2.0, C.amber);
  arrowH(sl, mx + 2.55 - 0.08, mx + 2.55 + 0.15, 2.0, C.amber);
  sl.addText("→ Every stage", { x: Lx + Lw, y: 1.88, w: mx - 0.08 - Lx - Lw, h: 0.2, fontSize: 6.5, color: C.amber, align: "center" });

  // ── RIGHT: Sales Pipeline ─────────────────────────────────────────────────
  const Rx = 7.2, Rw = 2.9, Rc = Rx + Rw / 2;
  let Ry = 0.62;

  sl.addShape("rect", { x: Rx - 0.08, y: 0.54, w: Rw + 0.16, h: 6.75, fill: { color: "E8F5E9" }, line: { color: C.green, width: 1 }, shadow: mkShadow() });
  sl.addText("SALES PIPELINE", { x: Rx, y: 0.56, w: Rw, h: 0.22, align: "center", fontSize: 9, bold: true, color: C.green });

  oval(sl, Rx, Ry, Rw, rh, "New Buyer Contact", C.green, "FFFFFF", 8);
  Ry += rh + g;
  arrowV(sl, Rc, Ry, Ry + g - 0.01); Ry += g;

  processBox(sl, Rx, Ry, Rw, rh, "Sales Opportunity Created", 8);
  Ry += rh + g;
  arrowV(sl, Rc, Ry, Ry + g - 0.01); Ry += g;

  const salStages = ["lead", "contacted", "requirement", "availability", "quoted", "negotiation", "confirmed", "invoiced", "delivered", "payment"];
  const salColors = ["546E7A","1565C0","00695C","6A1B9A","F57F17","E65100","2E7D32","1565C0","00695C","2E7D32"];
  salStages.forEach((stage, i) => {
    box(sl, Rx, Ry, Rw, rh - 0.04, stage.toUpperCase(), salColors[i], "FFFFFF", 7);
    Ry += rh - 0.04;
    if (i < salStages.length - 1) {
      arrowV(sl, Rc, Ry, Ry + g - 0.01);
      Ry += g;
    }
  });

  Ry += g;
  arrowV(sl, Rc, Ry, Ry + g - 0.01); Ry += g;
  diamond(sl, Rx, Ry, Rw, rh + 0.1, "Deal Outcome?", C.orange, 8);
  const salDecY = Ry;
  Ry += rh + 0.1 + g;

  // WON
  arrowV(sl, Rc, salDecY + rh + 0.1, Ry, C.green);
  label(sl, Rc - 0.5, salDecY + rh + 0.05, 0.5, 0.18, "WON↓", C.green, 6.5);
  box(sl, Rx, Ry, Rw, rh, "Link to Sale Record", C.green, "FFFFFF", 7.5);

  // LOST
  arrowH(sl, Rx + Rw, Rx + Rw + 0.12, salDecY + (rh + 0.1) / 2, C.red);
  box(sl, Rx + Rw + 0.12, salDecY, 1.4, rh, "Log Reason\n+ Archive", C.grey, "FFFFFF", 7.5);
  label(sl, Rx + Rw + 0.04, salDecY - 0.2, 0.6, 0.2, "LOST→", C.red, 6.5);

  // KPI strip at bottom
  const kpis = [
    { label: "Avg Deal Cycle", value: "12d", color: C.navy },
    { label: "Win Rate (Sales)", value: "38%", color: C.green },
    { label: "Win Rate (Sourcing)", value: "55%", color: C.teal },
    { label: "Active Opportunities", value: "24", color: C.orange },
  ];
  // (No room on this slide, skip for clean layout)
}

// ─────────────────────────────────────────────────────────────────────────────
// SLIDE 5 — System Architecture Flow
// ─────────────────────────────────────────────────────────────────────────────
{
  const sl = prs.addSlide();
  sl.background = { color: "1A237E" }; // deep indigo

  slideTitle(sl, "System Architecture", "OxyPC Inventory ERP — Infrastructure & Security Layers");

  // Override title banner to match dark bg
  sl.addShape("rect", { x: 0, y: 0, w: 13.33, h: 0.48, fill: { color: "0D1B6B" }, line: { color: "0D1B6B", width: 0 } });
  sl.addText("System Architecture  |  OxyPC Inventory ERP — Infrastructure & Security Layers", {
    x: 0.18, y: 0, w: 13.0, h: 0.48, align: "left", valign: "middle", fontSize: 12, bold: true, color: "CADCFC",
  });

  const BX = "263280"; // box bg
  const BXT = "CADCFC"; // box text
  const ACCENT = "42A5F5"; // light blue

  function archBox(x, y, w, h, text, fillC = BX, textC = BXT, fs = 9) {
    sl.addShape("roundRect", { x, y, w, h, fill: { color: fillC }, line: { color: ACCENT, width: 1 }, rectRadius: 0.1, shadow: { type: "outer", blur: 8, offset: 3, angle: 135, color: "000000", opacity: 0.4 } });
    sl.addText(text, { x, y, w, h, align: "center", valign: "middle", fontSize: fs, bold: true, color: textC, wrap: true, margin: 4 });
  }

  function archArrow(x1, y1, x2, y2) {
    sl.addShape("line", { x: x1, y: y1, w: x2 - x1, h: y2 - y1, line: { color: ACCENT, width: 1.5, endArrowType: "arrow" } });
  }

  function archLabel(x, y, w, h, text) {
    sl.addText(text, { x, y, w, h, align: "center", valign: "middle", fontSize: 7.5, color: "7BA7D4", italic: true });
  }

  // Layer headers
  const layers = [
    { y: 0.6, label: "CLIENT LAYER" },
    { y: 1.35, label: "INGRESS / PROXY" },
    { y: 1.98, label: "APPLICATION LAYER" },
    { y: 2.73, label: "SECURITY MIDDLEWARE" },
    { y: 3.55, label: "DATA ACCESS LAYER" },
    { y: 4.3, label: "DATABASE LAYER" },
    { y: 5.05, label: "BACKUP / DR" },
  ];
  layers.forEach(l => {
    sl.addText(l.label, {
      x: 0.1, y: l.y, w: 1.5, h: 0.3,
      align: "right", valign: "middle", fontSize: 6.5, bold: true, color: "7BA7D4", italic: true,
    });
    sl.addShape("line", { x: 1.65, y: l.y + 0.15, w: 11.5, h: 0, line: { color: "2A3B9A", width: 0.5, dashType: "dash" } });
  });

  // Client boxes
  archBox(1.8, 0.62, 2.2, 0.52, "LAN Browser Users\n(React Frontend)", "0D3B7A", "CADCFC", 8.5);
  archBox(5.45, 0.62, 2.4, 0.52, "OxyQC EXE\n(Windows Desktop)", "0D3B7A", "CADCFC", 8.5);
  archBox(9.1, 0.62, 2.4, 0.52, "WhatsApp Business\n(WA Web API)", "0D3B7A", "CADCFC", 8.5);

  // Arrows to proxy
  archArrow(2.9, 1.14, 2.9, 1.37);
  archArrow(6.65, 1.14, 6.65, 1.37);
  archArrow(10.3, 1.14, 10.3, 1.37);

  // nginx
  archBox(2.5, 1.38, 8.2, 0.5, "nginx Reverse Proxy — :80 / :443  (SSL Termination, Static Files, Load Balancing)", "1A2C80", BXT, 8.5);

  // Arrow to FastAPI
  archArrow(6.6, 1.88, 6.6, 2.0);

  // FastAPI
  archBox(2.5, 2.02, 8.2, 0.58, "FastAPI Application — 4 Uvicorn Workers — Port :8000\n(REST API, WebSocket, Background Tasks)", "1A2C80", BXT, 8.5);

  // Security middleware row
  const secBoxes = [
    { x: 1.8, label: "JWT Cookie\nAuthentication" },
    { x: 4.15, label: "CSRF\nProtection" },
    { x: 6.45, label: "RBAC\n11 Roles" },
    { x: 8.75, label: "Rate Limiter\n30 req/min" },
    { x: 11.0, label: "Input\nValidation" },
  ];
  archArrow(6.6, 2.6, 6.6, 2.75);
  secBoxes.forEach(s => {
    sl.addShape("roundRect", { x: s.x, y: 2.76, w: 2.12, h: 0.6, fill: { color: "1B3A8F" }, line: { color: "5C7CFA", width: 1 }, rectRadius: 0.08, shadow: { type: "outer", blur: 4, offset: 2, angle: 135, color: "000000", opacity: 0.35 } });
    sl.addText(s.label, { x: s.x, y: 2.76, w: 2.12, h: 0.6, align: "center", valign: "middle", fontSize: 8, bold: true, color: "CADCFC", wrap: true, margin: 3 });
  });

  // Arrow to ORM
  archArrow(6.6, 3.36, 6.6, 3.57);

  // SQLAlchemy ORM
  archBox(2.5, 3.58, 8.2, 0.5, "SQLAlchemy 2.0 ORM (async)  —  Alembic Migrations  —  Connection Pooling (asyncpg)", "1A2C80", BXT, 8.5);

  // Arrow to Postgres
  archArrow(6.6, 4.08, 6.6, 4.32);

  // PostgreSQL
  archBox(2.5, 4.33, 8.2, 0.55, "PostgreSQL 15  —  35+ Tables  —  pgvector  —  Row Level Security  —  Audit Triggers", "0D3B7A", "FFFFFF", 9);

  // Arrow to backup
  archArrow(6.6, 4.88, 6.6, 5.07);

  // Backup
  archBox(2.5, 5.08, 8.2, 0.45, "pg_dump Nightly Backup  —  Offsite Geo-Redundant Storage  —  PITR  —  Quarterly Restore Tests", "0D3B7A", BXT, 8);

  // ── WhatsApp side service ─────────────────────────────────────────────────
  sl.addShape("roundRect", { x: 9.7, y: 2.02, w: 3.4, h: 2.5, fill: { color: "0D2E5E" }, line: { color: "25D366", width: 1.5 }, rectRadius: 0.12, shadow: { type: "outer", blur: 6, offset: 3, angle: 135, color: "000000", opacity: 0.4 } });
  sl.addText("WhatsApp Service", { x: 9.8, y: 2.04, w: 3.2, h: 0.3, align: "center", fontSize: 9, bold: true, color: "25D366" });
  archBox(9.88, 2.38, 3.04, 0.44, "Node.js Service — :3001", "0D3B7A", "CADCFC", 8);
  arrowV(sl, 11.4, 2.82, 2.96);
  archBox(9.88, 2.97, 3.04, 0.44, "whatsapp-web.js", "0D3B7A", "CADCFC", 8);
  arrowV(sl, 11.4, 3.41, 3.55);
  archBox(9.88, 3.56, 3.04, 0.44, "WhatsApp Business API", "128C7E", "FFFFFF", 8);

  // Arrow from FastAPI to WA service
  sl.addShape("line", { x: 8.7, y: 2.31, w: 1.18, h: 0, line: { color: "25D366", width: 1.2, dashType: "dash", endArrowType: "arrow" } });
  sl.addText("WA triggers", { x: 8.72, y: 2.14, w: 1.15, h: 0.2, fontSize: 6.5, color: "25D366", align: "center" });

  // OxyQC connector
  sl.addShape("line", { x: 5.45, y: 0.88, w: -2.2, h: 0, line: { color: ACCENT, width: 1.0, dashType: "dash", endArrowType: "arrow" } });
  archLabel(3.6, 0.68, 1.8, 0.2, "HTTP/HTTPS");

  // Security layer note
  sl.addText("All endpoints: OAuth 2.0  •  TLS 1.3  •  MFA enforced  •  No direct DB access from frontend  •  AI read-only via views", {
    x: 1.7, y: 5.68, w: 9.7, h: 0.3,
    align: "center", valign: "middle", fontSize: 7.5, color: "7BA7D4", italic: true,
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// SLIDE 6 — RBAC Access Matrix
// ─────────────────────────────────────────────────────────────────────────────
{
  const sl = prs.addSlide();
  sl.background = { color: C.lightBg };
  slideTitle(sl, "RBAC Access Matrix", "Role-Based Access Control — 9 Roles × 12 Modules");

  const roles = ["Admin", "Manager", "IQC Engineer", "L1 Technician", "L2/L3 Technician", "QC Inspector", "Cosmetic Team", "Sales", "Dealer"];
  const modules = ["GRN /\nInventory", "IQC", "L1\nRepair", "L2/L3\nRepair", "QC", "Cosmetic", "Sales", "CRM", "Finance", "Reports", "Admin\nPanel", "API\nAccess"];

  // Access matrix: 1=full, 0=none, 2=read-only
  const matrix = [
    //GRN IQC L1  L2  QC  COS SAL CRM FIN REP ADM API
    [1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1 ], // Admin
    [1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  0,  1 ], // Manager
    [2,  1,  0,  0,  0,  0,  0,  0,  0,  2,  0,  0 ], // IQC Engineer
    [0,  0,  1,  0,  0,  0,  0,  0,  0,  2,  0,  0 ], // L1 Technician
    [0,  0,  0,  1,  0,  0,  0,  0,  0,  2,  0,  0 ], // L2/L3 Technician
    [0,  2,  0,  0,  1,  0,  0,  0,  0,  2,  0,  0 ], // QC Inspector
    [0,  0,  0,  0,  0,  1,  0,  0,  0,  2,  0,  0 ], // Cosmetic Team
    [2,  0,  0,  0,  0,  0,  1,  1,  2,  1,  0,  0 ], // Sales
    [0,  0,  0,  0,  0,  0,  2,  0,  2,  2,  0,  0 ], // Dealer
  ];

  const tw = 12.6, tx = 0.37, ty = 0.62;
  const colW_header = 1.5;
  const colW_module = (tw - colW_header) / modules.length;

  // Header row
  const headerRow = [
    { text: "Role / Module", options: { fill: { color: C.navy }, color: "FFFFFF", bold: true, fontSize: 8.5, align: "left", valign: "middle" } },
    ...modules.map(m => ({
      text: m,
      options: { fill: { color: C.navy }, color: "FFFFFF", bold: true, fontSize: 7, align: "center", valign: "middle" },
    })),
  ];

  const tableData = [headerRow];
  const roleColors = ["1B3A8F","1B3A8F","1565C0","00695C","00695C","2E7D32","6A1B9A","00695C","546E7A"];

  roles.forEach((role, ri) => {
    const row = [
      {
        text: role,
        options: {
          fill: { color: ri % 2 === 0 ? "EEF4FC" : "FFFFFF" },
          color: roleColors[ri],
          bold: true,
          fontSize: 8.5,
          align: "left",
          valign: "middle",
        },
      },
      ...matrix[ri].map((val) => {
        let fillColor, text, textColor;
        if (val === 1) { fillColor = "C8E6C9"; text = "✓"; textColor = "1B5E20"; }
        else if (val === 2) { fillColor = "FFF9C4"; text = "R"; textColor = "E65100"; }
        else { fillColor = ri % 2 === 0 ? "ECEFF1" : "F5F5F5"; text = "—"; textColor = "90A4AE"; }
        return {
          text,
          options: { fill: { color: fillColor }, color: textColor, bold: val > 0, fontSize: 9, align: "center", valign: "middle" },
        };
      }),
    ];
    tableData.push(row);
  });

  const colWArr = [colW_header, ...modules.map(() => colW_module)];
  sl.addTable(tableData, {
    x: tx, y: ty, w: tw, h: 5.8,
    border: { pt: 0.5, color: "CADCFC" },
    colW: colWArr,
  });

  // Legend
  sl.addShape("rect", { x: tx, y: ty + 5.88, w: 0.22, h: 0.22, fill: { color: "C8E6C9" }, line: { color: "C8E6C9", width: 0 } });
  sl.addText("✓ = Full Access", { x: tx + 0.28, y: ty + 5.88, w: 1.5, h: 0.22, fontSize: 8, color: C.black, valign: "middle" });
  sl.addShape("rect", { x: tx + 2.0, y: ty + 5.88, w: 0.22, h: 0.22, fill: { color: "FFF9C4" }, line: { color: "FFF9C4", width: 0 } });
  sl.addText("R = Read-Only", { x: tx + 2.28, y: ty + 5.88, w: 1.5, h: 0.22, fontSize: 8, color: C.black, valign: "middle" });
  sl.addShape("rect", { x: tx + 4.0, y: ty + 5.88, w: 0.22, h: 0.22, fill: { color: "ECEFF1" }, line: { color: "ECEFF1", width: 0 } });
  sl.addText("— = No Access", { x: tx + 4.28, y: ty + 5.88, w: 1.5, h: 0.22, fontSize: 8, color: C.black, valign: "middle" });
  sl.addText("* RBAC enforced at DB row-level AND application middleware  •  All roles require MFA  •  Quarterly access reviews mandatory", {
    x: tx + 6.0, y: ty + 5.88, w: 6.6, h: 0.22,
    fontSize: 7.5, color: C.grey, italic: true, align: "right", valign: "middle",
  });
}

// ── Save ──────────────────────────────────────────────────────────────────────
prs.writeFile({ fileName: OUTPUT }).then(() => {
  const stats = fs.statSync(OUTPUT);
  console.log(`✅ Saved: ${OUTPUT}`);
  console.log(`   Size: ${(stats.size / 1024).toFixed(1)} KB (${stats.size.toLocaleString()} bytes)`);
  console.log(`   Slides: 6`);
  console.log(`   Slide 1: Cover — OxyPC Refurbishment ERP`);
  console.log(`   Slide 2: Device Lifecycle — GRN → IQC → Repair Escalation → QC → Sale`);
  console.log(`   Slide 3: Dealer & Finance — Order → Invoice → Payment → Ageing`);
  console.log(`   Slide 4: CRM Pipelines — Sourcing (8 stages) & Sales (10 stages)`);
  console.log(`   Slide 5: System Architecture — nginx → FastAPI → PostgreSQL layers`);
  console.log(`   Slide 6: RBAC Access Matrix — 9 roles × 12 modules`);
}).catch(err => {
  console.error("❌ Error:", err);
  process.exit(1);
});
