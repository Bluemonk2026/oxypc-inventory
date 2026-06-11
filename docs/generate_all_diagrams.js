/**
 * OxyPC — Complete Diagram Reference Document Generator
 * 8 diagrams: Process Flow, Swimlane, ERD, Data Flow, System Architecture,
 *             API Mapping, UI Mapping, AI Layer
 * Output: docs/OxyPC_All_Diagrams.docx (A4 Landscape)
 */
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
  VerticalAlign, Header, Footer, PageNumber, PageBreak, PageOrientation,
  TabStopType,
} = require('docx');
const fs = require('fs');

// A4 Landscape — docx-js: pass portrait dims + LANDSCAPE orientation
// Content width = long edge − 2×margin = 16838 − 1440 = 15398 DXA
const PAGE_W  = 11906;   // short edge (A4 portrait width)
const PAGE_H  = 16838;   // long edge  (A4 portrait height)
const MARGIN  = 720;     // 0.5 inch
const CW      = PAGE_H - (MARGIN * 2); // 15398 usable DXA

const C = {
  navy:    '1F3864', blue:   '2E75B6', green:  '375623', orange: '843C0C',
  red:     '8B0000', purple: '4B1C6D', gold:   '7F6000', dgray:  '595959',
  lBlue:   'D9E1F2', lGreen: 'E2EFDA', lOrng:  'FCE4D6', lRed:   'FFE2E2',
  lYellow: 'FFF2CC', lPurp:  'E9D7F5', lGray:  'F2F2F2', white:  'FFFFFF',
  teal:    '1F4E79', lTeal:  'DAEEF3',
};

// ── Border helpers ──────────────────────────────────────────────────────────
const thin   = (col='CCCCCC') => ({ style: BorderStyle.SINGLE, size: 1, color: col });
const thick  = (col=C.blue)   => ({ style: BorderStyle.SINGLE, size: 4, color: col });
const none   = ()             => ({ style: BorderStyle.NONE,   size: 0, color: C.white });
const bAll   = (col='CCCCCC') => ({ top: thin(col), bottom: thin(col), left: thin(col), right: thin(col) });
const bNone  = ()             => ({ top: none(), bottom: none(), left: none(), right: none() });

// ── Cell helpers ────────────────────────────────────────────────────────────
function hCell(text, w, bg=C.navy, fg='FFFFFF', span=1, sz=18, bold=true) {
  return new TableCell({
    width: { size: w, type: WidthType.DXA }, columnSpan: span,
    borders: bAll(C.blue), shading: { fill: bg, type: ShadingType.CLEAR },
    margins: { top:80, bottom:80, left:120, right:120 },
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text, bold, color: fg, size: sz, font:'Arial' })],
    })],
  });
}
function dCell(text, w, bg=C.white, fg='000000', align=AlignmentType.LEFT, sz=16, bold=false) {
  return new TableCell({
    width: { size: w, type: WidthType.DXA },
    borders: bAll(), shading: { fill: bg, type: ShadingType.CLEAR },
    margins: { top:60, bottom:60, left:120, right:120 },
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({
      alignment: align,
      children: [new TextRun({ text: text||'', bold, color: fg, size: sz, font:'Arial' })],
    })],
  });
}
function secHeader(title, color, cols) {
  return new TableRow({ children:[new TableCell({
    columnSpan: cols, width:{ size:CW, type:WidthType.DXA },
    shading:{ fill: color, type: ShadingType.CLEAR },
    borders:{ top:thick(color), bottom:thick(color), left:thick(color), right:thick(color) },
    margins:{ top:70, bottom:70, left:120, right:120 },
    children:[new Paragraph({ children:[new TextRun({ text:title, font:'Arial', bold:true, size:18, color:'FFFFFF' })] })],
  })] });
}

// ── Typography helpers ───────────────────────────────────────────────────────
function h1(text) {
  return new Paragraph({ heading: HeadingLevel.HEADING_1, spacing:{ before:360, after:180 },
    children:[new TextRun({ text, font:'Arial', bold:true, size:38, color:C.navy })] });
}
function h2(text) {
  return new Paragraph({ heading: HeadingLevel.HEADING_2, spacing:{ before:240, after:120 },
    children:[new TextRun({ text, font:'Arial', bold:true, size:28, color:C.blue })] });
}
function p(text, sz=20, color='333333', bold=false) {
  return new Paragraph({ spacing:{ before:60, after:60 },
    children:[new TextRun({ text, font:'Arial', size: sz, color, bold })] });
}
function pb() { return new Paragraph({ children:[new PageBreak()] }); }
function sp(before=200) { return new Paragraph({ spacing:{before} }); }

// ═══════════════════════════════════════════════════════════════════════════════
// 1. PROCESS FLOW DIAGRAM
// ═══════════════════════════════════════════════════════════════════════════════
function processFlow() {
  const cols = [
    Math.round(CW*0.05), Math.round(CW*0.22), Math.round(CW*0.04),
    Math.round(CW*0.22), Math.round(CW*0.04), Math.round(CW*0.22),
    Math.round(CW*0.04), Math.round(CW*0.17),
  ];

  function stepRow(step, action, d1, decision, d2, next, owner, bgA=C.lBlue, bgN=C.lGreen) {
    return new TableRow({ children:[
      dCell(step,     cols[0], C.lGray,   C.navy,   AlignmentType.CENTER, 18, true),
      dCell(action,   cols[1], bgA,       '000000', AlignmentType.LEFT,   16),
      dCell(d1,       cols[2], C.lGray,   C.blue,   AlignmentType.CENTER, 24, true),
      dCell(decision, cols[3], C.lYellow, '000000', AlignmentType.LEFT,   15),
      dCell(d2,       cols[4], C.lGray,   C.blue,   AlignmentType.CENTER, 24, true),
      dCell(next,     cols[5], bgN,       '000000', AlignmentType.LEFT,   16),
      dCell('↓',      cols[6], C.lGray,   C.dgray,  AlignmentType.CENTER, 18, true),
      dCell(owner,    cols[7], C.lGray,   C.navy,   AlignmentType.LEFT,   14),
    ]});
  }

  return [
    h1('1. Process Flow Diagram'),
    p('End-to-end device lifecycle from Sourcing Deal through final Sale. Squares = process steps. Diamonds (◆) = decision points.'),
    sp(200),
    new Table({
      width:{ size:CW, type:WidthType.DXA }, columnWidths: cols,
      rows:[
        new TableRow({ children:[
          hCell('Step',     cols[0], C.navy), hCell('Action',      cols[1], C.navy),
          hCell('',         cols[2], C.navy), hCell('Decision ◆',  cols[3], C.navy),
          hCell('',         cols[4], C.navy), hCell('Next Step',   cols[5], C.navy),
          hCell('',         cols[6], C.navy), hCell('Owner',       cols[7], C.navy),
        ]}),
        stepRow('1','Supplier Contact / Sourcing Deal\nCRM Sourcing Pipeline created\nContact logged','→',
          '◆ PO raised?\nYES → Issue PO\nNO → Negotiate','→',
          'Purchase Order Issued\n/crm/purchase-orders/new','Purchase Mgr', C.lGreen, C.lBlue),
        stepRow('2','GRN Submitted\nLot + devices received\nQty vs Invoice checked','→',
          '◆ IQC location?\nDeshwal → IQC at Deshwal\nOxypc → IQC at Oxypc','→',
          'GRN Recorded\n/grn/new\nDevice barcodes created','Inventory Mgr', C.lBlue, C.lGreen),
        stepRow('3','Incoming Quality Check (IQC)\n/iqc/new\n65 fault parameters captured','→',
          '◆ IQC Result?\nPASS → Stock\nFAIL → Repair\nPNA → Scrap','→',
          'Device added to Inventory\ncurrent_stage = iqc → stock','IQC Inspector', C.lYellow, C.lGreen),
        stepRow('4','Stock Entry\nDevice in Inventory\nGrade provisionally set','→',
          '◆ Repair needed?\nYES → Assign to Engineer\nNO → QC Assignment','→',
          'L1 / L2 / L3 Repair\n/repair/l1 | l2 | l3','Inventory Mgr', C.lGreen, C.lOrng),
        stepRow('5','Repair (L1 / L2 / L3)\nFaults fixed, parts used\nSpare part inventory decremented','→',
          '◆ Repair outcome?\nOK → QC\nEscalate → L4\nUnfixable → Scrap','→',
          'QC Assignment\n/qc/new\nFunctional test','L1/L2/L3 Engineer', C.lOrng, C.lBlue),
        stepRow('6','Quality Check (QC)\nBattery / Screen / Keyboard / Body\nScores entered, Grade finalized','→',
          '◆ QC result?\nPASS → Cosmetic\nFAIL → Back to Repair\nScrap','→',
          'Cosmetic Pipeline\nCleaning → Painting → Final QC','QC Inspector', C.lBlue, C.lGreen),
        stepRow('7','Cosmetic Refurbishment\nMasking → Cleaning → Water Sanding\nDry Sanding → Painting → Final QC','→',
          '◆ Final QC?\nPASS → Ready to Sale\nFunc Fail → Repair\nPaint Fail → Redo\nScrap','→',
          'Ready to Sale\n/sales/ready\ncurrent_stage = sales','Cosmetic Team', C.lGreen, C.lBlue),
        stepRow('8','Sale Created\n/sales/new\nInvoice generated, payment recorded','→',
          '◆ Customer type?\nB2B → Dealer Order\nB2C → Direct Sale\nReturn → Re-enter Stock','→',
          'SOLD\ncurrent_stage = sold\nRevenue booked','Sales Team', C.lBlue, C.lGreen),
      ],
    }),
    sp(180),
    p('Legend:  ◆ = Decision Point    → = Flow Direction    [/path] = System URL', 17, C.dgray),
    pb(),
  ];
}

// ═══════════════════════════════════════════════════════════════════════════════
// 2. SWIMLANE DIAGRAM
// ═══════════════════════════════════════════════════════════════════════════════
function swimlane() {
  const labelW = Math.round(CW * 0.09);
  const laneW  = Math.round((CW - labelW) / 7);
  const laneColors = [
    {bg:'D9E1F2',fg:'1F3864'},{bg:'E2EFDA',fg:'375623'},{bg:'FCE4D6',fg:'843C0C'},
    {bg:'FFF2CC',fg:'7F6000'},{bg:'DAEEF3',fg:'1F4E79'},{bg:'E9D7F5',fg:'4B1C6D'},
    {bg:'FFE2E2',fg:'8B0000'},
  ];
  const laneNames = ['PURCHASE\n& CRM','IQC\n(INTAKE QC)','STOCK\n& INVENTORY',
                     'REPAIR\n(L1/L2/L3)','QUALITY\nCONTROL','COSMETIC\nREFURB','SALES\n& DEALER'];

  function swCell(text, lc) {
    const empty = !text || !text.trim();
    return new TableCell({
      width:{size:laneW,type:WidthType.DXA}, borders:bAll(),
      shading:{fill: empty ? 'F8F8F8' : lc.bg, type:ShadingType.CLEAR},
      margins:{top:80,bottom:80,left:80,right:80}, verticalAlign:VerticalAlign.CENTER,
      children:[new Paragraph({ alignment:AlignmentType.CENTER,
        children:[new TextRun({ text:text||'', font:'Arial', size:15,
          color: empty ? 'DDDDDD' : lc.fg, bold:!empty })] })],
    });
  }

  function swRow(label, ...cells) {
    return new TableRow({ height:{value:1200,rule:'atLeast'}, children:[
      new TableCell({
        width:{size:labelW,type:WidthType.DXA}, borders:bAll(),
        shading:{fill:C.lBlue,type:ShadingType.CLEAR},
        margins:{top:80,bottom:80,left:80,right:80}, verticalAlign:VerticalAlign.CENTER,
        children:[new Paragraph({ alignment:AlignmentType.CENTER,
          children:[new TextRun({ text:label, font:'Arial', size:15, color:C.navy, bold:true })] })],
      }),
      ...cells.map((txt, i) => swCell(txt, laneColors[i])),
    ]});
  }

  return [
    h1('2. Swimlane Diagram'),
    p('Horizontal lanes per department. Each phase flows top→bottom. Handoffs cross lane boundaries.'),
    sp(200),
    new Table({
      width:{size:CW,type:WidthType.DXA}, columnWidths:[labelW,...Array(7).fill(laneW)],
      rows:[
        new TableRow({ children:[
          hCell('PHASE',labelW,C.navy),
          ...laneNames.map((n,i) => hCell(n, laneW, laneColors[i].bg, laneColors[i].fg, 1, 14, true)),
        ]}),
        swRow('Phase 1\nSourcing',
          'CRM Sourcing\nDeal Created\n\nPO Issued\nto Supplier','','','','','',''),
        swRow('Phase 2\nReceiving',
          'GRN Submitted\nQty verified vs\nInvoice',
          'Device Received\nBarcode Assigned\n/grn/submit','','','','',''),
        swRow('Phase 3\nIQC','',
          'IQC Inspection\n65 Parameters\nGrade Assessed\n\nPASS→Stock\nFAIL→Repair\nPNA→Scrap',
          'Added to\nInventory\nStage: IQC','','','',''),
        swRow('Phase 4\nRepair','','',
          'Assigned to\nRepair Engineer',
          'L1 Repair\nL2 Repair\nL3/L4 Repair\n\nParts Used\nSparePart\nInventory\nUpdated\n\nOK→QC\nEscalate\nScrap','','',''),
        swRow('Phase 5\nQC','','','',
          'QC Check\nBattery Score\nScreen Score\nKeyboard Score\nBody Score\nGrade Set\n\nPASS→Cosmetic\nFAIL→Repair','',''),
        swRow('Phase 6\nCosmetic','','','','',
          'Cleaning\nMasking\nWater Sanding\nDry Sanding\nPainting\nFinal QC\n\nPASS→Sale\nFAIL→Redo',''),
        swRow('Phase 7\nSales',
          'Invoice Generated\nCredit Note\nDealer Ledger\nPayment Tracking','','','','','',
          'Sale Entry\nDealer Order\nB2B / B2C\nPayment Recorded\nDevice = SOLD'),
      ],
    }),
    sp(160), p('Each cell shows the activities performed by that department in that phase.', 17, C.dgray),
    pb(),
  ];
}

// ═══════════════════════════════════════════════════════════════════════════════
// 3. ENTITY RELATIONSHIP DIAGRAM
// ═══════════════════════════════════════════════════════════════════════════════
function erd() {
  const c1 = Math.round(CW*0.17), c2 = Math.round(CW*0.14);
  const c3 = Math.round(CW*0.28), c4 = CW-c1-c2-c3;

  const groups = [
    { name:'USER & AUTHENTICATION', color:C.navy, light:C.lBlue, tables:[
      { name:'users', pk:'id UUID', fks:[], cols:['username (UNIQUE)', 'full_name', 'password_hash', 'role Enum', 'status', 'created_at', 'last_login'] },
      { name:'user_permissions', pk:'id UUID', fks:['user_id → users.id'], cols:['permission', 'granted', 'granted_by', 'granted_at'] },
      { name:'login_logs', pk:'id UUID', fks:['user_id → users.id'], cols:['action', 'ip_address', 'timestamp', 'notes'] },
      { name:'attendance', pk:'id UUID', fks:['user_id → users.id'], cols:['date', 'check_in', 'check_out', 'status', 'marked_by', 'notes'] },
    ]},
    { name:'INVENTORY & DEVICES', color:C.green, light:C.lGreen, tables:[
      { name:'lots', pk:'id UUID', fks:[], cols:['lot_number UNIQUE', 'supplier_name', 'buying_price', 'qty', 'purchase_date', 'invoice_value', 'taxable_amount', 'sgst/cgst/igst', 'grn_system_number'] },
      { name:'lot_line_items', pk:'id UUID', fks:['lot_id → lots.id'], cols:['sub_category', 'brand', 'model', 'cpu', 'generation', 'ram_gb', 'storage_gb', 'grade', 'unit_price', 'qty'] },
      { name:'devices', pk:'id UUID', fks:['lot_id → lots.id', 'lot_line_item_id → lot_line_items.id'], cols:['barcode UNIQUE', 'brand', 'model', 'device_type', 'serial_no', 'cpu', 'generation', 'ram_gb', 'storage_gb', 'battery_health_pct', 'grade Enum', 'current_stage Enum', 'device_price'] },
      { name:'stage_movements', pk:'id UUID', fks:['device_id → devices.id'], cols:['from_stage', 'to_stage', 'moved_by', 'moved_at', 'exited_at', 'notes'] },
    ]},
    { name:'LOCATION & STORAGE', color:C.teal, light:C.lTeal, tables:[
      { name:'storage_locations', pk:'id UUID', fks:[], cols:['zone Enum', 'unit_type Enum', 'unit_id UNIQUE', 'slot', 'capacity', 'is_active'] },
      { name:'device_location_logs', pk:'id UUID', fks:['device_id → devices.id', 'location_id → storage_locations.id', 'actor_id → users.id'], cols:['action Enum', 'actor_name', 'notes', 'logged_at'] },
      { name:'inventory_audits', pk:'id UUID', fks:['initiated_by → users.id'], cols:['audit_number UNIQUE', 'zone_filter', 'status Enum', 'initiated_at', 'expected_count', 'found_count', 'missing_count'] },
      { name:'audit_scan_items', pk:'id UUID', fks:['audit_id → inventory_audits.id', 'device_id → devices.id', 'location_id → storage_locations.id'], cols:['barcode_scanned', 'scan_status Enum', 'scanned_by_name', 'scanned_at'] },
    ]},
    { name:'REPAIR & QC', color:C.orange, light:C.lOrng, tables:[
      { name:'iqc_inspections', pk:'id UUID', fks:['device_id → devices.id (UNIQUE)'], cols:['inspector_name', 'power_on', 'bios_password', 'status', 'screen_* ×15', 'panel_a/b/c/d_* ×20', 'keyboard_* ×4', 'port_* ×3', 'wifi_status', 'webcam_status', 'r2v3_grade_category', 'remarks', 'stress_report'] },
      { name:'repair_jobs', pk:'id UUID', fks:['device_id → devices.id', 'engineer_id → users.id'], cols:['stage', 'status Enum', 'faults', 'dust_cleaning', 'thermal_paste', 'final_status', 'ram_status', 'hdd_updated', 'scrap_reason', 'received_from'] },
      { name:'repair_attempts', pk:'id UUID', fks:['device_id → devices.id', 'repair_job_id → repair_jobs.id'], cols:['level', 'attempt_no', 'cost', 'time_spent', 'outcome', 'notes'] },
      { name:'qc_checks', pk:'id UUID', fks:['device_id → devices.id', 'inspector_id → users.id'], cols:['battery_score', 'screen_score', 'keyboard_score', 'body_score', 'total_score', 'result', 'grade', 'attempt_number', 'send_to_stage', 'notes'] },
    ]},
    { name:'SALES', color:C.red, light:C.lRed, tables:[
      { name:'sales', pk:'id UUID', fks:['device_id → devices.id'], cols:['sale_number UNIQUE', 'sale_price', 'customer_name', 'customer_phone', 'customer_state', 'invoice_no', 'payment_mode', 'sold_by', 'sold_at', 'notes'] },
      { name:'returns', pk:'id UUID', fks:['sale_id → sales.id', 'device_id → devices.id'], cols:['return_date', 'reason', 'condition_on_return', 'action_taken', 'reentered_stage', 'refund_amount'] },
    ]},
    { name:'DEALERS', color:C.purple, light:C.lPurp, tables:[
      { name:'dealers', pk:'id UUID', fks:[], cols:['dealer_code UNIQUE', 'business_name', 'phone', 'gstin', 'dealer_type', 'credit_limit', 'outstanding_amount', 'total_purchases', 'status', 'assigned_to'] },
      { name:'dealer_orders', pk:'id UUID', fks:['dealer_id → dealers.id'], cols:['order_number UNIQUE', 'order_date', 'items_description', 'total_amount', 'paid_amount', 'due_amount', 'payment_due_date', 'status', 'invoice_number'] },
      { name:'dealer_credit_notes', pk:'id UUID', fks:['dealer_id → dealers.id', 'order_id → dealer_orders.id'], cols:['credit_number UNIQUE', 'credit_date', 'amount', 'reason', 'is_applied', 'applied_at', 'applied_to_order_id'] },
      { name:'dealer_calls', pk:'id UUID', fks:['dealer_id → dealers.id'], cols:['called_by', 'call_date', 'call_type', 'call_outcome', 'quote_given', 'next_followup_date', 'whatsapp_sent'] },
      { name:'dealer_assignments', pk:'id UUID', fks:['dealer_id → dealers.id'], cols:['assigned_to', 'assigned_by', 'assigned_at', 'is_active'] },
    ]},
    { name:'CRM', color:C.navy, light:C.lBlue, tables:[
      { name:'crm_contacts', pk:'id UUID', fks:[], cols:['contact_code UNIQUE', 'contact_type', 'company_name', 'phone', 'gstin', 'source_type', 'buyer_type', 'credit_limit', 'outstanding', 'assigned_to'] },
      { name:'crm_sourcing_deals', pk:'id UUID', fks:['contact_id → crm_contacts.id', 'linked_lot_id → lots.id'], cols:['deal_number UNIQUE', 'title', 'est_quantity', 'asking_price_unit', 'our_offer_unit', 'final_price_total', 'stage', 'inspection_date', 'win_loss_reason'] },
      { name:'crm_sales_opportunities', pk:'id UUID', fks:['contact_id → crm_contacts.id', 'quote_id → crm_quotes.id'], cols:['opp_number UNIQUE', 'title', 'buyer_type', 'required_qty', 'grade_required', 'budget_per_unit', 'stage', 'estimated_value', 'linked_sale_ids'] },
      { name:'crm_quotes', pk:'id UUID', fks:['contact_id → crm_contacts.id'], cols:['quote_number UNIQUE', 'quote_date', 'valid_until', 'payment_terms', 'total_amount', 'status'] },
      { name:'crm_quote_items', pk:'id UUID', fks:['quote_id → crm_quotes.id'], cols:['line_number', 'device_type', 'grade', 'quantity', 'unit_price', 'total_price'] },
      { name:'crm_activities', pk:'id UUID', fks:['contact_id → crm_contacts.id'], cols:['deal_id', 'deal_type', 'activity_type', 'direction', 'summary', 'outcome', 'performed_by', 'next_followup', 'followup_done'] },
      { name:'crm_purchase_orders', pk:'id UUID', fks:['deal_id → crm_sourcing_deals.id', 'contact_id → crm_contacts.id'], cols:['po_number UNIQUE', 'po_date', 'expected_delivery_date', 'total_amount', 'advance_amount', 'status', 'issued_by'] },
      { name:'crm_grade_price_matrix', pk:'id UUID', fks:[], cols:['device_type', 'grade', 'material_type', 'brand', 'min_buy_price', 'max_buy_price', 'target_sell', 'min_margin_pct'] },
    ]},
    { name:'ACCOUNTS & PAYMENTS', color:C.green, light:C.lGreen, tables:[
      { name:'supplier_payments', pk:'id UUID', fks:['contact_id → crm_contacts.id', 'lot_id → lots.id', 'po_id → crm_purchase_orders.id'], cols:['payment_date', 'amount', 'payment_mode', 'reference_no', 'is_advance'] },
      { name:'customer_receipts', pk:'id UUID', fks:['contact_id → crm_contacts.id', 'dealer_id → dealers.id', 'dealer_order_id → dealer_orders.id'], cols:['receipt_date', 'amount', 'payment_mode', 'reference_no'] },
    ]},
    { name:'SPARE PARTS', color:C.gold, light:C.lYellow, tables:[
      { name:'spare_parts', pk:'id UUID', fks:[], cols:['part_code UNIQUE', 'name', 'category', 'unit_price', 'qty_in_stock', 'min_stock_alert', 'supplier'] },
      { name:'spare_parts_purchases', pk:'id UUID', fks:['part_id → spare_parts.id'], cols:['qty', 'unit_price', 'total_price', 'supplier', 'purchase_date', 'invoice_no'] },
      { name:'spare_parts_consumption', pk:'id UUID', fks:['device_id → devices.id', 'lot_id → lots.id', 'part_id → spare_parts.id'], cols:['qty_used', 'unit_cost', 'total_cost', 'used_by', 'used_at', 'stage'] },
      { name:'spare_parts_ledger', pk:'id UUID', fks:['part_id → spare_parts.id', 'device_id → devices.id'], cols:['entry_type', 'qty', 'cost_per_unit', 'total_cost', 'reference_type', 'reference_id'] },
      { name:'ram_tracking', pk:'id UUID', fks:['device_id → devices.id', 'destination_device_id → devices.id'], cols:['action', 'ram_gb', 'ram_type', 'by_user', 'at'] },
    ]},
    { name:'ANALYTICS & AUDIT', color:C.dgray, light:C.lGray, tables:[
      { name:'device_costing', pk:'id UUID', fks:['device_id → devices.id (UNIQUE)'], cols:['base_cost', 'parts_cost', 'labour_cost', 'total_cost', 'expected_sale_value', 'updated_at'] },
      { name:'device_aging', pk:'id UUID', fks:['device_id → devices.id (UNIQUE)'], cols:['days_in_stage', 'total_days', 'stage_entered_at', 'is_stuck', 'is_dead_stock', 'refreshed_at'] },
      { name:'audit_logs', pk:'id UUID', fks:['user_id → users.id'], cols:['username', 'action', 'table_name', 'record_id', 'old_value', 'new_value', 'ip_address', 'timestamp'] },
    ]},
    { name:'STAGE CONTROL & MASTER', color:C.blue, light:C.lBlue, tables:[
      { name:'stage_master', pk:'id UUID', fks:[], cols:['name UNIQUE', 'label', 'sequence', 'created_at'] },
      { name:'allowed_transitions', pk:'id UUID', fks:['from_stage → stage_master.name', 'to_stage → stage_master.name'], cols:['from_stage', 'to_stage', 'created_at'] },
      { name:'master_data', pk:'id UUID', fks:[], cols:['category', 'value', 'description', 'display_order', 'is_active'] },
      { name:'app_settings', pk:'key String PK', fks:[], cols:['value', 'description', 'updated_by', 'updated_at'] },
      { name:'stock_transfers', pk:'id UUID', fks:['device_id → devices.id'], cols:['transfer_type', 'from_warehouse', 'to_warehouse', 'transferred_by', 'transfer_date', 'barcode', 'serial_no'] },
    ]},
    { name:'TELECALLING & MARKET', color:C.orange, light:C.lOrng, tables:[
      { name:'telecalling_sessions', pk:'id UUID', fks:[], cols:['agent_username', 'session_date', 'total_calls', 'connected_calls', 'interested_leads', 'orders_placed', 'target_calls'] },
      { name:'telecalling_records', pk:'id UUID', fks:['dealer_id → dealers.id'], cols:['customer_name', 'phone', 'category', 'brand', 'model', 'processor', 'grade', 'called_by', 'call_outcome', 'next_followup'] },
      { name:'market_availability', pk:'id UUID', fks:['dealer_id → dealers.id'], cols:['brand', 'model', 'category', 'grade', 'trade_type', 'qty', 'price_per_unit', 'dealer_name', 'group_name', 'is_active'] },
    ]},
    { name:'QA / UAT', color:C.purple, light:C.lPurp, tables:[
      { name:'qa_requirements', pk:'id UUID', fks:[], cols:['req_code', 'title', 'source Enum', 'priority Enum', 'status Enum', 'module', 'created_by'] },
      { name:'qa_test_cases', pk:'id UUID', fks:['requirement_id → qa_requirements.id'], cols:['tc_code', 'title', 'scenario', 'steps', 'expected_result', 'type Enum', 'status Enum', 'is_automated', 'module'] },
      { name:'qa_test_executions', pk:'id UUID', fks:['test_case_id → qa_test_cases.id'], cols:['status Enum', 'actual_result', 'build_version', 'environment', 'executed_by', 'executed_at'] },
      { name:'qa_defects', pk:'id UUID', fks:['test_case_id → qa_test_cases.id'], cols:['defect_code', 'title', 'severity Enum', 'priority Enum', 'status Enum', 'module', 'assigned_to', 'root_cause', 'resolution'] },
      { name:'qa_uat_scenarios', pk:'id UUID', fks:['requirement_id → qa_requirements.id'], cols:['uat_code', 'title', 'acceptance_criteria', 'business_owner', 'status Enum', 'sign_off_by'] },
      { name:'qa_releases', pk:'id UUID', fks:[], cols:['version', 'title', 'status Enum', 'planned_date', 'release_date', 'qa_sign_off_by', 'deployed_by', 'rollback_plan'] },
    ]},
  ];

  const out = [
    h1('3. Entity Relationship Diagram (ERD)'),
    p('Complete database schema — 55 tables across 13 bounded contexts. All PKs are UUID unless noted. Soft-delete supported (is_active / deleted_at).'),
    sp(180),
    // Legend
    new Table({ width:{size:CW,type:WidthType.DXA}, columnWidths:[Math.round(CW/4),Math.round(CW/4),Math.round(CW/4),CW-3*Math.round(CW/4)], rows:[
      new TableRow({ children:[
        dCell('🔑 PK = Primary Key (UUID/bigserial)', Math.round(CW/4), C.lGreen, C.green, AlignmentType.LEFT, 15),
        dCell('🔗 FK = Foreign Key → target.column', Math.round(CW/4), C.lBlue,  C.navy,  AlignmentType.LEFT, 15),
        dCell('UNIQUE = unique constraint', Math.round(CW/4), C.lYellow, C.gold,  AlignmentType.LEFT, 15),
        dCell('Enum = enumerated type (string choices)', CW-3*Math.round(CW/4), C.lPurp, C.purple, AlignmentType.LEFT, 15),
      ]}),
    ]}),
    sp(200),
  ];

  for (const g of groups) {
    out.push(new Paragraph({ spacing:{before:220,after:80},
      children:[new TextRun({ text:g.name, font:'Arial', bold:true, size:24, color:g.color })] }));
    out.push(new Table({
      width:{size:CW,type:WidthType.DXA}, columnWidths:[c1,c2,c3,c4],
      rows:[
        new TableRow({ children:[ hCell('Table Name',c1,g.color), hCell('Primary Key',c2,g.color), hCell('Foreign Keys',c3,g.color), hCell('Key Columns',c4,g.color) ] }),
        ...g.tables.map(t => new TableRow({ children:[
          dCell(t.name,   c1, g.light, '000000', AlignmentType.LEFT, 15, true),
          dCell(t.pk,     c2, C.lGreen, C.green, AlignmentType.LEFT, 13),
          dCell(t.fks.length ? t.fks.join('\n') : '(none)', c3, t.fks.length ? C.lBlue : C.lGray, t.fks.length ? C.navy : C.dgray, AlignmentType.LEFT, 13),
          dCell(t.cols.join('\n'), c4, C.white, '333333', AlignmentType.LEFT, 13),
        ]})),
      ],
    }));
    out.push(sp(120));
  }

  out.push(p('Total: 55 tables across 13 bounded contexts', 18, C.dgray, true));
  out.push(pb());
  return out;
}

// ═══════════════════════════════════════════════════════════════════════════════
// 4. DATA FLOW DIAGRAM
// ═══════════════════════════════════════════════════════════════════════════════
function dataFlow() {
  const c1=Math.round(CW*0.12), c2=Math.round(CW*0.21), arr=Math.round(CW*0.04);
  const c4=Math.round(CW*0.21), c6=Math.round(CW*0.21);
  const c7=CW-c1-c2-arr-c4-arr-c6;

  const flows = [
    { mod:'SOURCING\n(CRM)', bg:C.lBlue, fg:C.navy,
      from:'External:\nSupplier / Vendor\nWhatsApp Groups\nMarket Intel',
      proc:'CRM Sourcing Deal\nContact logged\ncrm_contacts\ncrm_sourcing_deals',
      to:'Linked Lot Created\nlots + lot_line_items\nGRN → IQC pipeline',
      stores:'crm_sourcing_deals\ncrm_activities\ncrm_purchase_orders\ncrm_contacts' },
    { mod:'INTAKE\n(GRN / IQC)', bg:C.lGreen, fg:C.green,
      from:'CRM Sourcing Deal\nlinked_lot_id',
      proc:'GRN Submitted\nLot registered\nDevices barcoded\nIQC Inspection',
      to:'Device in Stock\ncurrent_stage=iqc→stock\nInventory Updated',
      stores:'lots\nlot_line_items\ndevices\niqc_inspections\nstage_movements' },
    { mod:'REPAIR\n(L1/L2/L3)', bg:C.lOrng, fg:C.orange,
      from:'Device (IQC FAIL)\ncurrent_stage=repair',
      proc:'Fault Diagnosed\nParts Assigned\nRepair Performed\nOutcome Logged',
      to:'Device → QC\ncurrent_stage=qc\nParts Inventory\nDecremented',
      stores:'repair_jobs\nrepair_attempts\nspare_parts_consumption\nspare_parts_ledger\nram_tracking' },
    { mod:'QC CHECK', bg:C.lBlue, fg:C.navy,
      from:'Device post-Repair\ncurrent_stage=qc',
      proc:'Score Assessment\nBattery/Screen/\nKeyboard/Body\nGrade Finalized',
      to:'PASS→Cosmetic\nFAIL→Repair\nScrap→End\ncurrent_stage updated',
      stores:'qc_checks\ndevices.grade\ndevices.current_stage\nstage_movements' },
    { mod:'COSMETIC\nREFURB', bg:C.lPurp, fg:C.purple,
      from:'Device (QC PASS)\ncurrent_stage=cosmetic',
      proc:'Cleaning→Painting\nFinal QC\nStage Advanced\n/cosmetic/advance',
      to:'Ready for Sale\ncurrent_stage=sales\nDevice Location\nUpdated',
      stores:'stage_movements\ndevice_location_logs\nstorage_locations' },
    { mod:'SALES', bg:C.lRed, fg:C.red,
      from:'Device (stage=sales)\nDealer / Customer\nCRM Opportunity',
      proc:'Sale Created\nInvoice Generated\nPayment Recorded\nDealer Order',
      to:'SOLD\ncurrent_stage=sold\nRevenue Booked\nDealer Outstanding↑',
      stores:'sales\ndealer_orders\ndealer_credit_notes\ncustomer_receipts' },
    { mod:'DEALERS\n& FINANCE', bg:C.lPurp, fg:C.purple,
      from:'dealer_orders\ncustomer_receipts\ndealer_credit_notes',
      proc:'Outstanding Calc\nLedger Updated\nCredit Note Applied\nPayment Reminder',
      to:'WhatsApp Reminder\nInvoice PDF\nAgeing Report\nStatement CSV',
      stores:'dealers.outstanding_amount\ndealer_orders.due_amount\nwhatsapp_messages\naudit_logs' },
    { mod:'REPORTS\n& ANALYTICS', bg:C.lGray, fg:C.dgray,
      from:'ALL tables:\ndevices, lots, sales\nrepair_jobs, dealers\ncrm_* tables',
      proc:'Aggregation Queries\nLot P&L\nBusiness P&L\nStock Aging Reports',
      to:'Dashboard KPIs\nReport Pages\nCSV Exports\nBI-ready views',
      stores:'device_costing\ndevice_aging\naudit_logs\n(no separate DW yet)' },
  ];

  return [
    h1('4. Data Flow Diagram'),
    p('Shows how data enters, is transformed, and flows between OxyPC modules. Each row = one functional domain.'),
    sp(180),
    new Table({
      width:{size:CW,type:WidthType.DXA}, columnWidths:[c1,c2,arr,c4,arr,c6,c7],
      rows:[
        new TableRow({ children:[
          hCell('Module',c1,C.navy), hCell('Input / Source',c2,C.navy), hCell('',arr,C.navy),
          hCell('Process / Transform',c4,C.navy), hCell('',arr,C.navy),
          hCell('Output / Destination',c6,C.navy), hCell('Data Stores',c7,C.navy),
        ]}),
        ...flows.map(f => new TableRow({ children:[
          dCell(f.mod,    c1, f.bg, f.fg, AlignmentType.CENTER, 15, true),
          dCell(f.from,   c2, C.lGray, '333333', AlignmentType.LEFT, 13),
          dCell('→',      arr, C.white, C.blue, AlignmentType.CENTER, 24, true),
          dCell(f.proc,   c4, f.bg, f.fg, AlignmentType.LEFT, 13),
          dCell('→',      arr, C.white, C.blue, AlignmentType.CENTER, 24, true),
          dCell(f.to,     c6, C.lGray, '333333', AlignmentType.LEFT, 13),
          dCell(f.stores, c7, C.lBlue, C.navy,  AlignmentType.LEFT, 12),
        ]})),
      ],
    }),
    sp(160), p('External Entities: Suppliers, Dealers, Customers, WhatsApp Groups', 17, C.dgray),
    pb(),
  ];
}

// ═══════════════════════════════════════════════════════════════════════════════
// 5. SYSTEM ARCHITECTURE DIAGRAM
// ═══════════════════════════════════════════════════════════════════════════════
function sysArch() {
  const c1=Math.round(CW*0.20), c2=Math.round(CW*0.50), c3=CW-c1-c2;
  const layers = [
    { name:'LAYER 7: CLIENT / BROWSER', bg:C.lBlue, fg:C.navy,
      comp:'Chrome / Edge / Mobile Browser (PWA-ready)\nBootstrap 5 + Vanilla JS + Jinja2-rendered HTML\nCSRF double-submit cookie pattern\nJWT stored in httpOnly cookie (no localStorage)\nRole-based sidebar — 9 roles → different nav items visible',
      tech:'HTML5 / CSS3 / Bootstrap 5.3\nVanilla JS / Fetch API\nNo React/Vue — server-side render' },
    { name:'LAYER 6: REVERSE PROXY / LAN ACCESS', bg:C.lGreen, fg:C.green,
      comp:'Uvicorn ASGI — binds 0.0.0.0:8000 (4 worker processes)\nLAN URL: http://192.168.4.8:8000 (internal network only)\nNSSM Windows Service — auto-restart on reboot, crash recovery\nNo Nginx in current deployment — direct Uvicorn exposure',
      tech:'Uvicorn 0.29\nNSSM (Windows service manager)\nWindows Server 2019 / Windows 10' },
    { name:'LAYER 5: APPLICATION FRAMEWORK', bg:C.lOrng, fg:C.orange,
      comp:'FastAPI 0.110 — async request handling, OpenAPI auto-docs\nSlowAPI — rate limiting (30/min login, 100/min global, per IP)\n38 Router modules — prefix-namespaced, include_router pattern\nJinja2 Templates — server-side rendering, cache_size=0\ndb_validator — ORM vs DB schema check + auto-fix on startup',
      tech:'Python 3.13\nFastAPI + Uvicorn\nSlowAPI / Jinja2\npasslib[bcrypt] / python-jose' },
    { name:'LAYER 4: BUSINESS LOGIC (38 ROUTERS)', bg:C.lYellow, fg:C.gold,
      comp:'Auth | Dashboard | Admin | IQC | Stock | Repair | QC\nSales | Dealers | Accounts | Reports | Spare Parts\nCosmetic | Devices | GRN | Transfers | Attendance\nTelecalling | WhatsApp | Market | Locations | Stage Control\nBulk Upload | Invoices | Settings | QA/UAT\nCRM: dashboard, contacts, sourcing, sales, quotes, activities, price_matrix, purchase_orders, reports',
      tech:'38 router files\n270 HTTP routes\nAll routes: JWT auth + CSRF verified\nPython async/await throughout' },
    { name:'LAYER 3: DATA ACCESS (ORM)', bg:C.lBlue, fg:C.navy,
      comp:'SQLAlchemy 2.0 async ORM — all queries use async Session\nasync Session factory — get_db() dependency injected\nAlembic migrations (partial — db_validator covers runtime auto-fix)\n55 ORM models across 13 bounded contexts\nSoft-delete pattern: is_active / deleted_at where applicable',
      tech:'SQLAlchemy 2.0 (async)\nasyncpg 0.29\nAlembic (partial coverage)' },
    { name:'LAYER 2: DATABASE', bg:C.lPurp, fg:C.purple,
      comp:'PostgreSQL 15 — local install, port 5432, DB: oxypc_db\n55 tables | UUID PKs | Soft delete | Stage FSM enforced\naudit_logs (append-only, RBAC-protected)\nstage_movements (immutable history)\nBackup: pg_dump nightly via backup_db.py (gzip, keep 30)',
      tech:'PostgreSQL 15\nasyncpg\npg_dump for backup\nNo pgvector yet (Sprint 24+)' },
    { name:'LAYER 1: INTEGRATIONS / EXTERNAL', bg:C.lRed, fg:C.red,
      comp:'WhatsApp Service: Node.js wa-service using Baileys library\n  → Exposes REST API on localhost for sending messages\nFile System: /static, /backups, /logs directories on server\nNone: No cloud services, no external SaaS, no AI APIs yet\nFuture planned: SMS gateway, Email, GST portal, Tally export',
      tech:'Node.js 22 + Baileys\n(WhatsApp Web API)\nLocal file system\nNo external cloud' },
  ];

  return [
    h1('5. System Architecture Diagram'),
    p('7-layer architecture stack for OxyPC ERP. All layers run on a single Windows server (internal LAN deployment). No cloud dependency — fully air-gapped capable.'),
    sp(180),
    new Table({ width:{size:CW,type:WidthType.DXA}, columnWidths:[c1,c2,c3], rows:[
      new TableRow({ children:[ hCell('Layer',c1,C.navy), hCell('Components & Description',c2,C.navy), hCell('Technology',c3,C.navy) ]}),
      ...layers.map(l => new TableRow({ children:[
        dCell(l.name, c1, l.bg, l.fg, AlignmentType.LEFT, 14, true),
        dCell(l.comp, c2, C.white, '333333', AlignmentType.LEFT, 13),
        dCell(l.tech, c3, C.lGray, C.dgray, AlignmentType.LEFT, 13),
      ]})),
    ]}),
    sp(200),
    p('REQUEST FLOW:', 18, C.navy, true),
    p('Browser → Uvicorn (ASGI, 4 workers) → FastAPI Router → JWT Auth Check + CSRF Verify → Async ORM Query → PostgreSQL 15 → Jinja2 Template Render → HTML Response → Browser', 17, C.dgray),
    pb(),
  ];
}

// ═══════════════════════════════════════════════════════════════════════════════
// 6. API MAPPING
// ═══════════════════════════════════════════════════════════════════════════════
function apiMapping() {
  const c1=Math.round(CW*0.05), c2=Math.round(CW*0.28), c3=Math.round(CW*0.08), c4=CW-c1-c2-c3;
  const mc = {
    GET:    {bg:'E2EFDA',fg:'375623'}, POST:  {bg:'FCE4D6',fg:'843C0C'},
    PUT:    {bg:'FFF2CC',fg:'7F6000'}, DELETE:{bg:'FFE2E2',fg:'8B0000'},
    PATCH:  {bg:'E9D7F5',fg:'4B1C6D'},
  };
  function ar(method, path, auth, desc) {
    const m = mc[method]||{bg:'F0F0F0',fg:'333333'};
    return new TableRow({ children:[
      dCell(method, c1, m.bg, m.fg, AlignmentType.CENTER, 13, true),
      dCell(path,   c2, C.lGray, C.navy, AlignmentType.LEFT, 13, true),
      dCell(auth,   c3, auth==='Open'?C.lGreen:C.lBlue, auth==='Open'?C.green:C.navy, AlignmentType.CENTER, 12),
      dCell(desc,   c4, C.white, '333333', AlignmentType.LEFT, 14),
    ]});
  }
  const sh = (title) => secHeader(title, C.blue, 4);

  return [
    h1('6. API Mapping'),
    p('All 270 HTTP routes across 38 router modules. Auth: Open = no login | Auth = login required | Admin = admin only | InvMgr = Inventory Manager | Sales = sales roles'),
    sp(180),
    new Table({ width:{size:CW,type:WidthType.DXA}, columnWidths:[c1,c2,c3,c4], rows:[
      new TableRow({ children:[ hCell('Method',c1,C.navy), hCell('Path',c2,C.navy), hCell('Auth',c3,C.navy), hCell('Description',c4,C.navy) ]}),

      sh('AUTH — /auth'),
      ar('GET',  '/auth/login',  'Open', 'Show login page'),
      ar('POST', '/auth/login',  'Open', 'Authenticate user — rate limited 30/min — sets JWT + CSRF cookies'),
      ar('POST', '/auth/logout', 'Auth', 'Clear authentication cookies and redirect to login'),

      sh('DASHBOARD'),
      ar('GET', '/', 'Auth', 'Main dashboard — role-based KPIs, device stage pipeline, outstanding amounts'),

      sh('ADMIN — /admin'),
      ar('GET',  '/admin/users',                     'Admin', 'List all system users'),
      ar('GET',  '/admin/users/new',                 'Admin', 'New user creation form'),
      ar('POST', '/admin/users/new',                 'Admin', 'Create new user account'),
      ar('GET',  '/admin/users/{id}/edit',           'Admin', 'Edit user form'),
      ar('POST', '/admin/users/{id}/edit',           'Admin', 'Update user details (name, role, status)'),
      ar('POST', '/admin/users/{id}/reset-password', 'Admin', 'Reset user password'),
      ar('GET',  '/admin/users/{id}/permissions',    'Admin', 'Fine-grained permission editor'),
      ar('POST', '/admin/users/{id}/permissions',    'Admin', 'Save custom permission overrides'),
      ar('GET',  '/admin/login-log',                 'Admin', 'View all login/logout events with IP'),
      ar('GET',  '/admin/audit-log',                 'Admin', 'Audit log with table/action/user filtering and pagination'),

      sh('IQC — /iqc'),
      ar('GET',  '/iqc',                       'Auth',   'List IQC inspections with lot/status filter'),
      ar('GET',  '/iqc/new',                   'Auth',   'IQC entry form — 65 inspection parameters'),
      ar('POST', '/iqc/submit',                'Auth',   'Submit IQC — updates device stage (PASS/FAIL/PNA)'),
      ar('GET',  '/iqc/api/lot-line-item/{id}','Auth',   'JSON: fetch lot line item specs for auto-fill'),

      sh('DEVICES — /devices'),
      ar('GET',  '/devices',                'Auth',   'Global inventory search — barcode, stage, lot, grade, category filters'),
      ar('GET',  '/devices/export',         'Auth',   'Export filtered device list as CSV'),
      ar('GET',  '/devices/{barcode}',      'Auth',   'Full device profile — stage history, repair jobs, QC checks, location'),
      ar('GET',  '/devices/{barcode}/edit', 'InvMgr', 'Device spec edit form'),
      ar('POST', '/devices/{barcode}/edit', 'InvMgr', 'Save device spec changes (audited in audit_logs)'),

      sh('STOCK & LOTS — /stock, /lots'),
      ar('GET',  '/stock',           'Auth',   'Stock overview — device counts per stage'),
      ar('GET',  '/lots',            'Auth',   'All purchase lots with device counts and P&L'),
      ar('GET',  '/lots/new',        'InvMgr', 'New lot entry form with line items'),
      ar('POST', '/lots/new',        'InvMgr', 'Create lot with line items'),
      ar('GET',  '/lots/{id}',       'Auth',   'Lot detail — devices, P&L, line items'),
      ar('GET',  '/lots/{id}/edit',  'InvMgr', 'Edit lot form'),
      ar('POST', '/lots/{id}/edit',  'InvMgr', 'Update lot details'),

      sh('GRN — /grn'),
      ar('GET',  '/grn',        'InvMgr', 'GRN list'),
      ar('GET',  '/grn/new',    'InvMgr', 'GRN submission form'),
      ar('POST', '/grn/submit', 'InvMgr', 'Submit GRN — auto-creates device barcodes from lot line items'),

      sh('REPAIR — /repair'),
      ar('GET',  '/repair/l1',        'Auth', 'L1 repair queue — devices assigned to L1 engineers'),
      ar('GET',  '/repair/l2',        'Auth', 'L2 repair queue'),
      ar('GET',  '/repair/l3',        'Auth', 'L3/L4 escalation queue'),
      ar('POST', '/repair/start',     'Auth', 'Start repair job — assigns engineer, opens job record'),
      ar('POST', '/repair/complete',  'Auth', 'Complete repair — logs outcome, moves device to QC or Scrap'),
      ar('GET',  '/repair/move/form', 'Auth', 'Move device between repair levels form'),
      ar('POST', '/repair/move',      'Auth', 'Move device — updates repair job stage'),

      sh('QC — /qc'),
      ar('GET',  '/qc',        'Auth', 'QC assignment queue'),
      ar('GET',  '/qc/new',    'Auth', 'QC check form — score-based grading (Battery/Screen/Keyboard/Body)'),
      ar('POST', '/qc/submit', 'Auth', 'Submit QC — updates grade, moves to Cosmetic or back to Repair'),

      sh('COSMETIC — /cosmetic'),
      ar('GET',  '/cosmetic',                 'InvMgr', 'Cosmetic pipeline dashboard — counts per sub-stage'),
      ar('GET',  '/cosmetic/{stage}',         'InvMgr', 'Device list at specific cosmetic stage (cleaning/painting/final_qc)'),
      ar('POST', '/cosmetic/advance',         'InvMgr', 'Advance device to next cosmetic stage'),
      ar('POST', '/cosmetic/send-to-cosmetic','InvMgr', 'Send QC-passed device to Cleaning stage'),

      sh('SALES — /sales'),
      ar('GET',  '/sales',              'Auth',  'All sales with date/grade/user filtering'),
      ar('GET',  '/sales/ready',        'Auth',  'Devices at stage=sales, ready to be sold'),
      ar('GET',  '/sales/new',          'Sales', 'New sale form — barcode scan entry'),
      ar('POST', '/sales/new',          'Sales', 'Create sale — moves device to sold, books revenue'),
      ar('GET',  '/invoices/print/{id}','Sales', 'Print GST invoice (no sidebar, print-ready layout)'),
      ar('GET',  '/returns',            'Auth',  'Returns list'),
      ar('POST', '/sales/return',       'Sales', 'Process return — device re-enters inventory at appropriate stage'),

      sh('DEALERS — /dealers'),
      ar('GET',  '/dealers',                              'Auth',  'Dealer list with search, filter, pagination'),
      ar('GET',  '/dealers/ageing',                       'Sales', 'Dealer ageing analysis — overdue by age bucket (30/60/90/90+ days)'),
      ar('GET',  '/dealers/overdue',                      'Sales', 'Orders overdue for payment'),
      ar('GET',  '/dealers/followups-due',                'Auth',  'Dealers with overdue call follow-ups'),
      ar('GET',  '/dealers/new',                          'Auth',  'New dealer form'),
      ar('POST', '/dealers/new',                          'Auth',  'Create dealer account'),
      ar('GET',  '/dealers/{id}',                         'Auth',  'Dealer profile — orders, call log, outstanding balance'),
      ar('GET',  '/dealers/{id}/ledger',                  'Sales', 'Full dealer transaction ledger'),
      ar('GET',  '/dealers/{id}/orders/new',              'Sales', 'New dealer order form'),
      ar('POST', '/dealers/{id}/orders/new',              'Sales', 'Create dealer order (adds to outstanding_amount)'),
      ar('POST', '/dealers/{id}/orders/{oid}/pay',        'Sales', 'Record payment — decrements due_amount'),
      ar('POST', '/dealers/{id}/orders/{oid}/credit-note','Sales', 'Create credit note for order'),
      ar('POST', '/dealers/{id}/credit-notes/{cn_id}/apply','Sales','Apply credit note to reduce order due_amount'),
      ar('GET',  '/dealers/{id}/orders/{oid}/invoice',    'Sales', 'Generate GST invoice for dealer order'),
      ar('GET',  '/dealers/{id}/statement.csv',           'Sales', 'Download dealer account statement as CSV'),
      ar('GET',  '/dealers/{id}/edit',                    'Auth',  'Edit dealer form'),
      ar('POST', '/dealers/{id}/edit',                    'Auth',  'Update dealer details'),
      ar('GET',  '/dealers/{id}/call',                    'Auth',  'Log call with dealer form'),
      ar('POST', '/dealers/{id}/call',                    'Auth',  'Submit call log'),

      sh('CRM — /crm'),
      ar('GET',  '/crm/',                              'Auth',  'CRM dashboard — pipeline KPIs, follow-ups due'),
      ar('GET',  '/crm/contacts',                      'Auth',  'Contact list with type/status filtering'),
      ar('GET',  '/crm/contacts/new',                  'Auth',  'New contact form'),
      ar('POST', '/crm/contacts/new',                  'Auth',  'Create CRM contact'),
      ar('GET',  '/crm/contacts/{id}',                 'Auth',  'Contact profile with full activity history'),
      ar('GET',  '/crm/contacts/{id}/edit',            'Auth',  'Edit contact form'),
      ar('POST', '/crm/contacts/{id}/edit',            'Auth',  'Update contact details'),
      ar('GET',  '/crm/contacts/import-csv',           'Auth',  'CSV import form for bulk contact upload'),
      ar('POST', '/crm/contacts/import-csv',           'Auth',  'Preview CSV import — duplicate check'),
      ar('POST', '/crm/contacts/import-confirm',       'Auth',  'Confirm and execute bulk contact import'),
      ar('GET',  '/crm/sourcing',                      'Auth',  'Sourcing deal pipeline with stage metrics'),
      ar('GET',  '/crm/sourcing/new',                  'Auth',  'New sourcing deal form'),
      ar('POST', '/crm/sourcing/new',                  'Auth',  'Create sourcing deal'),
      ar('GET',  '/crm/sourcing/{id}',                 'Auth',  'Sourcing deal detail with activity log'),
      ar('POST', '/crm/sourcing/{id}/stage',           'Auth',  'Move deal to new stage'),
      ar('POST', '/crm/sourcing/{id}/link-lot',        'Auth',  'Link lot to deal (marks deal as won)'),
      ar('GET',  '/crm/sales',                         'Auth',  'Sales opportunity pipeline'),
      ar('GET',  '/crm/sales/new',                     'Auth',  'New sales opportunity form'),
      ar('POST', '/crm/sales/new',                     'Auth',  'Create sales opportunity'),
      ar('GET',  '/crm/sales/{id}',                    'Auth',  'Opportunity detail with activities'),
      ar('POST', '/crm/sales/{id}/stage',              'Auth',  'Move opportunity to new stage'),
      ar('POST', '/crm/sales/{id}/link-sale',          'Auth',  'Link actual sale records to opportunity'),
      ar('GET',  '/crm/quotes',                        'Auth',  'Quote list with status filter'),
      ar('GET',  '/crm/quotes/new',                    'Auth',  'New quote form with line items'),
      ar('POST', '/crm/quotes/new',                    'Auth',  'Create quote'),
      ar('GET',  '/crm/quotes/{id}',                   'Auth',  'Quote detail'),
      ar('GET',  '/crm/quotes/{id}/print',             'Auth',  'Print-ready quote (no sidebar)'),
      ar('POST', '/crm/quotes/{id}/status',            'Auth',  'Update quote status (draft/sent/accepted/rejected)'),
      ar('GET',  '/crm/purchase-orders',               'Auth',  'Purchase orders list'),
      ar('GET',  '/crm/purchase-orders/new',           'Sales', 'New PO form'),
      ar('POST', '/crm/purchase-orders/new',           'Sales', 'Create purchase order'),
      ar('GET',  '/crm/purchase-orders/{id}',          'Auth',  'PO detail'),
      ar('POST', '/crm/purchase-orders/{id}/issue',    'Sales', 'Issue/finalize PO'),
      ar('GET',  '/crm/purchase-orders/{id}/print',    'Auth',  'Print-ready PO'),
      ar('POST', '/crm/activities/log',                'Auth',  'Log call/visit/WhatsApp/note activity'),
      ar('POST', '/crm/activities/{id}/done',          'Auth',  'Mark follow-up as completed'),
      ar('GET',  '/crm/activities/followups',          'Auth',  'All overdue and upcoming follow-ups'),
      ar('GET',  '/crm/price-matrix',                  'Auth',  'Grade-based price benchmarks (buy/sell/margin)'),
      ar('GET',  '/crm/price-matrix/new',              'Sales', 'New price matrix row form'),
      ar('POST', '/crm/price-matrix/new',              'Sales', 'Create price matrix row'),
      ar('GET',  '/crm/price-matrix/{id}/edit',        'Sales', 'Edit price matrix row'),
      ar('POST', '/crm/price-matrix/{id}/edit',        'Sales', 'Update price matrix row'),
      ar('POST', '/crm/price-matrix/{id}/delete',      'Sales', 'Delete price matrix row'),
      ar('GET',  '/crm/reports',                       'Auth',  'CRM analytics hub — win rates, pipeline health'),
      ar('GET',  '/crm/reports/funnel',                'Auth',  'Pipeline funnel (sourcing or sales)'),
      ar('GET',  '/crm/reports/win-loss',              'Auth',  'Win/loss analysis by source and user'),
      ar('GET',  '/crm/reports/activity-leaderboard',  'Auth',  'Agent activity leaderboard (calls/visits/emails)'),

      sh('ACCOUNTS — /accounts'),
      ar('GET',  '/accounts',                         'Auth', 'Accounts overview — payment and receipt totals'),
      ar('GET',  '/accounts/supplier-payments',       'Auth', 'Supplier payment list by contact'),
      ar('POST', '/accounts/supplier-payments/new',   'Auth', 'Record supplier payment'),
      ar('GET',  '/accounts/customer-receipts',       'Auth', 'Customer receipt list'),
      ar('POST', '/accounts/customer-receipts/new',   'Auth', 'Record customer receipt'),

      sh('SPARE PARTS — /spare-parts'),
      ar('GET',  '/spare-parts',           'Auth',   'Spare parts inventory — low stock highlighted in red'),
      ar('GET',  '/spare-parts/new',       'InvMgr', 'Add new spare part form'),
      ar('POST', '/spare-parts/new',       'InvMgr', 'Create spare part'),
      ar('GET',  '/spare-parts/{id}/edit', 'InvMgr', 'Edit spare part'),
      ar('POST', '/spare-parts/{id}/edit', 'InvMgr', 'Update spare part details'),
      ar('POST', '/spare-parts/consume',   'Auth',   'Record parts usage against device/repair job'),
      ar('POST', '/spare-parts/purchase',  'InvMgr', 'Record spare parts purchase from vendor'),
      ar('GET',  '/ram-tracking',          'Auth',   'RAM swap / removal tracking log'),

      sh('REPORTS — /reports'),
      ar('GET', '/reports/lot-pl',         'Auth', 'Lot P&L — buying cost vs sale revenue per lot'),
      ar('GET', '/reports/sales',          'Auth', 'Sales report with date/grade/user/channel filters'),
      ar('GET', '/reports/business-pl',    'Auth', 'Annual business P&L — monthly breakdown'),
      ar('GET', '/reports/stock-aging',    'Auth', 'Stock aging — days device has been in current stage'),
      ar('GET', '/reports/receivables',    'Auth', 'Receivables ageing — dealer outstanding by 30/60/90/90+ days'),
      ar('GET', '/reports/stage-movement', 'Auth', 'Full stage transition log with timeline'),

      sh('ATTENDANCE — /attendance'),
      ar('GET',  '/attendance',          'Auth',  'Today\'s attendance list for all users'),
      ar('POST', '/attendance/checkin',  'Auth',  'Record check-in (captures client IP for geofencing)'),
      ar('POST', '/attendance/checkout', 'Auth',  'Record check-out'),
      ar('GET',  '/attendance/history',  'Auth',  'Personal monthly calendar view'),
      ar('GET',  '/attendance/report',   'Admin', 'Full attendance report with date range + CSV export'),
      ar('POST', '/attendance/mark',     'Admin', 'Admin marks attendance manually for any user'),

      sh('LOCATIONS — /locations'),
      ar('GET',  '/locations/dashboard',          'Auth',   'Location dashboard — zone-based device map'),
      ar('GET',  '/locations/device/{id}',        'Auth',   'Device location detail and assignment'),
      ar('POST', '/locations/device/{id}/assign', 'InvMgr', 'Assign device to storage location'),
      ar('GET',  '/locations/gaps',               'InvMgr', 'Devices without a location assignment'),
      ar('GET',  '/locations/master',             'InvMgr', 'Manage storage locations (CRUD)'),
      ar('GET',  '/locations/audit',              'InvMgr', 'Physical audit sessions list'),
      ar('GET',  '/locations/audit/{id}',         'InvMgr', 'Audit session detail — scan results and discrepancies'),

      sh('TRANSFERS, BULK UPLOAD, WHATSAPP, MARKET, QA — miscellaneous'),
      ar('GET',  '/transfers',               'Auth',   'Stock transfer list'),
      ar('GET',  '/transfers/new',           'InvMgr', 'New stock transfer form'),
      ar('POST', '/transfers/new',           'InvMgr', 'Create stock transfer between warehouses'),
      ar('GET',  '/bulk-upload',             'InvMgr', 'Bulk upload interface (lots/devices/leads/spare parts)'),
      ar('GET',  '/bulk-upload/template/{t}','Auth',   'Download CSV template for a given upload type'),
      ar('POST', '/bulk-upload/lots',        'InvMgr', 'Bulk upload lots from CSV'),
      ar('POST', '/bulk-upload/devices',     'InvMgr', 'Bulk upload devices from CSV'),
      ar('POST', '/bulk-upload/spare-parts', 'InvMgr', 'Bulk upload spare parts from CSV'),
      ar('POST', '/bulk-upload/leads',       'Auth',   'Bulk upload telecalling leads from CSV'),
      ar('GET',  '/whatsapp',                'Auth',   'WhatsApp compose and group management'),
      ar('POST', '/whatsapp/send',           'Auth',   'Send WhatsApp message via wa-service (Node.js Baileys)'),
      ar('GET',  '/whatsapp/audit',          'Auth',   'WhatsApp message audit log'),
      ar('GET',  '/market',                  'Auth',   'Market availability intelligence (buy/sell listings)'),
      ar('GET',  '/stage-control',           'Admin',  'Stage transition rules management (FSM config)'),
      ar('GET',  '/stage-control/aging',     'Admin',  'Aging dashboard — devices stuck in stage'),
      ar('GET',  '/stage-control/audit',     'Admin',  'Stage control audit log'),
      ar('GET',  '/telecalling',             'Auth',   'Telecalling dashboard and records'),
      ar('POST', '/telecalling/add',         'Auth',   'Log a telecalling record'),
      ar('GET',  '/telecalling/records',     'Auth',   'Telecalling records with outcome filter'),
      ar('GET',  '/qa/',                     'Auth',   'QA/UAT dashboard — requirements, defects, releases'),
      ar('GET',  '/qa/requirements',         'Auth',   'Requirements list — CRUD'),
      ar('GET',  '/qa/test-cases',           'Auth',   'Test cases linked to requirements'),
      ar('GET',  '/qa/defects',              'Auth',   'Defect tracker — severity/priority/status'),
      ar('GET',  '/qa/uat',                  'Auth',   'UAT board — business sign-off tracking'),
      ar('GET',  '/qa/releases',             'Auth',   'Release versions and deploy tracking'),
      ar('GET',  '/qa/rtm',                  'Auth',   'Requirements Traceability Matrix'),
      ar('GET',  '/settings',                'Admin',  'Company settings — name, address, GSTIN, logo'),
      ar('GET',  '/health',                  'Open',   'Health check endpoint — returns DB connectivity status as JSON'),
    ]}),
    pb(),
  ];
}

// ═══════════════════════════════════════════════════════════════════════════════
// 7. UI MAPPING
// ═══════════════════════════════════════════════════════════════════════════════
function uiMapping() {
  const c1=Math.round(CW*0.11), c2=Math.round(CW*0.20), c3=Math.round(CW*0.22);
  const c4=Math.round(CW*0.11), c5=CW-c1-c2-c3-c4;

  function ur(module, page, url, roles, links, bg=C.white) {
    return new TableRow({ children:[
      dCell(module, c1, bg, C.navy, AlignmentType.LEFT, 14, !!module),
      dCell(page,   c2, bg, '000000', AlignmentType.LEFT, 14, true),
      dCell(url,    c3, C.lGray, C.navy, AlignmentType.LEFT, 13),
      dCell(roles,  c4, C.lBlue, C.navy, AlignmentType.LEFT, 12),
      dCell(links,  c5, C.white, '444444', AlignmentType.LEFT, 13),
    ]});
  }
  const mh = (t) => secHeader(t, C.blue, 5);

  return [
    h1('7. UI Mapping'),
    p('Complete screen inventory — 130+ pages across 26 modules. Shows URL path, role access, and cross-page navigation links.'),
    sp(180),
    new Table({ width:{size:CW,type:WidthType.DXA}, columnWidths:[c1,c2,c3,c4,c5], rows:[
      new TableRow({ children:[ hCell('Module',c1,C.navy), hCell('Page Name',c2,C.navy), hCell('URL Path',c3,C.navy), hCell('Roles',c4,C.navy), hCell('Links To / Navigation',c5,C.navy) ]}),

      mh('AUTH'),
      ur('Auth','Login','/auth/login','Public','POST /auth/login → Dashboard (/)'),

      mh('DASHBOARD'),
      ur('Dashboard','Main Dashboard','/','All Roles','All module entry points (role-filtered sidebar nav)'),

      mh('ADMIN'),
      ur('Admin','User List','/admin/users','Admin','/admin/users/new, /{id}/edit, /{id}/permissions, /{id}/reset-password'),
      ur('','New/Edit User','/admin/users/new | /{id}/edit','Admin','→ /admin/users (back on save)'),
      ur('','User Permissions','/admin/users/{id}/permissions','Admin','→ /admin/users'),
      ur('','Login Log','/admin/login-log','Admin','→ /admin'),
      ur('','Audit Log','/admin/audit-log','Admin','Filter by table/action/user — → /admin'),
      ur('','Company Settings','/settings','Admin','Save company name, address, GSTIN, logo'),

      mh('INTAKE — GRN / LOTS / IQC'),
      ur('Intake','Lots List','/lots','InvMgr','→ /lots/new, /{id}, /grn/new, /bulk-upload'),
      ur('','New/Edit Lot','/lots/new | /{id}/edit','InvMgr','→ /lots (back on save)'),
      ur('','Lot Detail','/lots/{id}','InvMgr','→ /lots/{id}/edit, /grn/new, /devices?lot={id}'),
      ur('','GRN List','/grn','InvMgr','→ /grn/new'),
      ur('','Submit GRN','/grn/new','InvMgr','POST /grn/submit — auto-creates device barcodes → /grn'),
      ur('','IQC List','/iqc','IQC/InvMgr','→ /iqc/new, filter by lot number'),
      ur('','IQC Form','/iqc/new','IQC/InvMgr','65 parameters → Stage: IQC→Stock or Repair or Scrap → /iqc'),

      mh('DEVICES & INVENTORY'),
      ur('Devices','Inventory Search','/devices','All Roles','→ /devices/{barcode}, /devices/export, /sales/new?barcode={}'),
      ur('','Device Detail','/devices/{barcode}','All Roles','→ /{barcode}/edit, /locations/device/{id}, /qc/new, /sales/new'),
      ur('','Device Edit','/devices/{barcode}/edit','InvMgr','→ /devices/{barcode} (back on save)'),
      ur('','Bulk Upload','/bulk-upload','InvMgr','→ /bulk-upload/template/{type} (CSV template download)'),

      mh('REPAIR'),
      ur('Repair','L1 Queue','/repair/l1','Engineer/Admin','POST /repair/start, POST /repair/complete'),
      ur('','L2 Queue','/repair/l2','Engineer/Admin','POST /repair/start, POST /repair/complete'),
      ur('','L3/L4 Queue','/repair/l3','Engineer/Admin','POST /repair/complete (scrap or L4 escalation)'),
      ur('','Move Device','/repair/move/form','Engineer/Admin','POST /repair/move → stage updated'),

      mh('QC CHECK'),
      ur('QC','QC Queue','/qc','QC Inspector/Admin','→ /qc/new'),
      ur('','QC Form','/qc/new','QC Inspector','Score entry → PASS→Cosmetic / FAIL→Repair / Scrap'),

      mh('COSMETIC REFURBISHMENT'),
      ur('Cosmetic','Pipeline Dashboard','/cosmetic','InvMgr','→ /cosmetic/cleaning, /cosmetic/painting, /cosmetic/final_qc'),
      ur('','Stage List','/cosmetic/{stage}','InvMgr','POST /cosmetic/advance → moves to next sub-stage'),

      mh('SALES'),
      ur('Sales','Sales List','/sales','Sales/Admin','→ /sales/new, /invoices/print/{id}'),
      ur('','Ready to Sale','/sales/ready','Sales','→ /sales/new?barcode={barcode}'),
      ur('','New Sale','/sales/new','Sales','POST /sales/new → device marked SOLD → /sales'),
      ur('','Returns List','/returns','Sales/Admin','→ /sales/return_form'),
      ur('','Return Form','/sales/return_form','Sales','POST /sales/return → device re-enters stock → /returns'),
      ur('','Invoice Print','/invoices/print/{id}','Sales','Print-only layout (no sidebar) — browser print dialog'),

      mh('DEALERS'),
      ur('Dealers','Dealer List','/dealers','Sales/Admin','→ /dealers/new, /{id}, /{id}/edit, /dealers/ageing, /dealers/overdue'),
      ur('','Dealer Profile','/dealers/{id}','Sales/Admin','→ /{id}/edit, /{id}/ledger, /{id}/orders/new, /whatsapp/compose'),
      ur('','Dealer Ledger','/dealers/{id}/ledger','Sales Mgr','→ /dealers/{id}'),
      ur('','New Order','/dealers/{id}/orders/new','Sales','POST /dealers/{id}/orders/new → /dealers/{id}'),
      ur('','Dealer Ageing','/dealers/ageing','Sales','30/60/90/90+ day buckets — CSV export available'),
      ur('','Overdue Orders','/dealers/overdue','Sales','→ /dealers'),
      ur('','Follow-ups Due','/dealers/followups-due','Sales','→ /dealers/{id}/call (to log follow-up)'),

      mh('CRM'),
      ur('CRM','CRM Dashboard','/crm/','Sales/CRM','→ /crm/contacts, /crm/sourcing, /crm/sales, /crm/activities/followups'),
      ur('','Contacts List','/crm/contacts','All','→ /crm/contacts/new, /{id}, /crm/sales/new?contact_id={}'),
      ur('','Contact Profile','/crm/contacts/{id}','All','→ /{id}/edit, /crm/sales/new, /crm/sourcing/new'),
      ur('','Contact Import','/crm/contacts/import-csv','All','CSV → duplicate preview → confirm import'),
      ur('','Sourcing Deals','/crm/sourcing','Sales/CRM','→ /new, /{id}, /{id}/edit, /{id}/link-lot'),
      ur('','Sourcing Deal','/crm/sourcing/{id}','Sales/CRM','→ /edit, /crm/quotes/new?opp_id={}, /lots/new?from_deal={}'),
      ur('','Sales Opportunities','/crm/sales','Sales/CRM','→ /new, /{id}, /{id}/edit, /{id}/link-sale'),
      ur('','Opportunity Detail','/crm/sales/{id}','Sales/CRM','→ /edit, /{id}/link-sale, /crm/quotes/new'),
      ur('','Quotes','/crm/quotes','Sales/CRM','→ /new, /{id}, /{id}/print'),
      ur('','Purchase Orders','/crm/purchase-orders','Sales/CRM','→ /new, /{id}, /{id}/print, /{id}/issue'),
      ur('','Follow-ups','/crm/activities/followups','Sales/CRM','→ /crm/sales/{id} or /crm/sourcing/{id}'),
      ur('','Price Matrix','/crm/price-matrix','Sales/Admin','→ /new, /{id}/edit, /{id}/delete'),
      ur('','CRM Reports','/crm/reports','Sales/Admin','→ /funnel, /win-loss, /activity-leaderboard'),

      mh('ACCOUNTS'),
      ur('Accounts','Accounts Overview','/accounts','Finance/Admin','→ /accounts/supplier-payments, /accounts/customer-receipts'),
      ur('','Supplier Payments','/accounts/supplier-payments','Finance/Admin','POST /new → record payment → /accounts'),
      ur('','Customer Receipts','/accounts/customer-receipts','Finance/Admin','POST /new → record receipt → /accounts'),

      mh('SPARE PARTS'),
      ur('Spare Parts','Parts List','/spare-parts','Engineer/Admin','→ /new, /{id}/edit, /consume, /purchase, /ram-tracking'),
      ur('','Consume Parts','/spare-parts/consume','Engineer','POST → decrements qty_in_stock → /spare-parts'),
      ur('','Purchase Parts','/spare-parts/purchase','InvMgr','POST → increments qty_in_stock → /spare-parts'),
      ur('','RAM Tracking','/ram-tracking','Engineer/Admin','RAM swap / removal log → /spare-parts'),

      mh('REPORTS'),
      ur('Reports','Lot P&L','/reports/lot-pl','Admin/Mgr','CSV export — buying cost vs sale revenue per lot'),
      ur('','Sales Report','/reports/sales','Sales/Admin','Date/grade/user filters + CSV export'),
      ur('','Business P&L','/reports/business-pl','Admin','Annual monthly P&L breakdown'),
      ur('','Stock Aging','/reports/stock-aging','InvMgr/Admin','Days device in current stage — highlights stuck devices'),
      ur('','Receivables Ageing','/reports/receivables','Sales Mgr','Dealer outstanding 30/60/90/90+ day buckets'),

      mh('LOCATIONS'),
      ur('Locations','Location Dashboard','/locations/dashboard','InvMgr','→ /locations/master, /locations/gaps, /locations/audit'),
      ur('','Device Location','/locations/device/{id}','All','Assign device to storage zone/slot'),
      ur('','Location Gaps','/locations/gaps','InvMgr','Devices without location → assign from here'),
      ur('','Audit Sessions','/locations/audit','InvMgr','→ /locations/audit/{id} (scan results and discrepancies)'),

      mh('ATTENDANCE'),
      ur('Attendance','Today\'s Attendance','/attendance','All','POST /attendance/checkin|checkout, → /attendance/history'),
      ur('','History Calendar','/attendance/history','All','Monthly calendar → /attendance'),
      ur('','Attendance Report','/attendance/report','Admin','Date range filter + CSV export'),

      mh('COMMUNICATION'),
      ur('WhatsApp','Compose & Groups','/whatsapp','Sales/Admin','→ /whatsapp/compose?dealer_id={}, /whatsapp/audit'),
      ur('Telecalling','Call Dashboard','/telecalling','Sales','→ /telecalling/add, /telecalling/records'),
      ur('','Log Call','/telecalling/add','Sales','Pre-fill from dealer → POST → /telecalling'),

      mh('MARKET & STAGE CONTROL'),
      ur('Market','Market Intelligence','/market','Sales/Admin','Edit market availability entries'),
      ur('Stage Ctrl','Stage Rules','/stage-control','Admin','FSM transition rules → /stage-control/aging, /audit'),

      mh('QA / UAT'),
      ur('QA/UAT','QA Dashboard','/qa/','All','→ /qa/requirements, /qa/test-cases, /qa/defects, /qa/uat, /qa/releases, /qa/rtm'),
      ur('','Requirements','/qa/requirements','All','CRUD for requirements linked to test cases'),
      ur('','Test Cases','/qa/test-cases','All','Linked to requirements, track automated vs manual'),
      ur('','Defect Tracker','/qa/defects','All','Severity/Priority/Status — full defect lifecycle'),
      ur('','UAT Board','/qa/uat','All','Business sign-off and acceptance criteria tracking'),
      ur('','Releases','/qa/releases','All','Version tracking — planned → in-progress → deployed'),
      ur('','RTM','/qa/rtm','All','Requirements Traceability Matrix — req ↔ test ↔ defect'),
    ]}),
    pb(),
  ];
}

// ═══════════════════════════════════════════════════════════════════════════════
// 8. AI LAYER
// ═══════════════════════════════════════════════════════════════════════════════
function aiLayer() {
  const c1=Math.round(CW*0.12), c2=Math.round(CW*0.20), c3=Math.round(CW*0.30);
  const c4=Math.round(CW*0.18), c5=CW-c1-c2-c3-c4;

  const features = [
    { sprint:'Sprint 19\n(Planned)', name:'Smart Auto-Recommendations\n(Rule-Based, no ML)',
      desc:'Based on IQC lot line item specs → auto-suggest Grade, repair level, expected sale price.\nBased on QC score → auto-suggest pass/fail, next stage.\nBased on repair history → auto-suggest L2 escalation.',
      data:'lot_line_items\niqc_inspections\nqc_checks\nrepair_jobs\ncrm_grade_price_matrix',
      status:'🟡 Planned', bg:C.lYellow, fg:C.gold },
    { sprint:'Sprint 21\n(Roadmap)', name:'Demand Forecasting\n(Statistical ML)',
      desc:'Predict which grades/models will sell in next 30/60/90 days based on sales history + market intel.\nFeed into sourcing deal price negotiation.\nAlert when inventory diverges from predicted demand.',
      data:'sales\nmarket_availability\ncrm_grade_price_matrix\ntelecalling_records',
      status:'🔵 Roadmap', bg:C.lBlue, fg:C.navy },
    { sprint:'Sprint 22\n(Roadmap)', name:'Price Optimization\n(ML Regression)',
      desc:'Dynamic pricing recommendations per device: age in stock, market price, grade, demand signal.\nRecommend floor price to avoid margin erosion.\nAlert when proposed sale price is below cost floor.',
      data:'device_costing\ndevice_aging\nmarket_availability\ncrm_grade_price_matrix\nsales',
      status:'🔵 Roadmap', bg:C.lBlue, fg:C.navy },
    { sprint:'Sprint 23\n(Roadmap)', name:'Repair Cost Predictor\n(ML Classification)',
      desc:'Based on IQC fault signature → predict expected repair cost, likely parts, repair duration.\nHelps engineers plan parts procurement.\nEstimates total device cost before pricing.',
      data:'iqc_inspections\nrepair_jobs\nrepair_attempts\nspare_parts_consumption',
      status:'🔵 Roadmap', bg:C.lBlue, fg:C.navy },
    { sprint:'Sprint 24\n(Roadmap)', name:'LLM Copilot\n(GPT-4 / Claude API)',
      desc:'Natural language queries: "Show all i5 Gen 10 laptops in repair > 7 days".\nAuto-draft WhatsApp payment reminders for overdue dealers.\nSummarise device history for sales team pitch.\nRAG over device/dealer history via pgvector.',
      data:'Read-only views on:\ndevices, repair_jobs\ndealer_calls\ncrm_activities\n(pgvector embeddings)',
      status:'🔵 Future', bg:C.lPurp, fg:C.purple },
    { sprint:'Sprint 25\n(Future)', name:'Computer Vision\nIQC Grading',
      desc:'Upload photos of device panels A/B/C/D and screen.\nAI auto-detects scratches, dents, cracks, colour fade.\nPre-fills IQC cosmetic parameters — reduces IQC time from 15 → 5 min.\nGrade suggested from visual analysis.',
      data:'iqc_inspections\ndevice_photos (new)\n/static/device_photos/\nImage storage on server',
      status:'🔵 Future', bg:C.lPurp, fg:C.purple },
  ];

  const archLayers = [
    { layer:'UI Layer',        bg:C.lBlue,
      desc:'Recommendation badges and auto-fill suggestion chips in Jinja2 templates. Confidence score shown. Human confirmation required before applying any AI suggestion. No AI output applied automatically.' },
    { layer:'API Layer',       bg:C.lGreen,
      desc:'New FastAPI endpoints: /api/recommend/grade, /api/recommend/price, /api/predict/repair-cost. All AI endpoints: JWT auth required, rate limited to 60/min, every call logged to audit_logs.' },
    { layer:'AI Service Layer',bg:C.lOrng,
      desc:'Python microservice (separate process, same server). Connects to read-only DB views only. No SQLAlchemy write sessions. Returns JSON recommendations to FastAPI. Isolated failure — main app continues if AI service is down.' },
    { layer:'Data Layer',      bg:C.lYellow,
      desc:'Read-only materialised views refreshed every 15 minutes. pgvector extension for LLM RAG. New tables: ai_recommendation_log, ai_model_versions, embeddings. AI tables are read-only to AI services, write-only from ETL jobs.' },
    { layer:'Security Gate',   bg:C.lRed,
      desc:'AI DB user: SELECT-only privileges. No AI service has INSERT/UPDATE/DELETE. All recommendations logged to ai_recommendation_log before display. Dedicated approval gate: every AI-suggested status change requires explicit user click.' },
  ];

  const newTables = [
    { name:'ai_recommendation_log', cols:'id, device_id, recommendation_type, input_features (JSON), recommendation (JSON), confidence_score, shown_to, shown_at, accepted (bool), acted_at' },
    { name:'ai_model_versions',     cols:'id, model_name, version, trained_on, accuracy_pct, deployed_at, is_active' },
    { name:'device_photos',         cols:'id, device_id, photo_type (panel_a/b/c/d/screen), file_path, uploaded_by, uploaded_at, ai_analysis (JSON)' },
    { name:'embeddings',            cols:'id, source_type, source_id, content_hash, embedding (vector 1536), created_at — requires pgvector extension' },
  ];

  const fw = Math.round(CW*0.22);

  return [
    h1('8. AI Layer'),
    p('OxyPC currently has ZERO AI/ML features in production. This diagram defines the planned AI architecture for Sprints 19–25.'),
    sp(120),
    p('CURRENT STATE: All recommendations are manual. Sprint 19 introduces the first rule-based (no ML) auto-suggest layer.', 18, C.red, true),
    sp(220),
    h2('AI Feature Roadmap'),
    new Table({ width:{size:CW,type:WidthType.DXA}, columnWidths:[c1,c2,c3,c4,c5], rows:[
      new TableRow({ children:[ hCell('Sprint',c1,C.navy), hCell('Feature',c2,C.navy), hCell('Description',c3,C.navy), hCell('Data Sources',c4,C.navy), hCell('Status',c5,C.navy) ]}),
      ...features.map(f => new TableRow({ children:[
        dCell(f.sprint, c1, f.bg, f.fg, AlignmentType.CENTER, 15, true),
        dCell(f.name,   c2, f.bg, f.fg, AlignmentType.LEFT,   15, true),
        dCell(f.desc,   c3, C.white, '333333', AlignmentType.LEFT, 13),
        dCell(f.data,   c4, C.lGray, C.navy,  AlignmentType.LEFT, 12),
        dCell(f.status, c5, f.bg, f.fg, AlignmentType.CENTER, 14, true),
      ]})),
    ]}),
    sp(280),
    h2('AI Architecture (Target State)'),
    new Table({ width:{size:CW,type:WidthType.DXA}, columnWidths:[Math.round(CW*0.16), CW-Math.round(CW*0.16)], rows:[
      new TableRow({ children:[ hCell('Layer', Math.round(CW*0.16), C.navy), hCell('Detail', CW-Math.round(CW*0.16), C.navy) ]}),
      ...archLayers.map(a => new TableRow({ children:[
        dCell(a.layer, Math.round(CW*0.16), a.bg, C.navy, AlignmentType.LEFT, 15, true),
        dCell(a.desc,  CW-Math.round(CW*0.16), C.white, '333333', AlignmentType.LEFT, 14),
      ]})),
    ]}),
    sp(280),
    h2('New DB Tables Required for AI'),
    new Table({ width:{size:CW,type:WidthType.DXA}, columnWidths:[fw, CW-fw], rows:[
      new TableRow({ children:[ hCell('Table', fw, C.navy), hCell('Key Columns', CW-fw, C.navy) ]}),
      ...newTables.map(t => new TableRow({ children:[
        dCell(t.name, fw, C.lPurp, C.purple, AlignmentType.LEFT, 14, true),
        dCell(t.cols, CW-fw, C.white, '333333', AlignmentType.LEFT, 13),
      ]})),
    ]}),
    sp(200),
    p('Design Principle: AI assists, humans decide. No AI recommendation is acted upon without explicit user confirmation. All AI activity is immutably logged in ai_recommendation_log.', 17, C.dgray, true),
  ];
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN DOCUMENT
// ═══════════════════════════════════════════════════════════════════════════════
async function build() {
  const doc = new Document({
    styles: {
      default: { document: { run: { font:'Arial', size:20 } } },
      paragraphStyles: [
        { id:'Heading1', name:'Heading 1', basedOn:'Normal', next:'Normal', quickFormat:true,
          run:{ size:38, bold:true, color:C.navy, font:'Arial' },
          paragraph:{ spacing:{before:400,after:200}, outlineLevel:0 } },
        { id:'Heading2', name:'Heading 2', basedOn:'Normal', next:'Normal', quickFormat:true,
          run:{ size:28, bold:true, color:C.blue, font:'Arial' },
          paragraph:{ spacing:{before:240,after:120}, outlineLevel:1 } },
      ],
    },
    sections:[{
      properties:{
        page:{
          size:{ width:PAGE_W, height:PAGE_H, orientation:PageOrientation.LANDSCAPE },
          margin:{ top:MARGIN, right:MARGIN, bottom:MARGIN, left:MARGIN },
        },
      },
      headers:{ default: new Header({ children:[
        new Paragraph({
          border:{ bottom:{ style:BorderStyle.SINGLE, size:4, color:C.blue } },
          tabStops:[{ type:TabStopType.RIGHT, position:CW }],
          children:[
            new TextRun({ text:'OxyPC Inventory ERP — Complete Diagram Reference', font:'Arial', size:18, color:C.navy, bold:true }),
            new TextRun({ text:'\tv1.0 — 27 April 2026', font:'Arial', size:16, color:C.dgray }),
          ],
        }),
      ]})},
      footers:{ default: new Footer({ children:[
        new Paragraph({
          border:{ top:{ style:BorderStyle.SINGLE, size:2, color:C.blue } },
          tabStops:[{ type:TabStopType.RIGHT, position:CW }],
          children:[
            new TextRun({ text:'OxyPC Confidential — Internal Use Only', font:'Arial', size:16, color:C.dgray }),
            new TextRun({ text:'\tPage ', font:'Arial', size:16 }),
            new TextRun({ children:[PageNumber.CURRENT], font:'Arial', size:16 }),
            new TextRun({ text:' of ', font:'Arial', size:16 }),
            new TextRun({ children:[PageNumber.TOTAL_PAGES], font:'Arial', size:16 }),
          ],
        }),
      ]})},
      children:[
        // ── COVER PAGE ──────────────────────────────────────────────────────
        sp(1800),
        new Paragraph({ alignment:AlignmentType.CENTER,
          children:[new TextRun({ text:'OxyPC INVENTORY ERP', font:'Arial', bold:true, size:80, color:C.navy })] }),
        new Paragraph({ alignment:AlignmentType.CENTER, spacing:{before:200,after:200},
          children:[new TextRun({ text:'Complete Diagram Reference Document', font:'Arial', size:40, color:C.blue })] }),
        new Paragraph({ alignment:AlignmentType.CENTER,
          children:[new TextRun({ text:'v1.0  —  27 April 2026', font:'Arial', size:28, color:C.dgray })] }),
        sp(400),
        // Cover index table
        (() => {
          const iw = Math.round(CW*0.65);
          const i1 = Math.round(iw*0.07), i2 = Math.round(iw*0.45), i3 = iw-i1-i2;
          return new Table({ width:{size:iw,type:WidthType.DXA}, columnWidths:[i1,i2,i3], rows:[
            new TableRow({ children:[ hCell('#',i1,C.navy), hCell('Diagram',i2,C.navy), hCell('Status',i3,C.navy) ]}),
            ...[
              ['1','Process Flow Diagram','✅ In this document'],
              ['2','Swimlane Diagram','✅ In this document'],
              ['3','Entity Relationship Diagram (ERD)','✅ 55 tables, 13 contexts'],
              ['4','Data Flow Diagram','✅ In this document'],
              ['5','System Architecture Diagram','✅ Updated from PPTX'],
              ['6','API Mapping','✅ All 270 routes'],
              ['7','UI Mapping','✅ 130+ pages'],
              ['8','AI Layer','✅ Sprint 19–25 roadmap'],
            ].map(([n,d,s],i) => new TableRow({ children:[
              dCell(n, i1, i%2===0?C.lGray:C.white, C.navy, AlignmentType.CENTER, 18, true),
              dCell(d, i2, i%2===0?C.lGray:C.white, '000000', AlignmentType.LEFT, 18),
              dCell(s, i3, C.lGreen, C.green, AlignmentType.LEFT, 16),
            ]})),
          ]});
        })(),
        pb(),

        // ── THE 8 DIAGRAMS ──────────────────────────────────────────────────
        ...processFlow(),
        ...swimlane(),
        ...erd(),
        ...dataFlow(),
        ...sysArch(),
        ...apiMapping(),
        ...uiMapping(),
        ...aiLayer(),
      ],
    }],
  });

  const buf = await Packer.toBuffer(doc);
  fs.writeFileSync('docs/OxyPC_All_Diagrams.docx', buf);
  const kb = (buf.length/1024).toFixed(1);
  console.log(`✅  OxyPC_All_Diagrams.docx  —  ${kb} KB`);
  console.log('    8 diagrams: Process Flow, Swimlane, ERD, Data Flow, System Arch, API Map, UI Map, AI Layer');
  console.log('    55 ERD entities | 270 API routes | 130+ UI pages | A4 Landscape');
}

build().catch(e => { console.error('❌', e.message); console.error(e.stack); process.exit(1); });
