/* ============================================================
   Reliance Asset FieldOps — Masters, Config & Seed Data
   Source: BRD v3.0 (Source Aligned) + Prototype v3
   ============================================================ */
(function (RA) {
  'use strict';

  var D = {};
  RA.data = D;

  /* ---------- Project master (BRD Sec 1) ---------- */
  D.PROJECT = {
    project_id: 'PRJ-REL-2026',
    name: 'Reliance Demo-Unit Asset Recovery',
    entity: 'DEV IT Serv Pvt Ltd / Deshwal Waste Mgmt (to confirm)',
    source: 'Inventory Details_LP TAT & Costing.xlsx',
    scope_assets: 3957,
    scope_locations: 622,
    baseline_days: 45,
    start_date: '2026-08-01',
    milestones: [
      { day: 20, pct: 50, label: 'D20 — ≥50%' },
      { day: 32, pct: 80, label: 'D32 — ≥80%' },
      { day: 40, pct: 95, label: 'D40 — ≥95%' },
      { day: 45, pct: 100, label: 'D45 — 100% accessible scope' }
    ]
  };

  /* ---------- Roles (BRD Sec 3) ---------- */
  D.ROLES = {
    fe:         { label: 'Field QC Engineer',   scope: 'Assigned sites only',  home: '#/myday' },
    coord:      { label: 'Regional Coordinator',scope: 'Assigned region',      home: '#/sites' },
    pmo:        { label: 'PMO / Project Manager',scope: 'All project data',    home: '#/dashboard' },
    spoc:       { label: 'Reliance Site SPOC',  scope: 'Own site (read-only)', home: '#/sites' },
    approver:   { label: 'Reliance QC Approver',scope: 'Assigned region',      home: '#/approvals' },
    commercial: { label: 'Commercial Approver', scope: 'Pricing data only',    home: '#/pricing' },
    packer:     { label: 'Packing / Pickup Partner', scope: 'Released assets', home: '#/packing' },
    courier:    { label: 'Courier Desk',        scope: 'Courier jobs only',    home: '#/courier' },
    warehouse:  { label: 'Warehouse User',      scope: 'Receiving warehouse',  home: '#/warehouse' },
    admin:      { label: 'System Admin',        scope: 'Administrative',       home: '#/admin' }
  };

  /* Screen access control (BRD FR-002 RBAC) */
  D.ACCESS = {
    myday:      ['fe', 'coord', 'pmo', 'admin'],
    sites:      ['fe', 'coord', 'pmo', 'spoc', 'approver', 'admin'],
    site:       ['fe', 'coord', 'pmo', 'spoc', 'approver', 'admin'],
    scan:       ['fe', 'coord', 'admin'],
    qc:         ['fe', 'coord', 'admin'],
    approvals:  ['approver', 'pmo', 'spoc', 'coord', 'admin'],
    pricing:    ['commercial', 'pmo', 'admin'],
    packing:    ['packer', 'fe', 'coord', 'pmo', 'admin'],
    pickup:     ['packer', 'coord', 'pmo', 'admin'],
    courier:    ['courier', 'coord', 'pmo', 'admin'],
    warehouse:  ['warehouse', 'pmo', 'admin'],
    dashboard:  ['pmo', 'coord', 'approver', 'spoc', 'commercial', 'admin'],
    reports:    ['pmo', 'coord', 'approver', 'commercial', 'warehouse', 'admin'],
    alerts:     ['fe', 'coord', 'pmo', 'approver', 'spoc', 'commercial', 'packer', 'courier', 'warehouse', 'admin'],
    audit:      ['pmo', 'admin', 'approver', 'commercial'],
    admin:      ['admin'],
    profile:    ['*'],
    asset:      ['*'],
    serial:     ['fe', 'coord', 'admin'],
    serials:    ['coord', 'pmo', 'admin']
  };

  /* Modules an administrator can grant or revoke per user, on top of the role
     default above (FR-002). `profile` and `asset` are always available. */
  D.MODULES = [
    { key: 'myday',     label: 'My Day' },
    { key: 'sites',     label: 'Sites & site jobs' },
    { key: 'scan',      label: 'Scan / find asset' },
    { key: 'serial',    label: 'Serial capture' },
    { key: 'qc',        label: 'Rapid QC' },
    { key: 'approvals', label: 'QC approvals' },
    { key: 'pricing',   label: 'Commercial & pricing' },
    { key: 'packing',   label: 'Packing' },
    { key: 'pickup',    label: 'Pickup & handover' },
    { key: 'courier',   label: 'Courier / AWB' },
    { key: 'warehouse', label: 'Warehouse receipt' },
    { key: 'serials',   label: 'Serial register' },
    { key: 'dashboard', label: 'Executive dashboard' },
    { key: 'reports',   label: 'Reports / MIS' },
    { key: 'alerts',    label: 'Notifications' },
    { key: 'audit',     label: 'Audit log' },
    { key: 'admin',     label: 'Admin & masters' }
  ];

  /* ---------- Defect codes (BRD Sec 6.2) ---------- */
  D.DEFECT_CODES = [
    { code: 'OK', label: 'No observable issue',                severity: 'none',   rank: 0, photo: false },
    { code: 'SC', label: 'Scratch / cosmetic wear',            severity: 'minor',  rank: 1, photo: true },
    { code: 'PP', label: 'Paint peel / paint wear',            severity: 'minor',  rank: 1, photo: true },
    { code: 'DT', label: 'Dent',                                severity: 'medium', rank: 2, photo: true },
    { code: 'KB', label: 'Keyboard not working / keys missing', severity: 'medium', rank: 2, photo: true },
    { code: 'TP', label: 'Touchpad not working / damaged',      severity: 'medium', rank: 2, photo: true },
    { code: 'HG', label: 'Hinge loose / broken',                severity: 'medium', rank: 2, photo: true },
    { code: 'PT', label: 'Port / exterior connector damaged',   severity: 'medium', rank: 2, photo: true },
    { code: 'CH', label: 'Charger missing / damaged',           severity: 'medium', rank: 2, photo: false },
    { code: 'NP', label: 'No Power',                            severity: 'major',  rank: 3, photo: true },
    { code: 'DB', label: 'Display broken / cracked',            severity: 'major',  rank: 3, photo: true },
    { code: 'DI', label: 'Display issue — lines / spots / no display', severity: 'major', rank: 3, photo: true },
    { code: 'CR', label: 'Body crack / major casing damage',    severity: 'major',  rank: 3, photo: true }
  ];
  D.codeMeta = function (c) {
    for (var i = 0; i < D.DEFECT_CODES.length; i++) if (D.DEFECT_CODES[i].code === c) return D.DEFECT_CODES[i];
    return { code: c, label: c, severity: 'none', rank: 0, photo: false };
  };

  /* ---------- Condition blocks — tap selections (BRD Sec 6.1) ---------- */
  var NT = 'Not Tested-No Power';
  D.CONDITION_BLOCKS = {
    laptop: [
      { key: 'power',    label: 'Power',           icon: '⚡',  values: ['Power ON', 'No Power'] },
      { key: 'display',  label: 'Display',         icon: '🖥️', values: ['OK', 'Broken/Cracked', 'Lines/Spots', 'No Display', NT], suppress: true },
      { key: 'body',     label: 'Body / Cosmetic', icon: '📱', values: ['OK', 'Scratch', 'Paint Wear/Peel', 'Dent', 'Crack', 'Multiple'] },
      { key: 'keyboard', label: 'Keyboard',        icon: '⌨️', values: ['Working', 'Not Working', 'Missing Key', NT], suppress: true },
      { key: 'touchpad', label: 'Touchpad',        icon: '🖱️', values: ['Working', 'Not Working', 'Damaged', NT], suppress: true },
      { key: 'hinge',    label: 'Hinge',           icon: '🔩', values: ['OK', 'Loose', 'Broken'] },
      { key: 'ports',    label: 'Ports / Exterior',icon: '🔌', values: ['Visibly OK', 'Damaged'] },
      { key: 'charger',  label: 'Charger',         icon: '🔋', values: ['Available/OK', 'Missing', 'Damaged', 'NA'] }
    ],
    desktop: [
      { key: 'power',    label: 'Power',           icon: '⚡',  values: ['Power ON', 'No Power'] },
      { key: 'body',     label: 'Cabinet / Body',  icon: '🖳',  values: ['OK', 'Scratch', 'Paint Wear/Peel', 'Dent', 'Crack', 'Multiple'] },
      { key: 'front',    label: 'Front Panel',     icon: '🎛️', values: ['OK', 'Damaged', 'Missing'] },
      { key: 'ports',    label: 'Ports / Exterior',icon: '🔌', values: ['Visibly OK', 'Damaged'] },
      { key: 'charger',  label: 'Power Cable',     icon: '🔌', values: ['Available/OK', 'Missing', 'Damaged', 'NA'] }
    ],
    tft: [
      { key: 'power',    label: 'Power',           icon: '⚡',  values: ['Power ON', 'No Power'] },
      { key: 'display',  label: 'Panel / Display', icon: '🖥️', values: ['OK', 'Broken/Cracked', 'Lines/Spots', 'No Display', NT], suppress: true },
      { key: 'body',     label: 'Body / Bezel',    icon: '🖼️', values: ['OK', 'Scratch', 'Paint Wear/Peel', 'Dent', 'Crack', 'Multiple'] },
      { key: 'stand',    label: 'Stand / Base',    icon: '🦿', values: ['OK', 'Loose', 'Broken', 'Missing'] },
      { key: 'ports',    label: 'Ports / Buttons', icon: '🔌', values: ['Visibly OK', 'Damaged'] },
      { key: 'charger',  label: 'Adapter / Cable', icon: '🔋', values: ['Available/OK', 'Missing', 'Damaged', 'NA'] }
    ]
  };
  D.NOT_TESTED = NT;

  /* Value → defect code mapping */
  D.CODE_MAP = {
    power:    { 'No Power': 'NP' },
    display:  { 'Broken/Cracked': 'DB', 'Lines/Spots': 'DI', 'No Display': 'DI' },
    body:     { 'Scratch': 'SC', 'Paint Wear/Peel': 'PP', 'Dent': 'DT', 'Crack': 'CR', 'Multiple': 'DT' },
    keyboard: { 'Not Working': 'KB', 'Missing Key': 'KB' },
    touchpad: { 'Not Working': 'TP', 'Damaged': 'TP' },
    hinge:    { 'Loose': 'HG', 'Broken': 'HG' },
    ports:    { 'Damaged': 'PT' },
    front:    { 'Damaged': 'PT', 'Missing': 'PT' },
    stand:    { 'Loose': 'HG', 'Broken': 'HG', 'Missing': 'HG' },
    charger:  { 'Missing': 'CH', 'Damaged': 'CH' }
  };

  /* ---------- Inspection spec fields (BRD v3 Sec 21) ---------- */
  var opt = function (k, l, v) { return { key: k, label: l, type: 'select', values: v }; };
  var txt = function (k, l) { return { key: k, label: l, type: 'text' }; };
  D.SPEC_FIELDS = {
    laptop: [
      txt('make', 'Make'), txt('model', 'Model'), txt('serial', 'Serial'),
      opt('processor', 'Processor', ['M1', 'M2', 'M3', 'M4', 'M1 Pro', 'M2 Pro', 'M3 Pro', 'M4 Pro',
        'M1 Max', 'M2 Max', 'M3 Max', 'M4 Max', 'i3', 'i5', 'i7', 'i9', 'Ryzen 5', 'Ryzen 7', 'Other']),
      opt('generation', 'Generation', ['Apple Silicon', '8th', '9th', '10th', '11th', '12th', '13th', 'NA']),
      opt('ram_type', 'RAM Type', ['Unified', 'DDR4', 'DDR5', 'LPDDR4', 'LPDDR5', 'NA']),
      opt('ram', 'RAM', ['4 GB', '8 GB', '16 GB', '18 GB', '24 GB', '32 GB', '36 GB', '48 GB', '64 GB', 'NA']),
      opt('storage_type', 'Storage Type', ['SSD', 'NVMe', 'HDD', 'eMMC', 'Missing']),
      opt('storage_cap', 'Storage Capacity', ['128 GB', '256 GB', '500 GB', '512 GB', '1 TB', '2 TB', 'NA']),
      opt('screen_size', 'Screen Size', ['13"', '14"', '15"', '16"', '11"', '17"']),
      opt('screen_type', 'Screen Type', ['HD', 'FHD', 'QHD', '4K', 'Touch']),
      opt('screen_cond', 'Screen Condition', ['Good', 'Minor Marks', 'Spots/Lines', 'Cracked']),
      opt('bezel', 'Bezel', ['OK', 'Loose', 'Damaged', 'Missing']),
      opt('base', 'Base', ['OK', 'Scratched', 'Cracked']),
      opt('front_panel', 'Front Panel', ['OK', 'Scratched', 'Damaged']),
      opt('body_paint', 'Body Paint', ['OK', 'Faded', 'Peeling']),
      opt('battery_avail', 'Battery Available', ['Yes', 'No']),
      opt('battery_cond', 'Battery Condition', ['Good', 'Weak', 'Dead', 'Not Tested']),
      opt('overall', 'Laptop Condition', ['A - Good', 'B - Fair', 'C - Poor', 'D - Scrap'])
    ],
    desktop: [
      txt('make', 'Make'), txt('model', 'Model'), txt('serial', 'Serial'),
      opt('processor', 'Processor', ['M1', 'M2', 'M3', 'M4', 'M1 Pro', 'M2 Pro', 'M3 Pro', 'M4 Pro',
        'M1 Max', 'M2 Max', 'M3 Max', 'M1 Ultra', 'M2 Ultra', 'i3', 'i5', 'i7', 'i9', 'Other']),
      opt('generation', 'Generation', ['Apple Silicon', '8th', '9th', '10th', '11th', '12th', '13th', 'NA']),
      opt('ram_type', 'RAM Type', ['Unified', 'DDR4', 'DDR5', 'NA']),
      opt('ram', 'RAM', ['4 GB', '8 GB', '16 GB', '24 GB', '32 GB', '36 GB', '48 GB', '64 GB', 'NA']),
      opt('storage_type', 'Storage Type', ['SSD', 'NVMe', 'HDD', 'Missing']),
      opt('storage_cap', 'Storage Capacity', ['128 GB', '256 GB', '500 GB', '512 GB', '1 TB', '2 TB', 'NA']),
      opt('screen_size', 'Screen Size (AIO)', ['21.5"', '24"', '27"', 'NA']),
      opt('form_factor', 'Form Factor', ['AIO', 'Tower', 'SFF', 'Mini']),
      opt('cabinet', 'Cabinet Condition', ['OK', 'Scratched', 'Dented', 'Cracked']),
      opt('front_panel', 'Front Panel', ['OK', 'Damaged', 'Missing']),
      opt('body_paint', 'Body Paint', ['OK', 'Faded', 'Peeling']),
      opt('overall', 'Desktop Condition', ['A - Good', 'B - Fair', 'C - Poor', 'D - Scrap'])
    ],
    tft: [
      txt('make', 'Make'), txt('model', 'Model'), txt('serial', 'Serial'),
      opt('screen_size', 'Screen Size', ['21.5"', '24"', '27"', '15"', '17"', '18.5"', '19"']),
      opt('screen_type', 'Screen Type', ['TN', 'IPS', 'VA', 'LED', 'LCD']),
      opt('screen_cond', 'Screen Condition', ['Good', 'Minor Marks', 'Spots/Lines', 'Cracked']),
      opt('bezel', 'Bezel', ['OK', 'Loose', 'Damaged']),
      opt('stand_incl', 'Stand Included', ['Yes', 'No']),
      opt('cable_incl', 'Cable Included', ['Yes', 'No']),
      opt('body_paint', 'Body Paint', ['OK', 'Faded', 'Peeling']),
      opt('overall', 'TFT Condition', ['A - Good', 'B - Fair', 'C - Poor', 'D - Scrap'])
    ]
  };

  D.CATEGORY_LABEL = { laptop: 'Laptop', desktop: 'Desktop', tft: 'TFT / Monitor' };

  /* ---------- Configuration defaults (admin-editable) ---------- */
  D.CONFIG = {
    /* Logistics thresholds — BRD FR-016 */
    logistics: { dedicated_min: 10, cluster_min: 3, courier_max: 2 },
    /* QC benchmark — BRD v3: 12–15 min per laptop */
    qc: { target_min: 12, max_min: 15, alert_min: 20 },
    /* FE allocation rules — BRD v3 Sec 21 */
    fe_rules: [
      { max: 10,     fes: 1, hours: '2 – 2.5 h',   h: 2.25 },
      { max: 20,     fes: 1, hours: '4 – 4.5 h',   h: 4.25 },
      { max: 40,     fes: 2, hours: '4 – 4.5 h',   h: 4.25 },
      { max: 60,     fes: 3, hours: '5 – 5.5 h',   h: 5.25 },
      { max: 1e9,    fes: 3, hours: '6 – 6.5 h',   h: 6.25 }
    ],
    store_buffer_min: 30,
    /* Visit plan KPI — BRD v3 */
    daily_location_target: 15,
    /* SLA (hours) — BRD Sec 15 */
    sla: {
      qc_approval_h: 24,
      dispute_h: 24,
      pickup_release_h: 4,
      pickup_release_breach_h: 8,
      transit_h: 48,
      wh_receipt_h: 4,
      wh_total_breach_h: 72,
      wh_discrepancy_h: 24
    },
    /* Multiple-defect commercial rule — BRD Sec 7.2 */
    multi_defect_rule: 'highest', // highest | additive | capped
    multi_defect_cap_pct: 40,
    /* Photo policy — BRD FR-008 */
    photo: { overall_required: true, defect_required_for_exception: true, max_photos: 4, max_px: 900, quality: 0.62 }
  };

  /* ---------- Charge rate card v1 (BRD v3 §21 costing fields) ----------
     Derived from and reconciled against the source workbook:
       QC charges      = ₹1,500 per block of 20 units      (622/622 rows exact)
       Packing         = ₹150 per unit                     (622/622 rows exact)
       Weight          = 4 kg per unit                     (622/622 rows exact)
       FOV             = 0.1% of shipment value            (where applicable)
       Shipment value  = Σ RRP of the units at the site    (622/622 rows exact)
       Total           = QC + packing + pickup + FOV       (622/622 rows exact)
       Post-confirm    = total + ₹1,500                    (622/622 rows exact)
       Pickup          = slab by quantity, per-unit rate for large sites
                         (matches 605/622; the rest carry a metro premium and
                          are held as per-site overrides)
     These are planning / commercial inputs and are separate from the
     asset-condition deduction matrix (BRD Sec 7). ------------------------- */
  D.RATE_CARD = {
    version: 1,
    label: 'v1 — As per source costing sheet',
    effective_from: '2026-08-01',
    approved_by: '',
    approval_status: 'Source baseline',
    active: true,
    created_at: '2026-08-01T00:00:00.000Z',
    rates: {
      qc_block_rate: 1500,        // ₹ per QC block
      qc_block_units: 20,         // units covered by one block
      packing_per_unit: 150,      // ₹ per unit
      weight_per_unit: 4,         // kg per unit
      pickup_single_max: 1,       // units ≤ this → single-pickup rate
      pickup_single: 600,
      pickup_cluster_max: 9,      // units ≤ this → cluster rate
      pickup_cluster: 1050,
      pickup_dedicated: 1500,     // units above cluster max
      pickup_per_unit: 84,        // ₹ per unit for large sites
      pickup_per_unit_from: 28,   // units at or above which per-unit applies
      fov_pct: 0.1,               // % of shipment value
      post_confirmation_addon: 1500
    }
  };

  D.RATE_FIELDS = [
    { key: 'qc_block_rate',       label: 'QC charge per block',        unit: '₹',  group: 'QC & packing' },
    { key: 'qc_block_units',      label: 'Units covered per QC block', unit: 'units', group: 'QC & packing' },
    { key: 'packing_per_unit',    label: 'Packing charge per unit',    unit: '₹',  group: 'QC & packing' },
    { key: 'weight_per_unit',     label: 'Weight per unit',            unit: 'kg', group: 'QC & packing' },
    { key: 'pickup_single_max',   label: 'Single pickup up to',        unit: 'units', group: 'Pickup' },
    { key: 'pickup_single',       label: 'Single pickup charge',       unit: '₹',  group: 'Pickup' },
    { key: 'pickup_cluster_max',  label: 'Cluster pickup up to',       unit: 'units', group: 'Pickup' },
    { key: 'pickup_cluster',      label: 'Cluster pickup charge',      unit: '₹',  group: 'Pickup' },
    { key: 'pickup_dedicated',    label: 'Dedicated pickup charge',    unit: '₹',  group: 'Pickup' },
    { key: 'pickup_per_unit',     label: 'Large-site rate per unit',   unit: '₹',  group: 'Pickup' },
    { key: 'pickup_per_unit_from',label: 'Per-unit rate applies from', unit: 'units', group: 'Pickup' },
    { key: 'fov_pct',             label: 'FOV charge',                 unit: '% of shipment', group: 'Freight & FOV' },
    { key: 'post_confirmation_addon', label: 'Post-confirmation add-on', unit: '₹', group: 'Freight & FOV' }
  ];

  /* ---------- Deduction master v1 — 0% until Reliance approval (BRD Sec 7) ---------- */
  D.DEDUCTION_V1 = {
    version: 1,
    label: 'v1 — Baseline (pending Reliance approval)',
    effective_from: '2026-08-01',
    approved_by: '',
    approval_status: 'Pending Reliance Approval',
    rule: 'highest',
    rates: (function () {
      var r = {}; D.DEFECT_CODES.forEach(function (c) { r[c.code] = 0; }); return r;
    })(),
    active: true,
    created_at: '2026-08-01T00:00:00.000Z'
  };

  /* ---------- Users (demo credentials; PIN 1234) ----------
     FE / SPOC site assignments are attached at seed time from the
     real location master (see D.seed). */
  D.USERS = [
    { id: 'U01', name: 'Rahul Verma',   emp: 'qc.eng.04',   role: 'fe',         region: 'West',  sites: [] },
    { id: 'U02', name: 'Anita Joshi',   emp: 'qc.eng.11',   role: 'fe',         region: 'South', sites: [] },
    { id: 'U03', name: 'Suresh Nair',   emp: 'coord.west',  role: 'coord',      region: 'West',  sites: [] },
    { id: 'U04', name: 'Priya Menon',   emp: 'pmo.national',role: 'pmo',        region: 'All',   sites: [] },
    { id: 'U05', name: 'Ramesh Kadam',  emp: 'rel.spoc',    role: 'spoc',       region: 'West',  sites: [] },
    { id: 'U06', name: 'Meera Rao',     emp: 'rel.qc.appr', role: 'approver',   region: 'All',   sites: [] },
    { id: 'U07', name: 'Vikram Shah',   emp: 'rel.comm',    role: 'commercial', region: 'All',   sites: [] },
    { id: 'U08', name: 'Sunil Pawar',   emp: 'pickup.desk', role: 'packer',     region: 'All',   sites: [] },
    { id: 'U09', name: 'Deepa Iyer',    emp: 'courier.desk',role: 'courier',    region: 'All',   sites: [] },
    { id: 'U10', name: 'Arjun Patel',   emp: 'wh.mumbai01', role: 'warehouse',  region: 'All',   sites: [] },
    { id: 'U11', name: 'Sysadmin',      emp: 'admin',       role: 'admin',      region: 'All',   sites: [] }
  ];


  /* ---------- Seed sites & assets from the source master ----------
     RA.inventory is generated from
     "Inventory Details_LP TAT & Costing.xlsx" (js/inventory.js):
       · 622 locations with TAT, costing and executing partner
       · 121 article SKUs
       · 3,957 units expanded into individual asset records
     ------------------------------------------------------------- */
  D.seed = function () {
    var inv = RA.inventory;
    if (!inv) return { sites: [], assets: [] };

    var perDay = D.CONFIG.daily_location_target || 15;
    var start = new Date(D.PROJECT.start_date);

    var sites = inv.sites.map(function (s, i) {
      var plan = new Date(start.getTime());
      plan.setDate(plan.getDate() + Math.floor(i / perDay));
      return {
        id: 'S' + pad(i + 1, 3),
        code: s.code,
        codes: s.codes,
        format: s.format,
        state: s.state,
        city: titleCase(s.city),
        region: s.zone,
        site: s.site,
        site_desc: s.site + ' · ' + s.format,
        address: [s.site, titleCase(s.city), s.state].filter(Boolean).join(', '),
        spoc: '', spoc_phone: '',
        access_window: '10:00 – 18:00', blackout: '',
        readiness: 'Pending',
        planned_date: plan.toISOString().slice(0, 10),
        planned_qty: s.qty,
        status: 'Scheduled',
        partner: s.exec_by,
        tat: s.tat,
        tat_after: s.tat_after,
        tat_risk: /30-45|45/.test(s.tat || '') || /45/.test(s.tat_after || ''),
        fov_applicable: (s.fov_ch || 0) > 0,
        costing: {
          shipment_value: s.shipment,
          qc_charges: s.qc_ch,
          packing_charges: s.pack_ch,
          weight_kg: s.weight,
          pickup_charges: s.pickup_ch,
          fov_charges: s.fov_ch,
          total_charges: s.total_ch,
          post_confirmation_total: s.post_ch,
          /* Sites whose source pickup carries a premium the rate card cannot
             express are held as overrides, so a rate-card apply never silently
             overwrites a negotiated figure. */
          basis: rulePickup(s.qty) === s.pickup_ch ? 'source' : 'override',
          rate_version: 0
        },
        notes: ''
      };
    });

    /* Assets stay lean on disk: article attributes live once in the catalogue
       and are attached as non-enumerable properties by D.hydrate(). */
    var assets = [], aSeq = 0, perSite = {};
    inv.lines.forEach(function (ln) {
      var site = sites[ln[0]];
      var c = inv.catalog[ln[1]];
      var qty = ln[2], sl = ln[3], invType = ln[4];
      for (var k = 0; k < qty; k++) {
        aSeq++;
        perSite[site.id] = (perSite[site.id] || 0) + 1;
        assets.push(D.hydrate({
          id: 'A' + pad(aSeq, 5),
          tag: 'REL-' + site.code + '-' + pad(perSite[site.id], 3),
          serial: 'PEND-' + pad(aSeq, 5),      /* captured at QC — not in source master */
          category: c.cat,
          site_id: site.id,
          storage_location: sl,
          inventory_type: invType,
          art: ln[1],
          base_price: c.rrp || c.mrp,
          status: 'pending_qc',
          qc_id: null, package_id: null, movement_id: null, receipt_id: null
        }, inv.catalog));
      }
    });

    /* Attach demo assignments to real locations, first by partner then by zone */
    var deshwal = sites.filter(function (s) { return s.partner === 'Deshwal'; });
    var south = sites.filter(function (s) { return s.region === 'South'; });
    D.USERS.forEach(function (u) {
      if (u.id === 'U01') u.sites = deshwal.slice(0, 3).map(idOf);
      if (u.id === 'U02') u.sites = south.slice(0, 3).map(idOf);
      if (u.id === 'U05') u.sites = deshwal.slice(0, 1).map(idOf);
      if (u.id === 'U01' && deshwal[0]) u.region = deshwal[0].region;
    });
    function idOf(s) { return s.id; }

    return { sites: sites, assets: assets };
  };

  /* ---------- Asset hydration ----------
     Attaches article-master attributes (make, model, MH hierarchy, RRP/MRP…)
     from the catalogue as NON-ENUMERABLE properties, so `asset.make` works
     everywhere in the app while JSON.stringify — and therefore what is stored
     on the device — keeps only the asset's own mutable fields. Assets created
     by CSV import carry their own attributes and are passed through untouched. */
  var ART_FIELDS = {
    make: 'make', model: 'model', chip: 'chip', ram: 'ram', storage: 'storage',
    screen_size: 'size', mh_family: 'family', mh_class: 'cls', mh_brick: 'brick',
    article: 'article', article_desc: 'desc', rrp: 'rrp', mrp: 'mrp'
  };
  D.hydrate = function (asset, catalog) {
    if (!asset || typeof asset.art !== 'number') return asset;
    var c = (catalog || (RA.inventory && RA.inventory.catalog) || [])[asset.art];
    if (!c) return asset;
    Object.keys(ART_FIELDS).forEach(function (k) {
      if (Object.prototype.hasOwnProperty.call(asset, k)) return;
      Object.defineProperty(asset, k, {
        value: c[ART_FIELDS[k]], enumerable: false, writable: true, configurable: true
      });
    });
    Object.defineProperty(asset, 'stock_qty', { value: 1, enumerable: false, writable: true, configurable: true });
    Object.defineProperty(asset, 'year', { value: '', enumerable: false, writable: true, configurable: true });
    return asset;
  };
  D.hydrateAll = function (assets) {
    var cat = RA.inventory && RA.inventory.catalog;
    if (!cat) return assets;
    for (var i = 0; i < assets.length; i++) D.hydrate(assets[i], cat);
    return assets;
  };

  /* Pickup charge implied by the baseline rate card, used at seed time to spot
     sites carrying a negotiated premium. */
  function rulePickup(units) {
    var r = D.RATE_CARD.rates;
    if (!units) return 0;
    if (units >= r.pickup_per_unit_from) return units * r.pickup_per_unit;
    if (units <= r.pickup_single_max) return r.pickup_single;
    if (units <= r.pickup_cluster_max) return r.pickup_cluster;
    return r.pickup_dedicated;
  }

  function pad(n, w) { var s = String(n); while (s.length < w) s = '0' + s; return s; }
  /* Source city names are upper-case; title-case them but keep known acronyms */
  var KEEP_UPPER = { NCR: 1, MG: 1, GT: 1, HSR: 1, BTM: 1, CBD: 1, IT: 1, SG: 1 };
  function titleCase(s) {
    return String(s || '').toLowerCase().replace(/[a-z']+/g, function (w) {
      var up = w.toUpperCase();
      if (KEEP_UPPER[up]) return up;
      return w.charAt(0).toUpperCase() + w.slice(1);
    }).replace(/\/\s+/g, ' / ');
  }

  /* ---------- FE allocation calculator (BRD v3) ---------- */
  D.feAllocation = function (qty, cfg) {
    cfg = cfg || D.CONFIG;
    var rules = cfg.fe_rules, r = rules[rules.length - 1];
    for (var i = 0; i < rules.length; i++) { if (qty < rules[i].max) { r = rules[i]; break; } }
    var buffer = cfg.store_buffer_min / 60;
    return {
      fes: r.fes,
      window: r.hours,
      hours: r.h,
      total_hours: +(r.h + buffer).toFixed(2),
      buffer_min: cfg.store_buffer_min,
      note: qty + ' units → ' + r.fes + ' FE × ' + r.hours + ' + ' + cfg.store_buffer_min + ' min store buffer'
    };
  };

  /* ---------- Logistics mode recommendation (BRD FR-016) ---------- */
  D.logisticsMode = function (count, cfg) {
    cfg = (cfg || D.CONFIG).logistics;
    if (count >= cfg.dedicated_min) return { mode: 'dedicated', label: 'Dedicated Pickup', rule: '≥' + cfg.dedicated_min + ' assets / site' };
    if (count >= cfg.cluster_min)   return { mode: 'cluster',   label: 'Cluster Pickup',   rule: cfg.cluster_min + '–' + (cfg.dedicated_min - 1) + ' assets / site' };
    return { mode: 'courier', label: 'Approved Courier', rule: '≤' + cfg.courier_max + ' assets · Reliance authorisation required' };
  };

})(window.RA = window.RA || {});
