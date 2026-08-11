/* ============================================================
   Reliance Asset FieldOps — Control screens
   Dashboard · Reports/MIS · Alerts · Audit · Admin · Profile
   ============================================================ */
(function (RA) {
  'use strict';
  var U = RA.ui, S = RA.store, D = RA.data;
  var Sc = RA.screens = RA.screens || {};
  var A = RA.actions = RA.actions || {};

  function kv(k, v) { return '<div class="kv"><div class="k">' + U.esc(k) + '</div><div class="v">' + U.esc(v) + '</div></div>'; }
  function metric(v, l) { return '<div class="metric-box"><div class="m-val">' + v + '</div><div class="m-lbl">' + U.esc(l) + '</div></div>'; }
  function bar(label, pct, cls) {
    return '<div class="chart-bar-wrap"><div class="chart-bar-label"><span>' + U.esc(label) +
      '</span><span>' + U.pct(pct) + '</span></div>' +
      '<div class="chart-bar"><div class="chart-bar-fill ' + cls + '" style="width:' + Math.min(100, pct) + '%">' +
      (pct > 12 ? U.pct(pct) : '') + '</div></div></div>';
  }

  /* =========================================================
     DASHBOARD (FR-020, Sec 12)
     ========================================================= */
  Sc.dashboard = {
    title: 'Executive Dashboard',
    badge: function () { return 'Day ' + S.projectDay(); },
    render: function () {
      var st = S.stats();
      var day = S.projectDay();
      var p = S.db.project;
      var todayQC = S.todayQC();
      var mins = todayQC.reduce(function (a, q) { return a + q.seconds; }, 0) / 60;
      var avg = todayQC.length ? mins / todayQC.length : 0;
      var sitesToday = {};
      todayQC.forEach(function (q) { sitesToday[q.site_id] = 1; });
      var locToday = Object.keys(sitesToday).length;

      var h = '';
      h += '<div class="card pad navy-card">' +
        '<div class="row-between"><b>' + U.esc(p.name) + '</b>' + U.pill('Day ' + day + ' / ' + p.baseline_days, 'gold') + '</div>' +
        '<div class="small light">' + st.total.toLocaleString('en-IN') + ' assets loaded · ' +
        S.db.sites.length + ' locations · scope ' + p.scope_assets.toLocaleString('en-IN') + ' / ' + p.scope_locations + '</div>' +
      '</div>';

      h += '<div class="stats-row">' +
        '<div class="stat-card highlight"><div class="stat-val">' + todayQC.length + '</div><div class="stat-label">Units QC\'d today</div></div>' +
        '<div class="stat-card"><div class="stat-val">' + st.qc_done.toLocaleString('en-IN') + '</div><div class="stat-label">Total QC done</div></div>' +
        '<div class="stat-card"><div class="stat-val">' + S.liveQC().filter(function (q) { return q.status === 'pending'; }).length +
          '</div><div class="stat-label">Pending approvals</div></div>' +
        '<div class="stat-card"><div class="stat-val">' + locToday + ' / ' + S.db.config.daily_location_target +
          '</div><div class="stat-label">Locations today (target)</div></div>' +
      '</div>';

      /* Milestones with RAG */
      h += '<div class="section-label">Milestones — RAG</div><div class="card pad">';
      p.milestones.forEach(function (m) {
        var rag = S.milestoneRag(m);
        h += '<div class="ms-row"><div class="row-between">' +
          '<span class="small"><b>' + U.esc(m.label) + '</b> · day ' + m.day + '</span>' +
          '<span class="rag rag-' + rag + '">' + rag.toUpperCase() + '</span></div>' +
          U.bar(st.pct_closed / m.pct * 100, rag === 'green' ? 'green' : rag === 'amber' ? 'amber' : 'red') +
          '<div class="small muted">Closure ' + U.pct(st.pct_closed) + ' of required ' + m.pct + '% · gap ' +
          Math.max(0, Math.ceil(st.total * m.pct / 100 - st.received)) + ' units</div></div>';
      });
      h += '</div>';

      /* Funnel */
      h += '<div class="section-label">Chain-of-custody funnel</div><div class="card pad">' +
        bar('QC complete', st.pct_qc, 'green') +
        bar('Reliance accepted', st.pct_accepted, 'amber') +
        bar('Packed', st.total ? st.packed / st.total * 100 : 0, 'blue') +
        bar('Dispatched', st.pct_dispatched, 'teal') +
        bar('Warehouse received', st.pct_received, 'green') +
      '</div>';

      /* Productivity */
      h += '<div class="section-label">Productivity & quality</div>' +
        '<div class="metric-grid">' +
          metric(avg ? avg.toFixed(1) + 'm' : '—', 'Avg min / unit') +
          metric(S.db.config.qc.target_min + '–' + S.db.config.qc.max_min + 'm', 'Benchmark') +
          metric(new Set(todayQC.map(function (q) { return q.engineer_id; })).size, 'FEs active') +
          metric(S.liveQC().filter(function (q) { return q.version > 1; }).length, 'Re-QC events') +
          metric(S.liveQC().filter(function (q) { return q.primary_code !== 'OK'; }).length, 'Exceptions') +
          metric(S.db.receipts.filter(function (r) { return r.discrepancy; }).length, 'WH discrepancies') +
        '</div>';

      /* Region split */
      var byRegion = {};
      S.db.sites.forEach(function (s) {
        var r = byRegion[s.region] = byRegion[s.region] || { total: 0, done: 0, sites: 0 };
        var a = S.assetsAt(s.id);
        r.sites++; r.total += a.length;
        r.done += a.filter(function (x) { return x.status !== 'pending_qc'; }).length;
      });
      h += '<div class="section-label">Regional progress</div><div class="card pad">' +
        Object.keys(byRegion).sort().map(function (r) {
          var x = byRegion[r];
          return bar(r + ' (' + x.sites + ' sites · ' + x.total + ' units)', x.total ? x.done / x.total * 100 : 0, 'green');
        }).join('') + '</div>';

      /* Executing partner split (v3) */
      var byPartner = { Deshwal: { s: 0, a: 0, d: 0 }, Partner: { s: 0, a: 0, d: 0 } };
      S.db.sites.forEach(function (s) {
        var k = s.partner === 'Deshwal' ? 'Deshwal' : 'Partner';
        var a = S.assetsAt(s.id);
        byPartner[k].s++; byPartner[k].a += a.length;
        byPartner[k].d += a.filter(function (x) { return x.status !== 'pending_qc'; }).length;
      });
      h += '<div class="section-label">Execution split — Deshwal vs partner-led</div><div class="card pad">' +
        Object.keys(byPartner).map(function (k) {
          var x = byPartner[k];
          return bar(k + '-led (' + x.s + ' sites · ' + x.a + ' units)', x.a ? x.d / x.a * 100 : 0, k === 'Deshwal' ? 'green' : 'blue');
        }).join('') +
        (function () {
          var risky = S.db.sites.filter(function (s) { return s.tat_risk; });
          return risky.length ? '<div class="small err mt6">⚠ ' + risky.length +
            ' site(s) carry a source TAT of 30–45 days against the Day-45 critical path.</div>' : '';
        })() +
      '</div>';

      /* Defect mix */
      var mix = {};
      S.liveQC().forEach(function (q) { q.codes.forEach(function (c) { mix[c] = (mix[c] || 0) + 1; }); });
      var mixKeys = Object.keys(mix).sort(function (a, b) { return mix[b] - mix[a]; });
      h += '<div class="section-label">Defect mix</div>';
      h += mixKeys.length ? '<div class="card">' + mixKeys.map(function (c) {
        var m = D.codeMeta(c);
        return '<div class="card-row"><div class="grow small">' + U.esc(c + ' — ' + m.label) + '</div>' +
          U.pill(mix[c] + ' units', m.rank === 0 ? 'ok' : m.rank >= 3 ? 'fail' : 'warn') + '</div>';
      }).join('') + '</div>' : U.empty('📊', 'No QC data yet', 'Complete a QC to populate analytics.');

      /* SLA ageing */
      var n = S.notifications();
      h += '<div class="section-label">SLA ageing & exceptions</div>';
      h += n.length ? '<div class="card">' + n.slice(0, 6).map(function (x) {
        var inner = '<span class="notif-dot ' + x.level + '"></span>' +
          '<div class="grow"><div class="row-title small">' + U.esc(x.title) + '</div>' +
          '<div class="small muted">' + U.esc(x.body) + '</div></div>';
        return x.link
          ? '<a class="card-row link" href="' + x.link + '">' + inner + '</a>'
          : '<div class="card-row">' + inner + '</div>';
      }).join('') + '</div>' : U.empty('✅', 'No SLA breaches', 'Everything inside target.');

      h += '<div class="pad-x mt8"><button class="btn btn-outline block" data-act="print-dashboard">🖨 Print / PDF executive summary</button></div>';
      return h;
    }
  };

  A['print-dashboard'] = function () {
    var st = S.stats(), p = S.db.project, day = S.projectDay();
    var rows = S.db.sites.map(function (s) {
      var a = S.assetsAt(s.id);
      var sst = S.stats([s.id]);
      return '<tr><td>' + U.esc(s.site) + '</td><td>' + U.esc(s.city + ', ' + s.state) + '</td><td>' + U.esc(s.partner) +
        '</td><td>' + a.length + '</td><td>' + sst.qc_done + '</td><td>' + sst.accepted + '</td><td>' + sst.dispatched +
        '</td><td>' + sst.received + '</td><td>' + U.pct(sst.pct_closed) + '</td></tr>';
    }).join('');
    U.printReport('Executive MIS — Day ' + day,
      '<h1>Reliance Asset FieldOps — Executive MIS</h1>' +
      '<div class="sub">' + U.esc(p.name) + ' · Day ' + day + ' of ' + p.baseline_days + '</div>' +
      '<div class="kv"><div><b>Assets:</b> ' + st.total + '</div><div><b>QC done:</b> ' + st.qc_done +
      '</div><div><b>Accepted:</b> ' + st.accepted + '</div><div><b>Dispatched:</b> ' + st.dispatched +
      '</div><div><b>WH received:</b> ' + st.received + '</div><div><b>Closure:</b> ' + U.pct(st.pct_closed) + '</div></div>' +
      '<h2>Milestone status</h2><table><thead><tr><th>Milestone</th><th>Target</th><th>Actual</th><th>RAG</th></tr></thead><tbody>' +
      p.milestones.map(function (m) {
        return '<tr><td>' + U.esc(m.label) + '</td><td>' + m.pct + '%</td><td>' + U.pct(st.pct_closed) +
          '</td><td>' + S.milestoneRag(m).toUpperCase() + '</td></tr>';
      }).join('') + '</tbody></table>' +
      '<h2>Site-wise progress</h2><table><thead><tr><th>Site</th><th>Location</th><th>Partner</th><th>Units</th>' +
      '<th>QC</th><th>Accepted</th><th>Dispatched</th><th>Received</th><th>Closure</th></tr></thead><tbody>' +
      rows + '</tbody></table>');
  };

  /* =========================================================
     REPORTS / MIS (FR-021, FR-024)
     ========================================================= */
  Sc.reports = {
    title: 'Reports & MIS',
    render: function () {
      var st = S.stats();
      var todayQC = S.todayQC();
      var h = '';
      h += '<div class="metric-grid">' +
        metric(todayQC.length, "QC'd today") +
        metric(st.qc_done, 'Total QC') +
        metric(st.accepted, 'Accepted') +
        metric(st.dispatched, 'Dispatched') +
        metric(st.received, 'WH received') +
        metric(S.db.receipts.filter(function (r) { return r.discrepancy && r.discrepancy_status === 'open'; }).length, 'Open variance') +
      '</div>';

      h += '<div class="section-label">Standard reports</div><div class="card">' +
        rep('📋', 'QC report', 'Asset-wise QC, codes, timing, engineer, status', 'export-qc') +
        rep('💰', 'Pricing report', 'Base, deduction %, deduction amount, revised price', 'export-pricing') +
        rep('📦', 'Packing & manifest log', 'Packages, seals, asset mapping', 'export-packing') +
        rep('🚚', 'Pickup / AWB log', 'Movements, vehicles, AWB, POD status', 'export-awb') +
        rep('🏷️', 'Warehouse discrepancy report', 'GRN, expected vs received, variance owner', 'export-wh') +
        rep('🔗', 'Chain-of-custody exception report', 'Assets stuck between stages', 'export-chain') +
        rep('📈', 'Daily MIS', 'Consolidated daily position', 'export-mis') +
        rep('🌱', 'BRSR / ESG summary', 'Recovered units, weight diverted, sites covered', 'print-esg') +
      '</div>';

      h += '<div class="section-label">Chain-of-custody exceptions</div>';
      var ex = chainExceptions();
      h += ex.length ? '<div class="card">' + ex.slice(0, 25).map(function (e) {
        return '<a class="card-row link" href="#/asset/' + e.id + '"><div class="grow">' +
          '<div class="row-title small">' + U.esc(e.tag) + '</div><div class="small muted">' + U.esc(e.issue) + '</div></div>' +
          U.statusPill(e.status) + '</a>';
      }).join('') + '</div>' : U.empty('✅', 'No chain-of-custody gaps', '');
      if (ex.length > 25) h += '<div class="small muted pad-x">Showing 25 of ' + ex.length + ' — export for the full list.</div>';
      return h;
    }
  };
  function rep(icon, title, sub, act) {
    return '<button class="card-row link full" data-act="' + act + '"><span class="rep-icon">' + icon + '</span>' +
      '<div class="grow"><div class="row-title">' + U.esc(title) + '</div>' +
      '<div class="small muted">' + U.esc(sub) + '</div></div><span class="chev">⬇</span></button>';
  }

  function chainExceptions() {
    var out = [];
    S.db.assets.forEach(function (a) {
      var q = a.qc_id ? S.qcRecord(a.qc_id) : null;
      if (q && q.status === 'accepted' && !a.package_id) out.push({ id: a.id, tag: a.tag, status: a.status, issue: 'Accepted but not packed' });
      else if (a.package_id && !a.movement_id) out.push({ id: a.id, tag: a.tag, status: a.status, issue: 'Packed but not dispatched' });
      else if (a.movement_id && !a.receipt_id) out.push({ id: a.id, tag: a.tag, status: a.status, issue: 'Dispatched but not received' });
      else if (a.status === 'received_discrepancy') out.push({ id: a.id, tag: a.tag, status: a.status, issue: 'Warehouse variance open' });
    });
    return out;
  }

  /* ----- export actions ----- */
  A['export-qc'] = function () {
    var rows = S.db.qc.map(function (q) {
      var a = S.asset(q.asset_id), s = S.site(q.site_id), cm = S.commercialFor(q.id);
      return [q.id, q.version, s ? s.state : '', s ? s.city : '', s ? s.site : '', a ? a.tag : '', a ? a.serial : '',
        a ? a.make : '', a ? a.model : '', D.CATEGORY_LABEL[q.category], q.codes.join('+'), q.primary_code,
        q.responses.power || '', q.responses.display || '', q.responses.body || '', q.responses.keyboard || '',
        q.responses.touchpad || '', q.responses.hinge || '', q.responses.ports || '', q.responses.charger || '',
        (q.photos || []).length, Math.round(q.seconds / 60 * 10) / 10, q.engineer, q.submitted_at, q.status,
        q.approver || '', q.approved_at || '', q.reason || '',
        cm ? cm.base_price : '', cm ? cm.deduction_pct : '', cm ? cm.deduction_amount : '', cm ? cm.revised_price : '', q.remarks];
    });
    U.exportCSV('QC_Report', ['QC ID', 'Version', 'State', 'City', 'Site', 'Asset Tag', 'Serial', 'Make', 'Model', 'Category',
      'Defect Codes', 'Primary Code', 'Power', 'Display', 'Body', 'Keyboard', 'Touchpad', 'Hinge', 'Ports', 'Charger',
      'Photos', 'QC Minutes', 'Engineer', 'Submitted At', 'QC Status', 'Approver', 'Approved At', 'Reason',
      'Base Price', 'Deduction %', 'Deduction Amount', 'Revised Price', 'Remarks'], rows);
  };
  A['export-pricing'] = function () {
    var rows = S.db.commercial.map(function (c) {
      var a = S.asset(c.asset_id), q = S.qcRecord(c.qc_id), s = a ? S.site(a.site_id) : null;
      return [c.id, c.qc_id, s ? s.site : '', a ? a.tag : '', a ? a.serial : '', q ? q.codes.join('+') : '',
        c.base_price, c.deduction_pct, c.deduction_amount, c.revised_price, 'v' + c.master_version,
        c.qc_status, c.commercial_status, c.updated_at];
    });
    U.exportCSV('Pricing_Report', ['Commercial ID', 'QC ID', 'Site', 'Asset Tag', 'Serial', 'Codes', 'Base Price',
      'Deduction %', 'Deduction Amount', 'Revised Price', 'Master Version', 'QC Status', 'Commercial Status', 'Updated'], rows);
  };
  A['export-packing'] = function () {
    var rows = [];
    S.db.packages.forEach(function (p) {
      var s = S.site(p.site_id);
      p.assets.forEach(function (id) {
        var a = S.asset(id);
        rows.push([p.id, s ? s.site : '', p.type, p.seal, p.packed_by, p.packed_at, p.status, p.movement_id || '',
          a ? a.tag : '', a ? a.serial : '', a ? a.make + ' ' + a.model : '']);
      });
    });
    U.exportCSV('Packing_Manifest', ['Package ID', 'Site', 'Type', 'Seal', 'Packed By', 'Packed At', 'Status',
      'Movement', 'Asset Tag', 'Serial', 'Model'], rows);
  };
  A['export-awb'] = function () {
    var rows = S.db.movements.map(function (m) {
      var s = S.site(m.site_id);
      return [m.id, m.mode, s ? s.site : '', m.packages.join('|'), m.assets.length, m.courier_name || '', m.awb || '',
        m.vehicle || '', m.driver || '', m.gate_pass || '', m.weight || '', m.destination, m.eta || '',
        m.status, m.pod || '', m.rto ? 'Yes' : 'No', m.exception || '', m.created_at, m.created_by];
    });
    U.exportCSV('Pickup_AWB_Log', ['Movement ID', 'Mode', 'Site', 'Packages', 'Assets', 'Courier', 'AWB', 'Vehicle',
      'Driver', 'Gate Pass', 'Weight', 'Destination', 'ETA', 'Status', 'POD', 'RTO', 'Exception', 'Created', 'Created By'], rows);
  };
  A['export-wh'] = function () {
    var rows = S.db.receipts.map(function (r) {
      var s = S.site(r.site_id);
      return [r.grn, r.id, r.movement_id, s ? s.site : '', r.expected_count, r.received_count, r.variance,
        r.seal_status, r.seal_no, r.damage, r.damage_note, r.discrepancy ? 'Yes' : 'No', r.discrepancy_status,
        r.discrepancy_owner, r.resolution || '', r.received_by, r.received_at];
    });
    U.exportCSV('Warehouse_GRN', ['GRN', 'Receipt ID', 'Movement', 'Site', 'Expected', 'Received', 'Variance',
      'Seal Status', 'Seal No', 'Damage', 'Damage Note', 'Discrepancy', 'Discrepancy Status', 'Owner',
      'Resolution', 'Received By', 'Received At'], rows);
  };
  A['export-chain'] = function () {
    var rows = chainExceptions().map(function (e) {
      var a = S.asset(e.id), s = S.site(a.site_id);
      return [a.tag, a.serial, s ? s.site : '', U.status(a.status).label, e.issue, a.qc_id || '', a.package_id || '',
        a.movement_id || '', a.receipt_id || ''];
    });
    U.exportCSV('Chain_Of_Custody_Exceptions', ['Asset Tag', 'Serial', 'Site', 'Status', 'Issue', 'QC ID',
      'Package', 'Movement', 'Receipt'], rows);
  };
  A['export-mis'] = function () {
    var st = S.stats(), day = S.projectDay();
    var totals = { shipment: 0, total_ch: 0, post_ch: 0, weight: 0 };
    var rows = S.db.sites.map(function (s) {
      var a = S.assetsAt(s.id), sst = S.stats([s.id]);
      var c = s.costing || {};
      totals.shipment += c.shipment_value || 0;
      totals.total_ch += c.total_charges || 0;
      totals.post_ch += c.post_confirmation_total || 0;
      totals.weight += c.weight_kg || 0;
      return [day, s.code || '', s.state, s.city, s.site, s.format || '', s.partner, s.readiness,
        a.length, sst.qc_done, sst.accepted, sst.packed, sst.dispatched, sst.received, sst.discrepancy,
        U.pct(sst.pct_closed, 1), D.feAllocation(a.length, S.db.config).fes,
        s.tat || '', s.tat_after || '', s.tat_risk ? 'YES' : '',
        c.shipment_value || 0, c.qc_charges || 0, c.packing_charges || 0, c.weight_kg || 0,
        c.pickup_charges || 0, c.fov_charges || 0, c.total_charges || 0, c.post_confirmation_total || 0];
    });
    rows.push(['', '', '', '', 'TOTAL', '', '', '', st.total, st.qc_done, st.accepted, st.packed,
      st.dispatched, st.received, st.discrepancy, U.pct(st.pct_closed, 1), '', '', '', '',
      Math.round(totals.shipment), '', '', Math.round(totals.weight), '', '',
      Math.round(totals.total_ch), Math.round(totals.post_ch)]);
    U.exportCSV('Daily_MIS_Day' + day, ['Project Day', 'Site Code', 'State', 'City', 'Site', 'Format',
      'Executed By', 'Readiness', 'Units', 'QC Done', 'Accepted', 'Packed', 'Dispatched', 'WH Received',
      'Discrepancy', 'Closure %', 'FE Reqd', 'Source TAT', 'TAT After Halting', 'TAT Risk',
      'Value of Shipment', 'QC Charges', 'Packing Charges', 'Weight (kg)', 'Pickup Charges',
      'FOV Charges', 'Total Charges', 'Post-Confirmation Total'], rows);
  };
  A['print-esg'] = function () {
    var st = S.stats();
    var kgPer = { laptop: 2.2, desktop: 8.5, tft: 3.6 };
    var weight = 0, byCat = { laptop: 0, desktop: 0, tft: 0 };
    S.db.assets.forEach(function (a) {
      if (['received', 'received_discrepancy', 'closed'].indexOf(a.status) > -1) {
        weight += kgPer[a.category] || 3; byCat[a.category]++;
      }
    });
    U.printReport('BRSR / ESG summary',
      '<h1>BRSR / ESG Recovery Summary</h1>' +
      '<div class="sub">' + U.esc(S.db.project.name) + ' · generated Day ' + S.projectDay() + '</div>' +
      '<table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>' +
      '<tr><td>Assets in scope</td><td>' + st.total + '</td></tr>' +
      '<tr><td>Assets QC-verified</td><td>' + st.qc_done + '</td></tr>' +
      '<tr><td>Assets recovered to warehouse</td><td>' + st.received + '</td></tr>' +
      '<tr><td>Laptops recovered</td><td>' + byCat.laptop + '</td></tr>' +
      '<tr><td>Desktops recovered</td><td>' + byCat.desktop + '</td></tr>' +
      '<tr><td>TFT / monitors recovered</td><td>' + byCat.tft + '</td></tr>' +
      '<tr><td>Estimated e-waste diverted from landfill</td><td>' + weight.toFixed(1) + ' kg</td></tr>' +
      '<tr><td>Locations covered</td><td>' + S.db.sites.length + '</td></tr>' +
      '<tr><td>Chain-of-custody documented</td><td>' + U.pct(st.pct_received) + ' of scope</td></tr>' +
      '</tbody></table>' +
      '<p style="font-size:11px">Indicative weights applied per category for reporting purposes; actual weights are recorded ' +
      'at package level in the pickup / AWB module.</p>');
  };

  /* =========================================================
     SERIAL REGISTER — serial ↔ site mapping
     ========================================================= */
  Sc.serials = {
    title: 'Serial Register',
    badge: function () {
      var st = S.serialStats();
      return st.pending ? st.pending + ' pending' : 'complete';
    },
    render: function () {
      var st = S.serialStats();
      var q = (RA.filters.serQ || '').toLowerCase();
      var tab = RA.filters.serTab || 'captured';

      var h = '<div class="stats-row">' +
        '<div class="stat-card highlight"><div class="stat-val">' + st.captured.toLocaleString('en-IN') +
          '</div><div class="stat-label">Serials mapped</div></div>' +
        '<div class="stat-card"><div class="stat-val">' + st.pending.toLocaleString('en-IN') +
          '</div><div class="stat-label">Awaiting capture</div></div>' +
        '<div class="stat-card"><div class="stat-val">' + U.pct(st.total ? st.captured / st.total * 100 : 0) +
          '</div><div class="stat-label">Coverage</div></div>' +
        '<div class="stat-card"><div class="stat-val">' + S.db.sites.filter(function (s) {
            return S.serialStats(s.id).pending === 0;
          }).length + '</div><div class="stat-label">Sites complete</div></div>' +
      '</div>';

      h += tabs('serTab', tab, [['captured', 'Mapped serials'], ['sites', 'By site'], ['pending', 'Awaiting capture']]);
      h += '<div class="toolbar"><input class="input-field" id="ser-q" placeholder="Search serial, tag, site…" value="' +
        U.esc(RA.filters.serQ || '') + '" data-live="serQ" /></div>';

      if (tab === 'sites') {
        var rows = S.db.sites.filter(function (s) {
          return !q || (s.site + s.city + s.state + (s.code || '')).toLowerCase().indexOf(q) > -1;
        }).map(function (s) {
          var x = S.serialStats(s.id);
          return [
            '<a href="#/site/' + s.id + '"><b>' + U.esc(s.site) + '</b></a>',
            U.esc(s.code || ''), U.esc(s.city), U.esc(s.state),
            String(x.total), String(x.captured), String(x.pending),
            U.pill(x.pending ? U.pct(x.captured / x.total * 100, 0) : 'Complete', x.pending ? 'warn' : 'ok')
          ];
        });
        h += U.table(['Site', 'Code', 'City', 'State', 'Units', 'Mapped', 'Pending', 'Coverage'], rows,
          { icon: '🔢', emptyTitle: 'No sites match' });
      } else {
        var pool = S.db.assets.filter(function (a) {
          return tab === 'captured' ? S.hasSerial(a) : !S.hasSerial(a);
        });
        if (q) {
          pool = pool.filter(function (a) {
            var s = S.site(a.site_id);
            return (a.serial + ' ' + a.tag + ' ' + a.model + ' ' + (s ? s.site : '')).toLowerCase().indexOf(q) > -1;
          });
        }
        h += '<div class="small muted pad-x">' + pool.length.toLocaleString('en-IN') + ' unit(s)' +
          (pool.length > 200 ? ' · showing first 200' : '') + '</div>';
        var rows2 = pool.slice(0, 200).map(function (a) {
          var s = S.site(a.site_id);
          return [
            tab === 'captured' ? '<b>' + U.esc(a.serial) + '</b>' : '<span class="muted">not captured</span>',
            '<a href="#/asset/' + a.id + '">' + U.esc(a.tag) + '</a>',
            U.esc(a.model), U.esc(s ? s.site : ''), U.esc(s ? s.city : ''),
            U.statusPill(a.status),
            a.serial_captured_by ? U.esc(a.serial_captured_by) + '<div class="small muted">' +
              U.dt(a.serial_captured_at) + '</div>' : '—'
          ];
        });
        h += U.table(['Serial', 'Asset tag', 'Model', 'Site', 'City', 'Status', 'Captured by'], rows2,
          { icon: '🔢', emptyTitle: tab === 'captured' ? 'No serials captured yet' : 'Every unit has a serial' });
      }

      h += '<div class="pad-x mt8"><button class="btn btn-outline block" data-act="export-serials">' +
        '⬇ Export serial ↔ site mapping (CSV)</button>' +
        (S.can('admin') ? '<button class="btn btn-outline block mt8" data-act="goto" data-arg="#/admin">' +
          '⬆ Bulk import serials (Admin)</button>' : '') + '</div>';
      return h;
    }
  };

  A['export-serials'] = function () {
    var rows = S.db.assets.map(function (a) {
      var s = S.site(a.site_id);
      return [S.hasSerial(a) ? a.serial : '', a.tag, a.article, a.article_desc, a.model,
        D.CATEGORY_LABEL[a.category], s ? s.code : '', s ? s.site : '', s ? s.city : '', s ? s.state : '',
        a.storage_location, a.base_price, U.status(a.status).label,
        a.serial_captured_by || '', a.serial_captured_at || ''];
    });
    U.exportCSV('Serial_Site_Mapping', ['Serial', 'Asset Tag', 'Article', 'Article Description', 'Model',
      'Category', 'Site Code', 'Site', 'City', 'State', 'Storage Location', 'Base Price', 'Status',
      'Captured By', 'Captured At'], rows);
  };

  /* =========================================================
     ALERTS / NOTIFICATIONS (FR-022)
     ========================================================= */
  Sc.alerts = {
    title: 'Notifications',
    badge: function () {
      var n = S.notifications().filter(function (x) { return !x.read; }).length;
      return n ? n + ' new' : null;
    },
    render: function () {
      var n = S.notifications();
      if (!n.length) return U.empty('🔔', 'No alerts', 'All SLAs are inside target.');
      var h = '<div class="pad-x mt8"><button class="btn btn-outline sm" data-act="mark-read">Mark all read</button></div>';
      h += '<div class="card">' + n.map(function (x) {
        var inner = '<span class="notif-dot ' + x.level + '"></span>' +
          '<div class="grow"><div class="notif-title">' + U.esc(x.title) + '</div>' +
          '<div class="notif-body">' + U.esc(x.body) + '</div>' +
          (x.ts ? '<div class="notif-time">' + U.dt(x.ts) + '</div>' : '') + '</div>';
        var cls = 'notif-item' + (x.read ? '' : ' unread');
        /* no link for anything this role cannot open — see S.notifications() */
        return x.link
          ? '<a class="' + cls + '" href="' + x.link + '">' + inner + '</a>'
          : '<div class="' + cls + '">' + inner + '</div>';
      }).join('') + '</div>';
      h += '<div class="section-label">Escalation matrix (BRD Sec 15)</div><div class="card">' +
        esc('QC awaiting approval', '1 business day', 'Coordinator → Reliance SPOC', 'PMO → Reliance Project Owner', 'PMO Director → National PMO') +
        esc('Disputed QC pending', '1 business day', 'PMO → QC Approver', 'Commercial Approver', 'Reliance Commercial') +
        esc('Pickup release pending', '4 business hours', 'Coordinator follow-up', 'PMO → Reliance SPOC', 'PMO Director') +
        esc('Dispatch → WH receipt', '48h transit + 4h WH', 'Logistics checks vehicle/AWB', 'PMO transit exception', 'Director-level carrier chase') +
        esc('WH discrepancy', '1 business day', 'WH → PMO', 'PMO → QC Approver', 'Joint review') +
      '</div>';
      return h;
    }
  };
  function esc(ev, sla, l1, l2, l3) {
    return '<div class="card-row col"><div class="row-between"><b class="small">' + U.esc(ev) + '</b>' +
      U.pill(sla, 'blue') + '</div>' +
      '<div class="small muted">L1: ' + U.esc(l1) + ' → L2: ' + U.esc(l2) + ' → L3: ' + U.esc(l3) + '</div></div>';
  }
  A['mark-read'] = function () { S.markAllRead(); U.toast('All alerts marked read', 'success'); RA.render(); };

  /* =========================================================
     AUDIT LOG (FR-023)
     ========================================================= */
  Sc.audit = {
    title: 'Audit Log',
    render: function () {
      var q = (RA.filters.auditQ || '').toLowerCase();
      var list = S.db.audit.slice().reverse().filter(function (e) {
        return !q || (e.entity + e.record_id + e.action + e.user + JSON.stringify(e.meta)).toLowerCase().indexOf(q) > -1;
      });
      var h = '<div class="toolbar"><input class="input-field" id="audit-q" placeholder="Filter by entity, action, user…" value="' +
        U.esc(RA.filters.auditQ || '') + '" data-live="auditQ" /></div>';
      h += '<div class="small muted pad-x">' + list.length + ' immutable events · no delete, soft-archive only</div>';
      h += U.table(['When', 'Entity', 'Record', 'Action', 'User', 'Detail'],
        list.slice(0, 300).map(function (e) {
          return [U.dt(e.ts), U.esc(e.entity), U.esc(e.record_id), '<b>' + U.esc(e.action) + '</b>', U.esc(e.user),
            '<span class="small muted">' + U.esc(JSON.stringify(e.meta)) + '</span>'];
        }));
      h += '<div class="pad-x mt8"><button class="btn btn-outline block" data-act="export-audit">⬇ Export audit log (CSV)</button></div>';
      return h;
    }
  };
  A['export-audit'] = function () {
    var rows = S.db.audit.map(function (e) {
      return [e.ts, e.entity, e.record_id, e.action, e.user, JSON.stringify(e.meta)];
    });
    U.exportCSV('Audit_Log', ['Timestamp', 'Entity', 'Record', 'Action', 'User', 'Detail'], rows);
  };

  /* =========================================================
     ADMIN / MASTERS (FR-003, FR-012, BR-11)
     ========================================================= */
  Sc.admin = {
    title: 'Admin & Masters',
    render: function () {
      var tab = RA.filters.adminTab || 'users';
      var h = tabs('adminTab', tab, [
        ['users', 'Users & permissions'], ['charges', 'QC & charges'],
        ['serials', 'Serial mapping'], ['upload', 'Bulk upload'],
        ['deduction', 'Deduction master'], ['config', 'Configuration'],
        ['delete', 'Delete data'], ['data', 'Backup']
      ]);
      if (tab === 'deduction') h += adminDeduction();
      else if (tab === 'charges') h += adminCharges();
      else if (tab === 'upload') h += adminUpload();
      else if (tab === 'delete') h += adminDelete();
      else if (tab === 'config') h += adminConfig();
      else if (tab === 'users') h += adminUsers();
      else if (tab === 'serials') h += adminSerials();
      else h += adminData();
      return h;
    },
    mount: function () {
      var r = document.getElementById('restore-file');
      if (r) r.addEventListener('change', handleRestoreFile);
      var s = document.getElementById('serial-file');
      if (s) s.addEventListener('change', handleSerialFile);
      var si = document.getElementById('server-import');
      if (si) si.addEventListener('change', handleServerImport);
      /* Accounts are authoritative on the server — refresh on entering the tab. */
      if ((RA.filters.adminTab || 'users') === 'users' && onServer() && !RA._usersFetched) {
        RA._usersFetched = true;
        RA.session.listUsers().then(function () { RA.render(); })
          .catch(function () { RA._usersFetched = false; });
      }
      /* bulk upload — one handler per dataset */
      [['up-assets', uploadAssets], ['up-serials', uploadSerials], ['up-sites', uploadSites],
       ['up-charges', uploadCharges], ['up-users', uploadUsers]].forEach(function (pair) {
        var el = document.getElementById(pair[0]);
        if (el) el.addEventListener('change', pair[1]);
      });
    }
  };
  function tabs(key, active, items) {
    return '<div class="tabs">' + items.map(function (it) {
      return '<button class="tab' + (active === it[0] ? ' on' : '') + '" data-act="set-filter" data-k="' + key +
        '" data-v="' + it[0] + '">' + U.esc(it[1]) + '</button>';
    }).join('') + '</div>';
  }

  function adminDeduction() {
    var active = S.activeDeduction();
    var h = '<div class="card pad ' + (active.approval_status === 'Approved' ? 'ok-card' : 'warn-card') + '">' +
      '<div class="row-between"><b>' + U.esc(active.label) + '</b>' +
      U.pill(active.approval_status, active.approval_status === 'Approved' ? 'ok' : 'warn') + '</div>' +
      '<div class="small muted">Effective ' + U.esc(active.effective_from) + ' · rule ' + U.esc(active.rule) +
      (active.approved_by ? ' · approved by ' + U.esc(active.approved_by) : '') + '</div></div>';

    h += '<div class="section-label">Defect-wise deduction % — new version</div>';
    h += '<div class="card pad">' +
      '<div class="ded-grid">' + D.DEFECT_CODES.map(function (c) {
        return '<label class="ded-row"><span><b>' + U.esc(c.code) + '</b> ' + U.esc(c.label) + '</span>' +
          '<input class="input-field ded-in" type="number" min="0" max="100" step="0.5" data-ded="' + c.code +
          '" value="' + (active.rates[c.code] || 0) + '" /></label>';
      }).join('') + '</div>' +
      '<div class="grid2 mt10">' +
        U.field('Multiple-defect rule', U.select('ded-rule', [
          { v: 'highest', l: 'Highest applicable (default)' },
          { v: 'additive', l: 'Additive' },
          { v: 'capped', l: 'Additive, capped at ' + S.db.config.multi_defect_cap_pct + '%' }
        ], active.rule)) +
        U.field('Effective from', U.input('ded-eff', '', new Date().toISOString().slice(0, 10), 'date')) +
        U.field('Approved by (Reliance)', U.input('ded-appr', 'Name of approving authority', '')) +
        U.field('Approval status', U.select('ded-status', ['Draft', 'Approved'], 'Draft')) +
      '</div>' +
      '<button class="btn btn-primary block mt10" data-act="ded-publish">Publish new version</button>' +
      '<div class="small muted mt6">BR-11: a new version is created, effective-dated and retained for audit. ' +
      'Historic QC records keep the version they were priced under.</div></div>';

    h += '<div class="section-label">Version history</div><div class="card">' +
      S.db.deductions.slice().reverse().map(function (v) {
        return '<div class="card-row col"><div class="row-between"><b>v' + v.version + '</b>' +
          U.pill(v.active ? 'Active' : v.approval_status, v.active ? 'ok' : 'gray') + '</div>' +
          '<div class="small muted">Effective ' + U.esc(v.effective_from) + ' · rule ' + U.esc(v.rule) +
          ' · ' + U.esc(v.approved_by || 'unapproved') + ' · created ' + U.dt(v.created_at) + '</div>' +
          '<div class="small muted">' + Object.keys(v.rates).map(function (k) { return k + ' ' + v.rates[k] + '%'; }).join(' · ') +
          '</div></div>';
      }).join('') + '</div>';
    return h;
  }

  A['ded-publish'] = function () {
    var rates = {};
    document.querySelectorAll('[data-ded]').forEach(function (el) {
      rates[el.getAttribute('data-ded')] = Math.max(0, Math.min(100, parseFloat(el.value) || 0));
    });
    rates.OK = 0;
    var status = U.val('ded-status'), approver = U.val('ded-appr');
    if (status === 'Approved' && !approver) { U.toast('Approver name is required to publish an approved version.', 'error'); return; }
    U.confirm('Publish deduction master?',
      'This creates version ' + (S.activeDeduction().version + 1) + '. ' +
      (status === 'Approved'
        ? 'It becomes ACTIVE and re-prices all commercially-pending records.'
        : 'It is saved as a draft and does not affect pricing.'),
      function () {
        var v = S.publishDeductionVersion(rates, U.val('ded-rule'), U.val('ded-eff'), approver, status);
        U.toast('Version v' + v.version + ' published', 'success'); RA.render();
      }, 'Publish');
  };

  /* ---------------- QC & charges rate card (BRD v3 §21 costing) ---------------- */
  function adminCharges() {
    var card = S.activeRateCard();
    var t = S.chargeTotals();
    var r = card.rates;

    var h = '<div class="card pad ' + (card.approval_status === 'Approved' ? 'ok-card' : 'blue-card') + '">' +
      '<div class="row-between"><b>' + U.esc(card.label) + '</b>' +
      U.pill(card.approval_status, card.approval_status === 'Approved' ? 'ok' : 'gray') + '</div>' +
      '<div class="small muted">Effective ' + U.esc(card.effective_from) +
      (card.approved_by ? ' · approved by ' + U.esc(card.approved_by) : '') + '</div>' +
      '<div class="small muted mt6">Planning / commercial charges. Separate from the asset-condition ' +
      'deduction matrix (BRD Sec 7), which is managed under <b>Deduction master</b>.</div></div>';

    h += '<div class="metric-grid">' +
      metric(U.money(t.qc), 'QC charges') +
      metric(U.money(t.packing), 'Packing') +
      metric(U.money(t.pickup), 'Pickup') +
      metric(U.money(t.fov), 'FOV') +
      metric(U.money(t.total), 'Total charges') +
      metric(U.money(t.post), 'Post-confirmation') +
    '</div>';
    h += '<div class="card pad"><div class="kv-grid">' +
      kv('Shipment value', U.money(t.shipment)) +
      kv('Billable weight', Math.round(t.weight).toLocaleString('en-IN') + ' kg') +
      kv('Sites on manual override', String(t.overrides)) +
    '</div></div>';

    /* rate card editor, grouped */
    var groups = {};
    D.RATE_FIELDS.forEach(function (f) { (groups[f.group] = groups[f.group] || []).push(f); });
    h += '<div class="section-label">Charge logic — edit and preview</div>';
    Object.keys(groups).forEach(function (g) {
      h += '<div class="card pad"><b>' + U.esc(g) + '</b><div class="ded-grid mt8">' +
        groups[g].map(function (f) {
          return '<label class="ded-row"><span>' + U.esc(f.label) +
            ' <span class="muted">(' + U.esc(f.unit) + ')</span></span>' +
            '<input class="input-field ded-in" type="number" step="0.01" min="0" data-rate="' + f.key +
            '" value="' + r[f.key] + '" /></label>';
        }).join('') + '</div></div>';
    });

    h += '<div class="card pad blue-card small">' +
      '<b>How each charge is derived</b>' +
      '<div class="mt6">QC charge = block rate × ⌈units ÷ block size⌉ &nbsp;·&nbsp; ' +
      'Packing = rate × units &nbsp;·&nbsp; Weight = kg × units</div>' +
      '<div class="mt4">Pickup = per-unit rate × units at or above the large-site threshold, ' +
      'otherwise the single / cluster / dedicated slab</div>' +
      '<div class="mt4">FOV = % of shipment value (Σ RRP of the units at the site), where applicable</div>' +
      '<div class="mt4">Total = QC + packing + pickup + FOV &nbsp;·&nbsp; ' +
      'Post-confirmation = total + add-on</div>' +
      '<div class="mt6 muted">Reconciled against the source costing sheet: QC, packing, weight, FOV, ' +
      'total and post-confirmation match all 622 sites; pickup matches 605 — the remainder carry a metro ' +
      'premium and are held as per-site overrides.</div></div>';

    h += '<div class="pad-x">' +
      '<label class="check-row"><input type="checkbox" id="rc-overrides" /> ' +
      '<span>Also recalculate the ' + t.overrides + ' site(s) on manual override</span></label>' +
      '<div class="grid2 mt8">' +
        U.field('Effective from', U.input('rc-eff', '', new Date().toISOString().slice(0, 10), 'date')) +
        U.field('Approved by', U.input('rc-appr', 'Name of approving authority', '')) +
      '</div>' +
      '<button class="btn btn-outline block" data-act="rc-preview">🔍 Preview impact</button>' +
      '<button class="btn btn-primary block mt8" data-act="rc-publish">Publish &amp; apply rate card</button>' +
      '<button class="btn btn-outline block mt8" data-act="export-charges">⬇ Export site charges (CSV)</button>' +
      '</div>';

    h += '<div class="section-label">Rate card history</div><div class="card">' +
      S.db.rate_cards.slice().reverse().map(function (v) {
        return '<div class="card-row col"><div class="row-between"><b>v' + v.version + '</b>' +
          U.pill(v.active ? 'Active' : v.approval_status, v.active ? 'ok' : 'gray') + '</div>' +
          '<div class="small muted">Effective ' + U.esc(v.effective_from) + ' · ' +
          U.esc(v.approved_by || 'unapproved') + ' · created ' + U.dt(v.created_at) + '</div>' +
          '<div class="small muted">QC ' + U.money(v.rates.qc_block_rate) + '/' + v.rates.qc_block_units +
          'u · packing ' + U.money(v.rates.packing_per_unit) + '/u · pickup ' +
          U.money(v.rates.pickup_per_unit) + '/u ≥' + v.rates.pickup_per_unit_from +
          'u · FOV ' + v.rates.fov_pct + '%</div></div>';
      }).join('') + '</div>';
    return h;
  }

  function readRates() {
    var rates = JSON.parse(JSON.stringify(S.activeRateCard().rates));
    document.querySelectorAll('[data-rate]').forEach(function (el) {
      var v = parseFloat(el.value);
      if (!isNaN(v) && v >= 0) rates[el.getAttribute('data-rate')] = v;
    });
    return rates;
  }

  A['rc-preview'] = function () {
    var card = { version: S.activeRateCard().version + 1, rates: readRates() };
    var inc = document.getElementById('rc-overrides').checked;
    var pre = S.previewCharges(card, { includeOverrides: inc });
    var t = pre.totals;
    var rows = pre.rows.filter(function (x) { return x.delta !== 0; }).slice(0, 40).map(function (x) {
      return [U.esc(x.site.site), String(S.assetsAt(x.site.id).length),
        U.money(x.from.total_charges || 0), U.money(x.to.total_charges),
        (x.delta > 0 ? '<span class="err">+' : '<span class="ok-text">') + U.money(x.delta) + '</span>'];
    });
    U.modal({
      title: 'Impact preview',
      body: '<div class="kv-grid">' +
          kv('Sites in scope', String(pre.rows.length)) +
          kv('Sites changing', String(t.changed)) +
          kv('Skipped (override)', String(t.skipped)) +
          kv('Total now', U.money(t.oldTotal)) +
          kv('Total after', U.money(t.newTotal)) +
          kv('Difference', (t.delta > 0 ? '+' : '') + U.money(t.delta)) +
          kv('Post-confirmation now', U.money(t.oldPost)) +
          kv('Post-confirmation after', U.money(t.newPost)) +
        '</div>' +
        (rows.length ? '<div class="section-label">Largest movements</div>' +
          U.table(['Site', 'Units', 'From', 'To', 'Δ'], rows)
          : '<p class="small muted mt8">No site charges change under these rates.</p>') +
        '<p class="small muted">Nothing has been written yet — publish to apply.</p>',
      footer: '<button class="btn btn-primary" data-act="modal-close">Close</button>'
    });
  };

  A['rc-publish'] = function () {
    var rates = readRates();
    var inc = document.getElementById('rc-overrides').checked;
    var approver = U.val('rc-appr');
    if (!approver) { U.toast('Approver name is required to publish a rate card.', 'error'); return; }
    var pre = S.previewCharges({ version: 0, rates: rates }, { includeOverrides: inc });
    U.confirm('Publish rate card v' + (S.activeRateCard().version + 1) + '?',
      pre.totals.changed + ' of ' + pre.rows.length + ' site(s) will be recalculated. Total charges move from ' +
      U.money(pre.totals.oldTotal) + ' to ' + U.money(pre.totals.newTotal) + ' (' +
      (pre.totals.delta > 0 ? '+' : '') + U.money(pre.totals.delta) + '). Previous versions are retained for audit.',
      function () {
        var res = S.publishRateCard(rates, U.val('rc-eff'), approver, 'Approved', true,
          { includeOverrides: inc });
        U.toast('Rate card v' + res.card.version + ' applied to ' + res.applied + ' site(s)', 'success');
        RA.render();
      }, 'Publish & apply');
  };

  A['export-charges'] = function () {
    var rows = S.db.sites.map(function (s) {
      var c = s.costing || {};
      return [s.code || '', s.site, s.city, s.state, s.partner, S.assetsAt(s.id).length,
        c.shipment_value || 0, c.qc_charges || 0, c.packing_charges || 0, c.weight_kg || 0,
        c.pickup_charges || 0, c.fov_charges || 0, c.total_charges || 0,
        c.post_confirmation_total || 0, c.basis || 'source', c.rate_version || '',
        s.fov_applicable === false ? 'No' : 'Yes', s.tat || '', s.tat_after || ''];
    });
    U.exportCSV('Site_Charges', ['Site Code', 'Site', 'City', 'State', 'Executed By', 'Units',
      'Value of Shipment', 'QC Charges', 'Packing Charges', 'Weight (kg)', 'Pickup Charges',
      'FOV Charges', 'Total Charges', 'Post-Confirmation Total', 'Basis', 'Rate Version',
      'FOV Applicable', 'TAT', 'TAT After Halting'], rows);
  };

  /* ---------------- Bulk upload ---------------- */
  function adminUpload() {
    function block(id, icon, title, desc, cols, tmpl) {
      return '<div class="card pad">' +
        '<div class="row-between"><b>' + icon + ' ' + U.esc(title) + '</b>' +
        '<button class="btn btn-outline xs" data-act="' + tmpl + '">⬇ Template</button></div>' +
        '<div class="small muted mt4">' + desc + '</div>' +
        '<div class="small muted mt4"><b>Columns:</b> ' + U.esc(cols) + '</div>' +
        '<input type="file" id="' + id + '" accept=".csv,text/csv" class="mt8" />' +
        '<div id="' + id + '-result" class="small mt8"></div></div>';
    }
    return '<div class="card pad blue-card small">Uploads are <b>additive</b> — new rows are added and ' +
      'matching rows updated. Nothing is removed unless you use <b>Delete data</b>. Every upload is ' +
      'validated row by row, reports what it skipped and why, and is written to the audit log.</div>' +

      block('up-assets', '📦', 'Inventory / assets',
        'Adds locations and units to the database. Rows expand by Stock Quantity into individual asset records.',
        'State, City, Site, Site Description, MH Family/Class/Brick, Article, Article Description, Storage Location, Inventory Type, Stock Quantity, RRP, MRP',
        'download-template') +

      block('up-serials', '🔢', 'Serial numbers',
        'Maps serials to units. Duplicates and in-file repeats are rejected (BR-06).',
        'Serial + either Asset Tag or Site (name / code / ID), optional Article',
        'serial-template') +

      block('up-sites', '📍', 'Site details & SPOC',
        'Updates existing locations — contacts, access windows, readiness, planned dates, partner and TAT.',
        'Site, SPOC, SPOC Phone, Access Window, Readiness, Planned Date, Executed By, TAT, Blackout, Notes',
        'sites-template') +

      block('up-charges', '💰', 'Site charges',
        'Loads charges site by site. Uploaded values are held as manual overrides and excluded from ' +
        'rate-card recalculation unless you opt in.',
        'Site, QC Charges, Packing Charges, Weight, Pickup Charges, FOV Charges, Value of Shipment',
        'charges-template') +

      block('up-users', '👥', 'Users',
        'Creates or updates accounts by employee ID, including role, region and assigned sites.',
        'Name, Employee ID, Role, Region, Sites (semicolon-separated), Status',
        'users-template');
  }

  function uploadHandler(id, fn, label) {
    return function () {
      var f = this.files && this.files[0];
      if (!f) return;
      var box = document.getElementById(id + '-result');
      var reader = new FileReader();
      reader.onload = function (e) {
        try {
          var res = fn(e.target.result);
          var n = (res.created || 0) + (res.updated || 0) + (res.mapped || 0);
          box.innerHTML = '<b class="ok-text">✓ ' + label + ': ' +
            [res.created ? res.created + ' created' : '', res.updated ? res.updated + ' updated' : '',
             res.mapped ? res.mapped + ' mapped' : '', res.sitesAdded ? res.sitesAdded + ' new sites' : '']
              .filter(Boolean).join(', ') + '.</b>' +
            (res.errors && res.errors.length ? '<div class="err mt6">' + res.errors.length +
              ' row(s) skipped:<br/>' + res.errors.slice(0, 10).map(U.esc).join('<br/>') +
              (res.errors.length > 10 ? '<br/>…' : '') + '</div>' : '');
          U.toast(label + ' — ' + n + ' row(s) applied', n ? 'success' : 'warn');
          setTimeout(RA.render, 1200);
        } catch (err) {
          box.innerHTML = '<span class="err">' + U.esc(err.message) + '</span>';
        }
      };
      reader.readAsText(f);
    };
  }
  var uploadAssets  = uploadHandler('up-assets',  function (t) { return S.importAssets(t, false); }, 'Inventory');
  var uploadSerials = uploadHandler('up-serials', function (t) { return S.importSerials(t); }, 'Serials');
  var uploadSites   = uploadHandler('up-sites',   function (t) { return S.importSiteDetails(t); }, 'Site details');
  var uploadCharges = uploadHandler('up-charges', function (t) { return S.importCharges(t); }, 'Charges');
  var uploadUsers   = uploadHandler('up-users',   function (t) { return S.importUsers(t); }, 'Users');

  A['sites-template'] = function () {
    var rows = S.db.sites.slice(0, 2).map(function (s) {
      return [s.site, 'Ramesh Kadam', '+91 98200 11001', '10:00 – 18:00', 'Ready',
        new Date().toISOString().slice(0, 10), s.partner, s.tat || '', '', ''];
    });
    U.download('FieldOps_site_details_template.csv', S.toCSV(
      ['Site', 'SPOC', 'SPOC Phone', 'Access Window', 'Readiness', 'Planned Date',
       'Executed By', 'TAT', 'Blackout', 'Notes'], rows), 'text/csv');
  };
  A['charges-template'] = function () {
    var rows = S.db.sites.slice(0, 2).map(function (s) {
      var c = s.costing || {};
      return [s.site, c.qc_charges || 0, c.packing_charges || 0, c.weight_kg || 0,
        c.pickup_charges || 0, c.fov_charges || 0, c.shipment_value || 0];
    });
    U.download('FieldOps_site_charges_template.csv', S.toCSV(
      ['Site', 'QC Charges', 'Packing Charges', 'Weight', 'Pickup Charges',
       'FOV Charges', 'Value of Shipment'], rows), 'text/csv');
  };
  A['users-template'] = function () {
    var rows = S.db.users.slice(0, 3).map(function (u) {
      return [u.name, u.emp, D.ROLES[u.role].label, u.region,
        (u.sites || []).map(function (id) { var s = S.site(id); return s ? s.site : id; }).join(';'),
        u.status || 'active'];
    });
    U.download('FieldOps_users_template.csv', S.toCSV(
      ['Name', 'Employee ID', 'Role', 'Region', 'Sites', 'Status'], rows), 'text/csv');
  };

  /* ---------------- Delete data ---------------- */
  function adminDelete() {
    var q = (RA.filters.delQ || '').toLowerCase();
    var sites = S.db.sites.filter(function (s) {
      return q && (s.site + s.city + s.state + (s.code || '')).toLowerCase().indexOf(q) > -1;
    }).slice(0, 15);
    var archived = S.db.qc.filter(function (x) { return x.archived; }).length;

    return '<div class="card pad warn-card small"><b>⚠️ Deletions are permanent on this device.</b> ' +
      'Export a backup first (Backup tab). QC evidence is never hard-deleted — it is archived, ' +
      'keeping the audit trail intact per the BRD retention rule.</div>' +

      '<div class="card pad"><b>Delete a location</b>' +
      '<div class="small muted mt4">Removes the site, its units, and any packages, dispatches and receipts ' +
      'raised for it. Sites holding recorded work need the extra confirmation.</div>' +
      '<input class="input-field mt8" id="del-q" placeholder="Search the site to delete…" value="' +
        U.esc(RA.filters.delQ || '') + '" data-live="delQ" />' +
      (q ? (sites.length ? '<div class="card mt8">' + sites.map(function (s) {
        var units = S.assetsAt(s.id).length;
        var work = S.assetsAt(s.id).filter(function (a) { return S.assetDependencies(a).length; }).length;
        return '<div class="card-row"><div class="grow"><div class="row-title small">' + U.esc(s.site) + '</div>' +
          '<div class="small muted">' + U.esc(s.city + ', ' + s.state) + ' · ' + units + ' units' +
          (work ? ' · ' + work + ' with recorded work' : '') + '</div></div>' +
          '<button class="btn btn-red xs" data-act="del-site" data-arg="' + s.id + '">Delete</button></div>';
      }).join('') + '</div>' : '<div class="small muted mt8">No site matches.</div>') :
        '<div class="small muted mt8">Type to search — nothing is listed until you do.</div>') +
      '</div>' +

      '<div class="card pad"><b>Delete units</b>' +
      '<div class="small muted mt4">Removes individual assets by tag or serial (comma or newline separated). ' +
      'Units with QC or movement history are skipped unless forced.</div>' +
      '<textarea class="input-field mt8" id="del-assets" rows="3" ' +
        'placeholder="REL-8633-001, REL-8633-002 or C02XY1234ABC"></textarea>' +
      '<label class="check-row"><input type="checkbox" id="del-force" /> ' +
      '<span>Also delete their QC, packing and dispatch records</span></label>' +
      '<button class="btn btn-red block mt8" data-act="del-assets">Delete units</button></div>' +

      '<div class="card pad"><b>Archive a QC record</b>' +
      '<div class="small muted mt4">Withdraws a QC submission from the live queues and returns the unit ' +
      'to Pending QC. The record, its evidence and its audit trail are retained. ' +
      (archived ? archived + ' record(s) already archived.' : '') + '</div>' +
      '<input class="input-field mt8" id="del-qc" placeholder="QC record ID, e.g. QC-000012" />' +
      '<button class="btn btn-outline block mt8" data-act="del-qc">Archive QC record</button></div>' +

      '<div class="card pad"><b>Bulk clear</b>' +
      '<div class="small muted mt4">Resets working data while keeping the inventory master and users.</div>' +
      '<div class="btn-row mt8">' +
        '<button class="btn btn-outline sm" data-act="clear-photos">Clear photo cache</button>' +
        '<button class="btn btn-outline sm" data-act="clear-serials">Clear all serials</button>' +
        '<button class="btn btn-red sm" data-act="purge-transactions">Clear QC &amp; movements</button>' +
      '</div>' +
      '<div class="btn-row mt8">' +
        '<button class="btn btn-red sm" data-act="reset-demo">Reset everything to the source master</button>' +
      '</div></div>';
  }

  A['del-site'] = function (el) {
    var s = S.site(el.getAttribute('data-arg'));
    var units = S.assetsAt(s.id).length;
    var work = S.assetsAt(s.id).filter(function (a) { return S.assetDependencies(a).length; }).length;
    U.modal({
      title: 'Delete ' + s.site + '?',
      body: '<p class="small">' + units + ' unit(s) will be removed' +
        (work ? ', of which <b>' + work + '</b> hold QC or movement records' : '') + '.</p>' +
        (work ? '<label class="check-row"><input type="checkbox" id="ds-force" /> ' +
          '<span>Delete the recorded work as well</span></label>' : '') +
        '<div class="input-label mt8">Type the site name to confirm</div>' +
        U.input('ds-confirm', s.site, ''),
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
              '<button class="btn btn-red" id="ds-go">Delete location</button>',
      onOpen: function (host) {
        host.querySelector('#ds-go').addEventListener('click', function () {
          if (U.val('ds-confirm') !== s.site) { U.toast('Site name does not match.', 'error'); return; }
          var force = host.querySelector('#ds-force') ? host.querySelector('#ds-force').checked : false;
          try {
            var res = S.deleteSite(s.id, { force: force });
            U.closeModal();
            U.toast('Deleted ' + res.site.site + ' and ' + res.assets + ' unit(s)', 'success');
            RA.filters.delQ = '';
            RA.render();
          } catch (e) { U.toast(e.message, 'error'); }
        });
      }
    });
  };

  A['del-assets'] = function () {
    var raw = (document.getElementById('del-assets') || {}).value || '';
    var keys = raw.split(/[\n,;]+/).map(function (x) { return x.trim(); }).filter(Boolean);
    if (!keys.length) { U.toast('Enter at least one asset tag or serial.', 'error'); return; }
    var force = document.getElementById('del-force').checked;
    var ids = [], missing = [];
    keys.forEach(function (k) {
      var a = S.findBySerial(k) ||
        S.db.assets.filter(function (x) { return x.tag.toLowerCase() === k.toLowerCase(); })[0];
      if (a) ids.push(a.id); else missing.push(k);
    });
    if (!ids.length) { U.toast('No matching units found.', 'error'); return; }
    U.confirm('Delete ' + ids.length + ' unit(s)?',
      (missing.length ? missing.length + ' entry(ies) did not match and will be ignored. ' : '') +
      (force ? 'Their QC, packing and dispatch records will be deleted too. ' : '') +
      'This cannot be undone on this device.',
      function () {
        var res = S.deleteAssets(ids, { force: force });
        U.toast(res.removed + ' unit(s) deleted' +
          (res.blocked.length ? ', ' + res.blocked.length + ' skipped (recorded work)' : ''),
          res.blocked.length ? 'warn' : 'success');
        RA.render();
      }, 'Delete', true);
  };

  A['del-qc'] = function () {
    var id = U.val('del-qc');
    if (!id) { U.toast('Enter a QC record ID.', 'error'); return; }
    var q = S.qcRecord(id);
    if (!q) { U.toast('QC record ' + id + ' not found.', 'error'); return; }
    var a = S.asset(q.asset_id);
    U.modal({
      title: 'Archive ' + q.id,
      body: '<p class="small">' + U.esc(a ? a.tag + ' · ' + a.serial : '') + ' returns to Pending QC. ' +
        'The record and its evidence are retained and remain visible in the asset history.</p>' +
        U.field('Reason', U.select('aq-reason', [
          'Submitted against the wrong unit', 'Duplicate submission',
          'Evidence unusable', 'Withdrawn by PMO', 'Other'], 'Submitted against the wrong unit')),
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
              '<button class="btn btn-primary" id="aq-go">Archive record</button>',
      onOpen: function (host) {
        host.querySelector('#aq-go').addEventListener('click', function () {
          try {
            S.archiveQC(id, U.val('aq-reason'));
            U.closeModal(); U.toast(id + ' archived', 'success'); RA.render();
          } catch (e) { U.toast(e.message, 'error'); }
        });
      }
    });
  };

  A['clear-serials'] = function () {
    U.confirm('Clear every captured serial?',
      'All units return to a pending serial. QC records keep the serial they were submitted with.',
      function () { var n = S.clearSerials(); U.toast(n + ' serial(s) cleared', 'success'); RA.render(); },
      'Clear serials', true);
  };

  A['purge-transactions'] = function () {
    U.confirm('Clear all QC and movement records?',
      'Every QC record, package, dispatch and warehouse receipt is removed and all units return to ' +
      'Pending QC. Inventory, sites, serials, users and rate cards are kept.',
      function () {
        var c = S.purgeTransactions();
        U.toast('Cleared ' + c.qc + ' QC, ' + c.packages + ' packages, ' + c.movements + ' movements', 'success');
        RA.render();
      }, 'Clear working data', true);
  };

  A['download-template'] = function () {
    var headers = ['State', 'City', 'Site', 'Site Description', 'MH Family', 'MH Class', 'MH Brick', 'Article',
      'Article Description', 'Storage Location', 'Inventory Type', 'Stock Quantity', 'RRP', 'MRP', 'Serial', 'Asset Tag'];
    var rows = [
      ['Maharashtra', 'Mumbai', 'Andheri BKC Hub', 'Reliance Digital – BKC', 'IT Hardware', 'Laptop', 'Lenovo Laptop',
        'ART-1042', 'Lenovo ThinkPad X1 Carbon Laptop', 'SL-S01-01', 'Demo Unit', '1', '62000', '69000', 'LT8K2M9QAX', 'REL-S01-001'],
      ['Karnataka', 'Bengaluru', 'Bengaluru Whitefield', 'Reliance Digital – WF', 'IT Peripherals', 'TFT',
        'Dell TFT', 'ART-2210', 'Dell P2222H Monitor', 'SL-S06-02', 'Demo Unit', '3', '9800', '11500', '', '']
    ];
    U.download('FieldOps_asset_master_template.csv', S.toCSV(headers, rows), 'text/csv');
  };
  function adminConfig() {
    var c = S.db.config;
    return '<div class="card pad"><b>Logistics thresholds (FR-016)</b>' +
      '<div class="grid2 mt8">' +
        U.field('Dedicated pickup ≥', U.input('cfg-ded', '', c.logistics.dedicated_min, 'number')) +
        U.field('Cluster pickup ≥', U.input('cfg-clu', '', c.logistics.cluster_min, 'number')) +
        U.field('Courier max assets', U.input('cfg-cou', '', c.logistics.courier_max, 'number')) +
        U.field('Daily location target', U.input('cfg-loc', '', c.daily_location_target, 'number')) +
      '</div></div>' +
      '<div class="card pad"><b>QC benchmark (BRD v3)</b>' +
      '<div class="grid2 mt8">' +
        U.field('Target min / unit', U.input('cfg-qt', '', c.qc.target_min, 'number')) +
        U.field('Max min / unit', U.input('cfg-qm', '', c.qc.max_min, 'number')) +
        U.field('Supervisor alert (min)', U.input('cfg-qa', '', c.qc.alert_min, 'number')) +
        U.field('Store buffer (min)', U.input('cfg-buf', '', c.store_buffer_min, 'number')) +
      '</div></div>' +
      '<div class="card pad"><b>SLA thresholds (hours) — BRD Sec 15</b>' +
      '<div class="grid2 mt8">' +
        U.field('QC approval', U.input('cfg-sla1', '', c.sla.qc_approval_h, 'number')) +
        U.field('Dispute disposition', U.input('cfg-sla2', '', c.sla.dispute_h, 'number')) +
        U.field('Pickup release breach', U.input('cfg-sla3', '', c.sla.pickup_release_breach_h, 'number')) +
        U.field('Dispatch → WH breach', U.input('cfg-sla4', '', c.sla.wh_total_breach_h, 'number')) +
      '</div></div>' +
      '<div class="card pad"><b>Photo policy (FR-008)</b>' +
      '<div class="grid2 mt8">' +
        U.field('Max photos per QC', U.input('cfg-ph', '', c.photo.max_photos, 'number')) +
        U.field('Max pixel dimension', U.input('cfg-px', '', c.photo.max_px, 'number')) +
      '</div>' +
      '<label class="check-row mt8"><input type="checkbox" id="cfg-overall"' + (c.photo.overall_required ? ' checked' : '') +
      ' /> <span>Overall photo mandatory</span></label>' +
      '<label class="check-row"><input type="checkbox" id="cfg-defect"' + (c.photo.defect_required_for_exception ? ' checked' : '') +
      ' /> <span>Defect photo mandatory for exception codes</span></label></div>' +
      '<div class="pad-x"><button class="btn btn-primary block" data-act="cfg-save">Publish configuration</button>' +
      '<div class="small muted mt6">Configuration changes are audit-logged with user and timestamp.</div></div>';
  }
  A['cfg-save'] = function () {
    var c = S.db.config;
    var num = function (id, d) { var v = parseFloat(U.val(id)); return isNaN(v) ? d : v; };
    c.logistics.dedicated_min = num('cfg-ded', c.logistics.dedicated_min);
    c.logistics.cluster_min = num('cfg-clu', c.logistics.cluster_min);
    c.logistics.courier_max = num('cfg-cou', c.logistics.courier_max);
    c.daily_location_target = num('cfg-loc', c.daily_location_target);
    c.qc.target_min = num('cfg-qt', c.qc.target_min);
    c.qc.max_min = num('cfg-qm', c.qc.max_min);
    c.qc.alert_min = num('cfg-qa', c.qc.alert_min);
    c.store_buffer_min = num('cfg-buf', c.store_buffer_min);
    c.sla.qc_approval_h = num('cfg-sla1', c.sla.qc_approval_h);
    c.sla.dispute_h = num('cfg-sla2', c.sla.dispute_h);
    c.sla.pickup_release_breach_h = num('cfg-sla3', c.sla.pickup_release_breach_h);
    c.sla.wh_total_breach_h = num('cfg-sla4', c.sla.wh_total_breach_h);
    c.photo.max_photos = num('cfg-ph', c.photo.max_photos);
    c.photo.max_px = num('cfg-px', c.photo.max_px);
    c.photo.overall_required = document.getElementById('cfg-overall').checked;
    c.photo.defect_required_for_exception = document.getElementById('cfg-defect').checked;
    S.audit('config', 'app', 'publish', { by: (S.me() || {}).name });
    S.persist();
    U.toast('Configuration published', 'success');
    RA.render();
  };

  /* ---------------- Users & permissions (FR-002) ----------------
     Hosted, accounts live on the server and every change is authorised there;
     standalone (no API) the same screens fall back to the local store. */
  function onServer() { return RA.session && RA.session.isServer(); }

  function persistUser(payload) {
    if (onServer()) return RA.session.saveUser(payload);
    try { return Promise.resolve(S.saveUser(payload)); }
    catch (e) { return Promise.reject(e); }
  }
  function removeUser(id) {
    if (onServer()) return RA.session.deleteUser(id);
    try { S.deleteUser(id); return Promise.resolve({ ok: true }); }
    catch (e) { return Promise.reject(e); }
  }
  function afterUserChange(msg) {
    U.toast(msg, 'success');
    if (onServer()) RA.session.listUsers().then(RA.render).catch(function () { RA.render(); });
    else RA.render();
  }

  function adminUsers() {
    var q = (RA.filters.usrQ || '').toLowerCase();
    var list = S.db.users.filter(function (u) {
      return !q || (u.name + u.emp + D.ROLES[u.role].label + u.region).toLowerCase().indexOf(q) > -1;
    });
    var h = '<div class="pad-x mt8"><button class="btn btn-primary block" data-act="usr-edit" data-arg="">' +
      '+ Add user</button></div>';
    h += '<div class="toolbar"><input class="input-field" id="usr-q" placeholder="Search name, ID, role…" value="' +
      U.esc(RA.filters.usrQ || '') + '" data-live="usrQ" /></div>';

    h += '<div class="card">' + list.map(function (u) {
      var perms = u.perms || {};
      var extra = (perms.allow || []).length, revoked = (perms.deny || []).length;
      var siteNames = (u.sites || []).map(function (id) {
        var s = S.site(id); return s ? s.site : id;
      });
      return '<div class="card-row col' + (u.status === 'inactive' ? ' dim' : '') + '">' +
        '<div class="row-between"><b>' + U.esc(u.name) + '</b>' +
        U.pill(D.ROLES[u.role].label, u.status === 'inactive' ? 'gray' : 'blue') + '</div>' +
        '<div class="small muted">' + U.esc(u.emp) + ' · ' + U.esc(u.region) +
        (u.status === 'inactive' ? ' · <b>inactive</b>' : '') + '</div>' +
        '<div class="small muted">' + (siteNames.length
          ? 'Sites: ' + U.esc(siteNames.slice(0, 3).join(', ')) +
            (siteNames.length > 3 ? ' +' + (siteNames.length - 3) + ' more' : '')
          : 'Sites: per role scope') + '</div>' +
        '<div class="small">' +
          (extra ? U.pill('+' + extra + ' granted', 'ok') + ' ' : '') +
          (revoked ? U.pill('−' + revoked + ' revoked', 'fail') + ' ' : '') +
          (u.has_password === false ? U.pill('no password set', 'warn') + ' ' : '') +
          (u.must_change_password ? U.pill('must change password', 'blue') : '') +
        '</div>' +
        '<div class="btn-row mt6">' +
          '<button class="btn btn-outline xs" data-act="usr-edit" data-arg="' + u.id + '">Edit</button>' +
          '<button class="btn btn-outline xs" data-act="usr-sites" data-arg="' + u.id + '">Assign sites</button>' +
          '<button class="btn btn-outline xs" data-act="usr-perms" data-arg="' + u.id + '">Permissions</button>' +
          '<button class="btn btn-outline xs" data-act="usr-password" data-arg="' + u.id + '">Set password</button>' +
          '<button class="btn btn-outline xs" data-act="usr-toggle" data-arg="' + u.id + '">' +
            (u.status === 'inactive' ? 'Reactivate' : 'Deactivate') + '</button>' +
          '<button class="btn btn-red xs" data-act="usr-delete" data-arg="' + u.id + '">Delete</button>' +
        '</div></div>';
    }).join('') + '</div>';

    h += '<div class="card pad small muted">' + (onServer()
      ? 'Accounts live on the server. Passwords are stored as bcrypt hashes and can only be set, ' +
        'never read — use <b>Set password</b> to issue or reset one; the user is asked to change it ' +
        'at their next sign-in. Every change here is recorded in the server audit.'
      : 'Standalone mode — these accounts exist only on this device. Hosted, they are managed on ' +
        'the server with real passwords.') + '</div>';
    return h;
  }

  A['usr-edit'] = function (el) {
    var id = el.getAttribute('data-arg');
    var u = id ? S.user(id) : null;
    var regions = ['All', 'West', 'South', 'North', 'East', 'Central', 'North East'];
    U.modal({
      title: u ? 'Edit ' + u.name : 'Add user',
      body:
        U.field('Full name', U.input('ue-name', 'e.g. Rahul Verma', u ? u.name : '')) +
        U.field('Employee ID / login', U.input('ue-emp', 'e.g. qc.eng.21', u ? u.emp : '')) +
        U.field('Role', U.select('ue-role', Object.keys(D.ROLES).map(function (k) {
          return { v: k, l: D.ROLES[k].label };
        }), u ? u.role : 'fe')) +
        U.field('Region / zone', U.select('ue-region', regions, u ? u.region : 'All')) +
        U.field('Account status', U.select('ue-status', [
          { v: 'active', l: 'Active' }, { v: 'inactive', l: 'Inactive — cannot sign in' }
        ], u ? (u.status || 'active') : 'active')) +
        (u ? '' : U.field('Initial password (optional — can be set later)',
          U.input('ue-password', 'at least 8 characters', '', 'password'))) +
        '<div class="small muted">Changing the role resets module access to that role\'s default. ' +
        'Per-user grants are managed under <b>Permissions</b>.</div>',
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
              '<button class="btn btn-primary" id="ue-save">Save</button>',
      onOpen: function (host) {
        host.querySelector('#ue-save').addEventListener('click', function () {
          try {
            var roleChanged = u && u.role !== U.val('ue-role');
            var payload = {
              id: u ? u.id : null,
              name: U.val('ue-name'), username: U.val('ue-emp'), emp: U.val('ue-emp'),
              role: U.val('ue-role'), region: U.val('ue-region'),
              status: U.val('ue-status'),
              sites: u ? u.sites : [],
              allow: roleChanged ? [] : (u && u.perms ? u.perms.allow : []),
              deny: roleChanged ? [] : (u && u.perms ? u.perms.deny : [])
            };
            if (!u && U.val('ue-password')) payload.password = U.val('ue-password');
            persistUser(payload).then(function () {
              U.closeModal();
              afterUserChange(u ? 'User updated' : 'User added');
            }).catch(function (e) { U.toast(e.message, 'error'); });
          } catch (e) { U.toast(e.message, 'error'); }
        });
      }
    });
  };

  A['usr-toggle'] = function (el) {
    var u = S.user(el.getAttribute('data-arg'));
    var next = u.status === 'inactive' ? 'active' : 'inactive';
    persistUser({
      id: u.id, name: u.name, emp: u.emp, username: u.emp, role: u.role, region: u.region,
      status: next, sites: u.sites,
      allow: (u.perms || {}).allow, deny: (u.perms || {}).deny
    }).then(function () { afterUserChange(u.name + ' is now ' + next); })
      .catch(function (e) { U.toast(e.message, 'error'); });
  };

  A['usr-delete'] = function (el) {
    var u = S.user(el.getAttribute('data-arg'));
    U.confirm('Delete ' + u.name + '?',
      'The account is removed permanently. Accounts that already hold QC records must be deactivated instead.',
      function () {
        removeUser(u.id).then(function () { afterUserChange('User deleted'); })
          .catch(function (e) { U.toast(e.message, 'error'); });
      }, 'Delete', true);
  };

  /* ---- site assignment ---- */
  A['usr-sites'] = function (el) {
    var u = S.user(el.getAttribute('data-arg'));
    RA.siteSel = {};
    (u.sites || []).forEach(function (id) { RA.siteSel[id] = true; });
    RA.siteQuery = '';
    openSitePicker(u);
  };

  function openSitePicker(u) {
    var q = (RA.siteQuery || '').toLowerCase();
    var matches = S.db.sites.filter(function (s) {
      return !q || (s.site + ' ' + s.city + ' ' + s.state + ' ' + (s.code || '') + ' ' + s.partner)
        .toLowerCase().indexOf(q) > -1;
    });
    /* already-assigned sites float to the top so the selection is always visible */
    matches.sort(function (a, b) {
      return (RA.siteSel[b.id] ? 1 : 0) - (RA.siteSel[a.id] ? 1 : 0);
    });
    var chosen = Object.keys(RA.siteSel).filter(function (k) { return RA.siteSel[k]; });
    U.modal({
      title: 'Assign sites — ' + u.name,
      body:
        '<div class="small muted">' + chosen.length + ' site(s) selected · ' +
          chosen.reduce(function (t, id) { return t + S.assetsAt(id).length; }, 0) + ' units in scope</div>' +
        '<input class="input-field mt8" id="sp-q" placeholder="Search site, city, state, code…" value="' +
          U.esc(RA.siteQuery || '') + '" autocomplete="off" />' +
        '<div class="btn-row mt8">' +
          '<button class="btn btn-outline xs" id="sp-all">Select all matches (' + matches.length + ')</button>' +
          '<button class="btn btn-outline xs" id="sp-none">Clear selection</button>' +
        '</div>' +
        '<div class="site-picker mt8">' + matches.slice(0, 120).map(function (s) {
          return '<label class="picker-row"><input type="checkbox" data-site="' + s.id + '"' +
            (RA.siteSel[s.id] ? ' checked' : '') + ' />' +
            '<div class="grow"><div class="small"><b>' + U.esc(s.site) + '</b></div>' +
            '<div class="small muted">' + U.esc(s.city + ', ' + s.state) + ' · ' +
            S.assetsAt(s.id).length + ' units · ' + U.esc(s.partner) + '</div></div></label>';
        }).join('') + '</div>' +
        (matches.length > 120 ? '<div class="small muted mt6">Showing first 120 of ' + matches.length +
          ' — refine the search to reach the rest.</div>' : '') +
        '<div class="small muted mt8">Field Engineers and Reliance SPOCs see only their assigned sites. ' +
        'Coordinators, packers and warehouse users fall back to their region when nothing is assigned.</div>',
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
              '<button class="btn btn-primary" id="sp-save">Save assignment</button>',
      onOpen: function (host) {
        var qEl = host.querySelector('#sp-q');
        qEl.addEventListener('input', function () {
          RA.siteQuery = qEl.value;
          clearTimeout(RA.spT);
          RA.spT = setTimeout(function () {
            openSitePicker(u);
            var el2 = document.querySelector('#sp-q');
            if (el2) { el2.focus(); el2.setSelectionRange(el2.value.length, el2.value.length); }
          }, 240);
        });
        host.querySelectorAll('[data-site]').forEach(function (cb) {
          cb.addEventListener('change', function () {
            RA.siteSel[cb.getAttribute('data-site')] = cb.checked;
          });
        });
        host.querySelector('#sp-all').addEventListener('click', function () {
          matches.forEach(function (s) { RA.siteSel[s.id] = true; });
          openSitePicker(u);
        });
        host.querySelector('#sp-none').addEventListener('click', function () {
          RA.siteSel = {};
          openSitePicker(u);
        });
        host.querySelector('#sp-save').addEventListener('click', function () {
          var sites = Object.keys(RA.siteSel).filter(function (k) { return RA.siteSel[k]; });
          persistUser({
            id: u.id, name: u.name, emp: u.emp, username: u.emp, role: u.role, region: u.region,
            status: u.status || 'active', sites: sites,
            allow: (u.perms || {}).allow, deny: (u.perms || {}).deny
          }).then(function () {
            U.closeModal();
            afterUserChange(sites.length + ' site(s) assigned to ' + u.name);
          }).catch(function (e) { U.toast(e.message, 'error'); });
        });
      }
    });
  }

  /* ---- per-user permissions ---- */
  A['usr-perms'] = function (el) {
    var u = S.user(el.getAttribute('data-arg'));
    var perms = u.perms || { allow: [], deny: [] };
    U.modal({
      title: 'Permissions — ' + u.name,
      body:
        '<div class="small muted">Role default for <b>' + U.esc(D.ROLES[u.role].label) +
        '</b>, with per-user grants and revocations on top. Server-side enforcement in production (FR-002).</div>' +
        '<div class="perm-list mt8">' + D.MODULES.map(function (m) {
          var byRole = S.roleAllows(u.role, m.key);
          var granted = perms.allow.indexOf(m.key) > -1;
          var revoked = perms.deny.indexOf(m.key) > -1;
          var on = revoked ? false : (granted || byRole);
          return '<label class="perm-row">' +
            '<input type="checkbox" data-perm="' + m.key + '"' + (on ? ' checked' : '') + ' />' +
            '<div class="grow"><div class="small"><b>' + U.esc(m.label) + '</b></div>' +
            '<div class="small muted">' + (byRole ? 'allowed by role' : 'not in role default') +
            (granted && !byRole ? ' · granted' : '') + (revoked ? ' · revoked' : '') + '</div></div>' +
            (byRole ? U.pill('role', 'gray') : '') + '</label>';
        }).join('') + '</div>',
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
              '<button class="btn btn-primary" id="pm-save">Save permissions</button>',
      onOpen: function (host) {
        host.querySelector('#pm-save').addEventListener('click', function () {
          var allow = [], deny = [];
          host.querySelectorAll('[data-perm]').forEach(function (cb) {
            var key = cb.getAttribute('data-perm');
            var byRole = S.roleAllows(u.role, key);
            if (cb.checked && !byRole) allow.push(key);
            if (!cb.checked && byRole) deny.push(key);
          });
          persistUser({
            id: u.id, name: u.name, emp: u.emp, username: u.emp, role: u.role, region: u.region,
            status: u.status || 'active', sites: u.sites, allow: allow, deny: deny
          }).then(function () {
            U.closeModal();
            afterUserChange('Permissions updated for ' + u.name);
          }).catch(function (e) { U.toast(e.message, 'error'); });
        });
      }
    });
  };

  /* ---------------- passwords ---------------- */
  A['usr-password'] = function (el) {
    var u = S.user(el.getAttribute('data-arg'));
    if (!onServer()) { U.toast('Passwords are managed on the server; this device is standalone.', 'warn'); return; }
    U.modal({
      title: 'Set password — ' + u.name,
      body: '<p class="small muted">Issue a password for <b>' + U.esc(u.emp) + '</b>. ' +
            'They will be asked to change it the first time they sign in. ' +
            'Existing passwords cannot be read — only replaced.</p>' +
            U.field('New password', U.input('pw-new', 'at least 8 characters', '', 'password')) +
            U.field('Repeat', U.input('pw-again', '', '', 'password')),
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
              '<button class="btn btn-primary" id="pw-go">Set password</button>',
      onOpen: function (host) {
        host.querySelector('#pw-go').addEventListener('click', function () {
          var a = U.val('pw-new'), b = U.val('pw-again');
          if (a.length < 8) { U.toast('Use at least 8 characters.', 'error'); return; }
          if (a !== b) { U.toast('The two entries do not match.', 'error'); return; }
          RA.session.resetPassword(u.id, a).then(function () {
            U.closeModal();
            afterUserChange('Password set for ' + u.name);
          }).catch(function (e) { U.toast(e.message, 'error'); });
        });
      }
    });
  };

  /* Own password — also the forced change after an admin reset. */
  A['change-password'] = function (el) {
    var forced = el && el.getAttribute('data-arg') === 'forced';
    if (!onServer()) { U.toast('Passwords are managed on the server; this device is standalone.', 'warn'); return; }
    U.modal({
      title: forced ? 'Choose a new password' : 'Change password',
      body: (forced
              ? '<p class="small">Your administrator has issued this password. Choose your own to continue.</p>'
              : '') +
            (forced ? '' : U.field('Current password', U.input('cp-old', '', '', 'password'))) +
            U.field('New password', U.input('cp-new', 'at least 8 characters', '', 'password')) +
            U.field('Repeat', U.input('cp-again', '', '', 'password')),
      footer: (forced ? '' : '<button class="btn btn-outline" data-act="modal-close">Cancel</button>') +
              '<button class="btn btn-primary" id="cp-go">Save password</button>',
      onOpen: function (host) {
        host.querySelector('#cp-go').addEventListener('click', function () {
          var a = U.val('cp-new'), b = U.val('cp-again');
          if (a.length < 8) { U.toast('Use at least 8 characters.', 'error'); return; }
          if (a !== b) { U.toast('The two entries do not match.', 'error'); return; }
          RA.session.changePassword(forced ? null : U.val('cp-old'), a).then(function () {
            if (RA.session.state.user) RA.session.state.user.must_change_password = false;
            U.closeModal();
            U.toast('Password changed', 'success');
            RA.render();
          }).catch(function (e) { U.toast(e.message, 'error'); });
        });
      }
    });
  };

  /* ---------------- Serial mapping admin ---------------- */
  function adminSerials() {
    var st = S.serialStats();
    return '<div class="card pad">' +
      '<div class="row-between"><b>Serial ↔ site mapping</b>' +
      U.pill(st.captured + ' / ' + st.total, st.pending ? 'warn' : 'ok') + '</div>' +
      U.bar(st.total ? st.captured / st.total * 100 : 0, st.pending ? 'amber' : 'green') +
      '<div class="small muted mt6">The Reliance inventory carries quantity per SKU per site, not serials. ' +
      'Serials are recorded by the engineer as the first step of QC, or loaded in bulk here.</div>' +
      '<button class="btn btn-outline sm mt8" data-act="goto" data-arg="#/serials">Open serial register</button>' +
      '</div>' +

      '<div class="card pad"><b>Bulk import serials</b>' +
      '<div class="small muted mt4">CSV with a <b>Serial</b> column plus either <b>Asset Tag</b> (exact unit) or ' +
      '<b>Site</b> — site name, site code or site ID — optionally with <b>Article</b> to pick the right SKU. ' +
      'Each serial maps to the next unmapped unit that matches. Duplicates are rejected (BR-06).</div>' +
      '<input type="file" id="serial-file" accept=".csv,text/csv" class="mt10" />' +
      '<div id="serial-result" class="small mt8"></div>' +
      '<div class="btn-row mt10">' +
        '<button class="btn btn-outline sm" data-act="serial-template">⬇ CSV template</button>' +
        '<button class="btn btn-outline sm" data-act="export-serials">⬇ Export current mapping</button>' +
      '</div></div>' +

      '<div class="card pad"><b>Sites still awaiting serials</b>' +
      '<div class="small muted mt4">' + S.db.sites.filter(function (s) {
        return S.serialStats(s.id).pending > 0;
      }).length + ' of ' + S.db.sites.length + ' locations have unmapped units.</div>' +
      '<button class="btn btn-outline sm mt8" data-act="set-filter" data-k="serTab" data-v="sites">' +
      'View by site</button></div>';
  }

  A['serial-template'] = function () {
    var rows = [];
    var sample = S.db.sites.slice(0, 2);
    sample.forEach(function (s) {
      var a = S.assetsAt(s.id)[0];
      if (a) rows.push([s.site, s.code, a.article, a.tag, 'C02XX' + s.id + '001']);
    });
    if (!rows.length) rows.push(['Site name', 'Site code', 'Article', 'Asset tag', 'SERIAL123']);
    U.download('FieldOps_serial_import_template.csv',
      S.toCSV(['Site', 'Site Code', 'Article', 'Asset Tag', 'Serial'], rows), 'text/csv');
  };

  function handleSerialFile() {
    var f = this.files && this.files[0];
    if (!f) return;
    var reader = new FileReader();
    reader.onload = function (e) {
      var box = document.getElementById('serial-result');
      try {
        var res = S.importSerials(e.target.result);
        box.innerHTML = '<b class="ok-text">✓ Mapped ' + res.mapped + ' serial(s).</b>' +
          (res.errors.length ? '<div class="err mt6">' + res.errors.length + ' row(s) skipped:<br/>' +
            res.errors.slice(0, 12).map(U.esc).join('<br/>') +
            (res.errors.length > 12 ? '<br/>…' : '') + '</div>' : '');
        U.toast('Mapped ' + res.mapped + ' serial(s)', res.mapped ? 'success' : 'warn');
      } catch (err) {
        box.innerHTML = '<span class="err">' + U.esc(err.message) + '</span>';
      }
    };
    reader.readAsText(f);
  }

  function adminData() {
    var size = 0;
    try { size = (localStorage.getItem('relianceFieldOps.db.v1') || '').length; } catch (e) { }
    return '<div class="card pad"><b>Local data</b>' +
      '<div class="kv-grid mt8">' +
        kv('Assets', String(S.db.assets.length)) + kv('Sites', String(S.db.sites.length)) +
        kv('QC records', String(S.db.qc.length)) + kv('Packages', String(S.db.packages.length)) +
        kv('Movements', String(S.db.movements.length)) + kv('Receipts', String(S.db.receipts.length)) +
        kv('Audit events', String(S.db.audit.length)) + kv('Storage used', (size / 1024).toFixed(0) + ' KB') +
      '</div></div>' +
      (onServer()
        ? '<div class="card pad"><b>Shared store — bulk export &amp; import</b>' +
          '<div class="small muted mt4">Everything every device has synced, as one JSON document: ' +
          'QC records, commercial records, assets, sites, packages, movements, receipts, masters and ' +
          'the workflow audit, plus the account list (never passwords). Administrator only.</div>' +
          '<div class="btn-row mt10">' +
            '<button class="btn btn-outline sm" data-act="server-export">⬇ Export everything</button>' +
            '<label class="btn btn-outline sm">⬆ Import<input type="file" id="server-import" accept=".json" hidden /></label>' +
          '</div>' +
          '<label class="check-row mt8"><input type="checkbox" id="import-replace-server" /> ' +
          '<span>Replace the shared store instead of merging into it</span></label>' +
          '<div id="server-import-result" class="small mt8"></div></div>'
        : '') +
      '<div class="card pad"><b>This device</b>' +
      '<div class="small muted mt4">A snapshot of what this device holds — useful for support, or to ' +
      'move an offline device\'s work onto another machine.</div>' +
      '<div class="btn-row mt10">' +
        '<button class="btn btn-outline sm" data-act="backup">⬇ Export device snapshot</button>' +
        '<label class="btn btn-outline sm">⬆ Restore<input type="file" id="restore-file" accept=".json" hidden /></label>' +
      '</div></div>' +
      '<div class="card pad"><b>Danger zone</b>' +
      '<div class="btn-row mt8">' +
        '<button class="btn btn-outline sm" data-act="clear-photos">Clear photo cache</button>' +
        '<button class="btn btn-red sm" data-act="reset-demo">Reset to demo data</button>' +
      '</div></div>';
  }
  A['server-export'] = function () {
    if (!onServer()) { U.toast('No shared store on this device.', 'warn'); return; }
    U.toast('Preparing export…', 'info');
    RA.session.exportAll().then(function (data) {
      U.download('fieldops_shared_store_' +
        new Date().toISOString().slice(0, 19).replace(/[:T]/g, '') + '.json',
        JSON.stringify(data, null, 2), 'application/json');
      U.toast('Exported ' + (data.records || []).length + ' record(s) and ' +
              (data.users || []).length + ' account(s)', 'success');
    }).catch(function (e) { U.toast(e.message, 'error'); });
  };

  function handleServerImport() {
    var f = this.files && this.files[0];
    if (!f) return;
    var replace = document.getElementById('import-replace-server').checked;
    var box = document.getElementById('server-import-result');
    var reader = new FileReader();
    reader.onload = function (e) {
      var payload;
      try { payload = JSON.parse(e.target.result); }
      catch (err) { box.innerHTML = '<span class="err">That file is not valid JSON.</span>'; return; }
      var records = payload.records || payload;
      if (!Array.isArray(records)) {
        box.innerHTML = '<span class="err">No record list found in that file.</span>';
        return;
      }
      U.confirm(replace ? 'Replace the shared store?' : 'Import into the shared store?',
        records.length + ' record(s) will be ' + (replace
          ? 'loaded after clearing everything currently there. Accounts and passwords are untouched.'
          : 'merged in; existing records with the same id are overwritten.'),
        function () {
          box.innerHTML = 'Importing…';
          RA.session.importAll(records, replace).then(function (out) {
            box.innerHTML = '<b class="ok-text">✓ Loaded ' + out.loaded + ' record(s)' +
              (out.skipped ? ', skipped ' + out.skipped : '') + '.</b>';
            U.toast('Imported ' + out.loaded + ' record(s)', 'success');
            if (RA.sync) { S.db.sync.cursor = null; RA.sync.run({ full: true }); }
          }).catch(function (err) {
            box.innerHTML = '<span class="err">' + U.esc(err.message) + '</span>';
          });
        }, replace ? 'Replace' : 'Import', replace);
    };
    reader.readAsText(f);
  }

  A.backup = function () {
    U.download('fieldops_backup_' + new Date().toISOString().slice(0, 19).replace(/[:T]/g, '') + '.json',
      S.exportJSON(), 'application/json');
    U.toast('Backup downloaded', 'success');
  };
  function handleRestoreFile() {
    var f = this.files && this.files[0]; if (!f) return;
    var reader = new FileReader();
    reader.onload = function (e) {
      try { S.importJSON(e.target.result); U.toast('Backup restored', 'success'); RA.render(); }
      catch (err) { U.toast('Restore failed: ' + err.message, 'error'); }
    };
    reader.readAsText(f);
  }
  A['clear-photos'] = function () {
    U.confirm('Clear photo cache?', 'QC records are kept; only cached image data is removed from this device.', function () {
      var n = 0;
      S.db.qc.forEach(function (q) { (q.photos || []).forEach(function (p) { if (p.data) { p.data = null; p.shed = true; n++; } }); });
      S.persist(); U.toast(n + ' photo(s) cleared', 'success'); RA.render();
    }, 'Clear', true);
  };
  A['reset-demo'] = function () {
    U.confirm('Reset all data?', 'Every QC record, package, dispatch and receipt on this device will be deleted and demo data restored.',
      function () { S.reset(); U.toast('Reset to demo data', 'success'); location.hash = '#/dashboard'; RA.render(); }, 'Reset', true);
  };

  /* =========================================================
     PROFILE
     ========================================================= */
  Sc.profile = {
    title: 'Profile',
    render: function () {
      var me = S.me(), r = D.ROLES[me.role];
      var pending = S.pendingSync().length;
      return '<div class="card pad">' +
        '<div class="avatar">' + U.esc(me.name.charAt(0)) + '</div>' +
        '<div class="row-between mt8"><b>' + U.esc(me.name) + '</b>' + U.pill(r.label, 'blue') + '</div>' +
        '<div class="kv-grid mt8">' +
          kv('Employee ID', me.emp) + kv('Region', me.region) +
          kv('Data access', r.scope) + kv('Assigned sites', me.sites.length ? me.sites.join(', ') : 'Per role scope') +
        '</div></div>' +
        (RA.session && RA.session.isServer()
          ? '<div class="card pad"><b>Sign-in</b>' +
            '<div class="kv-grid mt8">' +
              kv('Username', me.emp) +
              kv('Signed in as', D.ROLES[me.role].label) +
              kv('Last sign-in', (RA.session.state.user && RA.session.state.user.last_login)
                ? U.dt(RA.session.state.user.last_login) : 'first session') +
            '</div>' +
            '<button class="btn btn-outline sm mt10" data-act="change-password">Change my password</button>' +
            '<div class="small muted mt6">Your account, role and site assignments are issued by an ' +
            'administrator. Passwords are stored hashed and can never be read back.</div></div>'
          : '<div class="card pad warn-card small"><b>Standalone mode.</b> No server session — this ' +
            'device is running on its own, with no shared store and no server accounts.</div>') +
        '<div class="card pad"><b>Device & sync</b>' +
        '<div class="kv-grid mt8">' +
          kv('Connection', navigator.onLine ? 'Online' : 'Offline') +
          kv('Pending sync', String(pending)) +
          kv('App version', '3.0.0 (PWA)') +
          kv('Install', window.matchMedia('(display-mode: standalone)').matches ? 'Installed' : 'Browser') +
        '</div>' +
        '<div class="btn-row mt10">' +
          '<button class="btn btn-outline sm" data-act="sync-now">Sync now</button>' +
          '<button class="btn btn-outline sm" data-act="install-app">📲 Install app</button>' +
        '</div></div>' +
        '<div class="card pad"><b>My access</b>' +
        '<div class="small muted mt4">Modules available to this account:</div>' +
        '<div class="chips mt6">' + D.MODULES.filter(function (m) { return S.can(m.key); })
          .map(function (m) {
            var byRole = S.roleAllows(me.role, m.key);
            return U.pill(m.label, byRole ? 'blue' : 'ok');
          }).join('') + '</div>' +
        (((me.perms || {}).allow || []).length || ((me.perms || {}).deny || []).length
          ? '<div class="small muted mt6">Includes administrator adjustments to the role default.</div>' : '') +
        '</div>' +
        '<div class="pad-x"><button class="btn btn-red block" data-act="logout">Sign out</button></div>';
    }
  };
  A['install-app'] = function () {
    if (RA.deferredPrompt) {
      RA.deferredPrompt.prompt();
      RA.deferredPrompt = null;
    } else {
      U.modal({
        title: 'Install FieldOps',
        body: '<p class="small"><b>Android / Chrome:</b> menu ⋮ → “Add to Home screen”.</p>' +
              '<p class="small mt6"><b>iPhone / Safari:</b> Share ⬆ → “Add to Home Screen”.</p>' +
              '<p class="small mt6"><b>Desktop:</b> install icon in the address bar.</p>' +
              '<p class="small muted mt6">The app then opens full-screen and works offline.</p>',
        footer: '<button class="btn btn-primary" data-act="modal-close">Got it</button>'
      });
    }
  };

})(window.RA = window.RA || {});
