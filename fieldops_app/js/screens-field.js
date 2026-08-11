/* ============================================================
   Reliance Asset FieldOps — Field screens
   Login · My Day · Sites · Site Job · Scan · Rapid QC · Asset
   ============================================================ */
(function (RA) {
  'use strict';
  var U = RA.ui, S = RA.store, D = RA.data;
  var Sc = RA.screens = RA.screens || {};
  var A = RA.actions = RA.actions || {};

  /* =========================================================
     LOGIN
     ========================================================= */
  Sc.login = {
    chrome: false,
    title: 'Sign In',
    render: function () {
      var users = S.db.users;
      return '' +
      '<div class="login-bg">' +
        '<div class="login-inner">' +
          '<div class="login-logo">📦</div>' +
          '<div class="login-title">FieldOps</div>' +
          '<div class="login-sub">Reliance Asset QC &amp; Logistics Portal</div>' +
          '<div class="login-card">' +
            '<label class="input-label">Employee ID / Email</label>' +
            '<select class="input-field" id="login-user">' +
              users.map(function (u) {
                return '<option value="' + u.id + '">' + U.esc(u.emp) + ' — ' + U.esc(u.name) +
                  ' (' + U.esc(D.ROLES[u.role].label) + ')</option>';
              }).join('') +
            '</select>' +
            '<label class="input-label" style="margin-top:10px">PIN</label>' +
            '<input class="input-field" id="login-pin" type="password" inputmode="numeric" maxlength="6" value="1234" />' +
            '<label class="check-row"><input type="checkbox" id="login-remember" checked /> ' +
              '<span>Remember me on this device</span></label>' +
            '<button class="btn btn-primary block" data-act="login">Sign In →</button>' +
            '<div class="login-hint">Standalone mode — no server reachable, so this device is ' +
            'running on its own. Hosted, sign-in is issued by your administrator.</div>' +
          '</div>' +
          '<div class="login-footer">DEV IT / Deshwal PMO · BRD v3.0 Source-Aligned<br/>' +
            'Project ' + U.esc(S.db.project.project_id) + ' · ' + S.db.project.scope_assets.toLocaleString('en-IN') +
            ' assets · ' + S.db.project.scope_locations + ' locations · 45-day baseline</div>' +
        '</div>' +
      '</div>';
    }
  };

  A.login = function () {
    var id = U.val('login-user'), pin = U.val('login-pin');
    if (pin !== '1234') { U.toast('Incorrect PIN. Demo PIN is 1234.', 'error'); return; }
    var sess = S.login(id, document.getElementById('login-remember').checked);
    if (!sess) { U.toast('User not found', 'error'); return; }
    S.persist();
    var me = S.me();
    U.toast('Signed in as ' + me.name, 'success');
    location.hash = D.ROLES[me.role].home;
    RA.render();
  };

  A.logout = function () {
    U.confirm('Sign out?',
      'Captured work already synced stays in the shared store. Anything still queued on ' +
      'this device will send the next time you sign in.',
      function () {
        if (RA.session) RA.session.logout();
        else { S.logout(); location.hash = '#/login'; RA.render(); }
      }, 'Sign out');
  };

  /* =========================================================
     MY DAY (BRD Sec 9 — My Day)
     ========================================================= */
  Sc.myday = {
    title: 'My Day',
    badge: function () { return 'Day ' + S.projectDay(); },
    render: function () {
      var me = S.me();
      var sites = S.mySites();
      var todayQC = S.todayQC().filter(function (q) { return q.engineer_id === me.id || me.role !== 'fe'; });
      var pending = S.pendingSync().length;
      var scopeIds = sites.map(function (s) { return s.id; });
      var st = S.stats(scopeIds);
      var mins = todayQC.reduce(function (a, q) { return a + q.seconds; }, 0) / 60;
      var avg = todayQC.length ? (mins / todayQC.length) : 0;

      var h = '';
      h += '<div class="stats-row">' +
        stat(todayQC.length, "Units QC'd today", 'highlight') +
        stat(st.qc_done + ' / ' + st.total, 'My scope progress') +
        stat(sites.filter(function (s) { return s.status === 'In Progress'; }).length, 'Sites active') +
        stat(avg ? avg.toFixed(1) + 'm' : '—', 'Avg min / unit') +
      '</div>';

      var bench = S.db.config.qc;
      h += '<div class="card pad">' +
        '<div class="row-between"><span class="small muted">QC benchmark (BRD v3)</span>' +
        '<b class="small">' + bench.target_min + '–' + bench.max_min + ' min / laptop</b></div>' +
        U.bar(Math.min(100, avg / bench.max_min * 100), avg <= bench.max_min ? 'green' : 'amber') +
        '<div class="small muted mt6">' + (avg ? (avg <= bench.max_min ?
          '✓ Within benchmark' : '⚠ Above benchmark — check for rework or complex units') :
          'No QC recorded today yet') + '</div></div>';

      if (pending) {
        h += '<div class="card pad warn-card">' +
          '<b>⏳ ' + pending + ' record(s) pending sync</b>' +
          '<div class="small muted">Captured offline. They will upload when the connection is restored.</div>' +
          '<button class="btn btn-outline sm mt8" data-act="sync-now">Sync now</button></div>';
      }

      h += '<div class="section-label">My sites — today</div>';
      if (!sites.length) h += U.empty('📍', 'No sites assigned', 'Ask your Regional Coordinator for an assignment.');
      else {
        h += '<div class="card">' + sites.map(function (s) {
          var a = S.assetsAt(s.id);
          var done = a.filter(function (x) { return x.status !== 'pending_qc'; }).length;
          var fe = D.feAllocation(a.length, S.db.config);
          return '<a class="card-row link" href="#/site/' + s.id + '">' +
            '<div class="grow">' +
              '<div class="row-title">' + U.esc(s.site) + '</div>' +
              '<div class="small muted">' + U.esc(s.city) + ' · ' + a.length + ' units · SPOC ' + U.esc(s.spoc || '—') + '</div>' +
              '<div class="small muted">Plan: ' + fe.fes + ' FE · ' + fe.window + ' · ' + done + '/' + a.length + ' done</div>' +
              U.bar(a.length ? done / a.length * 100 : 0, 'green') +
            '</div>' +
            '<div class="col-right">' + readinessPill(s) + '</div></a>';
        }).join('') + '</div>';
      }

      h += '<div class="section-label">Quick actions</div>' +
        '<div class="quick-grid">' +
          (sites[0] ? qa('🔢', 'Capture serial', 'goto', '#/serial/' + sites[0].id) : qa('🔢', 'Capture serial', 'goto', '#/sites')) +
          qa('🔍', 'Find asset', 'goto', '#/scan') +
          qa('📦', 'Packing', 'goto', '#/packing') +
          qa('🔔', 'Alerts', 'goto', '#/alerts') +
        '</div>';
      return h;
    }
  };

  function stat(v, l, cls) {
    return '<div class="stat-card ' + (cls || '') + '"><div class="stat-val">' + v + '</div>' +
      '<div class="stat-label">' + U.esc(l) + '</div></div>';
  }
  function qa(icon, label, act, arg) {
    return '<button class="quick-btn" data-act="' + act + '"' + (arg ? ' data-arg="' + arg + '"' : '') + '>' +
      '<span class="qa-icon">' + icon + '</span><span>' + U.esc(label) + '</span></button>';
  }
  function readinessPill(s) {
    if (s.readiness === 'Ready') return U.pill('Ready', 'ok');
    if (s.readiness === 'Pending') return U.pill('Readiness ?', 'warn');
    return U.pill(s.readiness, 'gray');
  }

  A['sync-now'] = function () { S.syncNow(); };   // sync.js reports the outcome
  A.goto = function (el) { location.hash = el.getAttribute('data-arg'); };

  /* =========================================================
     SITES LIST
     ========================================================= */
  Sc.sites = {
    title: 'Sites',
    render: function () {
      var sites = S.mySites();
      var q = (RA.filters.siteQ || '').toLowerCase();
      var list = sites.filter(function (s) {
        return !q || (s.site + s.city + s.state + s.spoc).toLowerCase().indexOf(q) > -1;
      });
      var h = '<div class="toolbar">' +
        '<input class="input-field" id="site-q" placeholder="Search site, city, SPOC…" value="' + U.esc(RA.filters.siteQ || '') + '" data-live="siteQ" />' +
        '</div>';
      h += '<div class="small muted pad-x">' + list.length + ' of ' + sites.length + ' sites · ' +
        S.db.project.scope_locations + ' in project scope</div>';
      h += '<div class="card">' + list.map(function (s) {
        var a = S.assetsAt(s.id);
        var done = a.filter(function (x) { return x.status !== 'pending_qc'; }).length;
        return '<a class="card-row link" href="#/site/' + s.id + '">' +
          '<div class="grow"><div class="row-title">' + U.esc(s.site) + '</div>' +
          '<div class="small muted">' + U.esc(s.city) + ', ' + U.esc(s.state) + ' · ' + U.esc(s.partner) +
          ' · TAT ' + U.esc(s.tat || '—') + (s.tat_risk ? ' ⚠' : '') + '</div>' +
          '<div class="small muted">' + done + '/' + a.length + ' QC · ' + U.esc(s.status) + '</div></div>' +
          '<div class="col-right">' + readinessPill(s) + '</div></a>';
      }).join('') + '</div>';
      return h;
    }
  };

  /* =========================================================
     SITE JOB (BRD FR-004 + v3 FE allocation)
     ========================================================= */
  Sc.site = {
    title: function (p) { var s = S.site(p[0]); return s ? s.site : 'Site'; },
    back: '#/sites',
    render: function (p) {
      var s = S.site(p[0]);
      if (!s) return U.empty('❓', 'Site not found', '');
      var assets = S.assetsAt(s.id);
      var st = S.stats([s.id]);
      var fe = D.feAllocation(assets.length, S.db.config);
      var mode = D.logisticsMode(assets.filter(function (a) { return a.status === 'accepted' || a.status === 'packed'; }).length, S.db.config);
      var canQC = S.can('qc');

      var h = '';
      h += '<div class="card pad">' +
        '<div class="row-between"><b>' + U.esc(s.site_desc) + '</b>' + readinessPill(s) + '</div>' +
        '<div class="small muted mt4">' + U.esc(s.address) + '</div>' +
        '<div class="kv-grid mt8">' +
          kv('SPOC', s.spoc || '—') + kv('Access window', s.access_window) +
          kv('Planned date', s.planned_date || '—') + kv('Executing partner', s.partner) +
          kv('Zone', s.region) + kv('Site TAT (source)', s.tat || '—') +
          kv('TAT after halting', s.tat_after || '—') + kv('Site code', s.code || '—') +
          kv('Store format', s.format || '—') +
        '</div>' +
        '<div class="btn-row mt10">' +
          (s.spoc_phone ? '<a class="btn btn-outline sm" href="tel:' + U.esc(s.spoc_phone.replace(/\s/g, '')) + '">📞 Call SPOC</a>' : '') +
          '<a class="btn btn-outline sm" target="_blank" rel="noopener" href="https://www.google.com/maps/search/?api=1&query=' +
            encodeURIComponent(s.address) + '">🗺️ Navigate</a>' +
          (S.can('site') && ['coord', 'pmo', 'admin', 'spoc'].indexOf(S.me().role) > -1 ?
            '<button class="btn btn-outline sm" data-act="site-readiness" data-arg="' + s.id + '">✓ Set readiness</button>' : '') +
        '</div>' +
      '</div>';

      h += '<div class="card pad accent">' +
        '<div class="row-between"><b>Recommended FE allocation</b>' + U.pill('BRD v3', 'blue') + '</div>' +
        '<div class="big-num">' + fe.fes + ' <span class="unit">FE</span> · ' + fe.window + '</div>' +
        '<div class="small muted">' + U.esc(fe.note) + ' → planned on-site ' + fe.total_hours + ' h</div>' +
      '</div>';

      if (s.tat_risk) {
        h += '<div class="card pad fail-card small"><b>⚠ TAT risk</b> — source TAT for this site is ' +
          U.esc(s.tat || '—') + (s.tat_after ? ' (' + U.esc(s.tat_after) + ' after halting)' : '') +
          ', which runs against the Day-45 critical path.</div>';
      }

      var c = s.costing || {};
      if (c.total_charges) {
        var basisLabel = { source: 'Source workbook', 'rate-card': 'Rate card v' + (c.rate_version || ''), override: 'Manual override' };
        h += '<div class="section-label">Planning &amp; costing</div>' +
          '<div class="card pad">' +
          '<div class="row-between mb6"><span class="small muted">Basis</span>' +
          U.pill(basisLabel[c.basis] || 'Source workbook', c.basis === 'override' ? 'warn' : 'blue') + '</div>' +
          '<div class="kv-grid">' +
            kv('Value of shipment', U.money(c.shipment_value)) +
            kv('QC charges', U.money(c.qc_charges)) +
            kv('Packing charges', U.money(c.packing_charges)) +
            kv('Weight', (c.weight_kg || 0) + ' kg') +
            kv('Pickup charges', U.money(c.pickup_charges)) +
            kv('FOV charges', U.money(c.fov_charges)) +
            kv('Total charges', U.money(c.total_charges)) +
            kv('Post-confirmation total', U.money(c.post_confirmation_total)) +
          '</div>' +
          '<div class="small muted mt6">Planning / commercial inputs — separate from asset-condition price ' +
          'deductions (BRD v3 §21).</div></div>';
      }

      h += '<div class="stats-row">' +
        stat(assets.length, 'Units at site') +
        stat(st.qc_done, 'QC done', 'highlight') +
        stat(st.accepted, 'Accepted') +
        stat(st.dispatched, 'Dispatched') +
      '</div>';

      h += '<div class="card pad">' +
        '<div class="row-between"><span class="small muted">Recommended logistics mode</span>' +
        U.pill(mode.label, 'blue') + '</div>' +
        '<div class="small muted">' + U.esc(mode.rule) + ' · ' +
        assets.filter(function (a) { return a.status === 'accepted'; }).length + ' released now</div></div>';

      var ser = S.serialStats(s.id);
      h += '<div class="card pad">' +
        '<div class="row-between"><b>Serial mapping</b>' +
        U.pill(ser.captured + ' / ' + ser.total, ser.pending ? 'warn' : 'ok') + '</div>' +
        U.bar(ser.total ? ser.captured / ser.total * 100 : 0, ser.pending ? 'amber' : 'green') +
        '<div class="small muted mt6">' + ser.pending + ' unit(s) still awaiting a serial. ' +
        'Serials are read off the device and mapped to this site as QC starts.</div></div>';

      if (canQC) {
        h += '<div class="pad-x mt8"><button class="btn btn-green block" data-act="goto" data-arg="#/serial/' + s.id + '">' +
          '▶ Start QC — capture serial</button>' +
          '<button class="btn btn-outline block mt8" data-act="goto" data-arg="#/scan/' + s.id + '">' +
          '🔍 Browse site inventory</button></div>';
      }

      h += '<div class="section-label">Asset inventory</div>';
      var q = (RA.filters.assetQ || '').toLowerCase();
      h += '<div class="toolbar"><input class="input-field" id="asset-q" placeholder="Filter by serial, tag, model…" value="' +
        U.esc(RA.filters.assetQ || '') + '" data-live="assetQ" /></div>';
      var shown = assets.filter(function (a) {
        return !q || (a.serial + a.tag + a.model + a.make).toLowerCase().indexOf(q) > -1;
      }).slice(0, 200);
      h += '<div class="card">' + shown.map(function (a) {
        return '<a class="card-row link" href="#/asset/' + a.id + '">' +
          '<div class="grow"><div class="row-title">' + U.esc(a.tag) + ' · ' + U.esc(a.serial) + '</div>' +
          '<div class="small muted">' + U.esc(a.make + ' ' + a.model) + ' · ' + U.esc(D.CATEGORY_LABEL[a.category]) +
          ' · ' + U.money(a.base_price) + '</div></div>' +
          '<div class="col-right">' + U.statusPill(a.status) + '</div></a>';
      }).join('') + '</div>';
      if (assets.length > 200) h += '<div class="small muted pad-x">Showing first 200 of ' + assets.length + '.</div>';
      return h;
    }
  };
  function kv(k, v) { return '<div class="kv"><div class="k">' + U.esc(k) + '</div><div class="v">' + U.esc(v) + '</div></div>'; }

  A['site-readiness'] = function (el) {
    var s = S.site(el.getAttribute('data-arg'));
    U.modal({
      title: 'Site readiness — ' + s.site,
      body: U.field('Readiness status', U.select('rd-status', ['Ready', 'Pending', 'Blocked'], s.readiness)) +
            U.field('Access window', U.input('rd-window', '10:00 – 18:00', s.access_window)) +
            U.field('Planned date', U.input('rd-date', '', s.planned_date, 'date')) +
            U.field('Notes / blackout dates', U.input('rd-notes', 'Optional', s.notes)),
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
              '<button class="btn btn-primary" id="rd-save">Save</button>',
      onOpen: function (host) {
        host.querySelector('#rd-save').addEventListener('click', function () {
          s.readiness = U.val('rd-status'); s.access_window = U.val('rd-window');
          s.planned_date = U.val('rd-date'); s.notes = U.val('rd-notes');
          S.audit('site', s.id, 'readiness', { status: s.readiness });
          S.persist(); U.closeModal(); U.toast('Site updated', 'success'); RA.render();
        });
      }
    });
  };

  /* =========================================================
     SCAN / FIND ASSET (BRD FR-005)
     ========================================================= */
  Sc.scan = {
    title: 'Scan / Find Asset',
    render: function (p) {
      var siteId = p[0] || null;
      var site = siteId ? S.site(siteId) : null;
      var q = RA.filters.scanQ || '';
      var results = S.searchAssets(q, siteId);
      var h = '';
      h += '<div class="pad-x mt8"><button class="btn btn-primary block" data-act="scan-open"' +
        (siteId ? ' data-arg="' + siteId + '"' : '') + '>📷 Scan QR / Barcode</button></div>';
      h += '<div class="toolbar"><input class="input-field" id="scan-q" placeholder="Serial, asset tag or model…" value="' +
        U.esc(q) + '" data-live="scanQ" autocomplete="off" /></div>';
      if (site) h += '<div class="small muted pad-x">Scoped to ' + U.esc(site.site) + ' · ' + results.length + ' match(es)</div>';
      else h += '<div class="small muted pad-x">' + results.length + ' match(es) across all assigned sites</div>';

      h += '<div class="card">' + results.map(function (a) {
        var s = S.site(a.site_id);
        return '<a class="card-row link" href="#/asset/' + a.id + '">' +
          '<div class="grow"><div class="row-title">' + U.esc(a.serial) + '</div>' +
          '<div class="small muted">' + U.esc(a.tag) + ' · ' + U.esc(a.make + ' ' + a.model) + '</div>' +
          '<div class="small muted">' + U.esc(s ? s.site : '') + '</div></div>' +
          '<div class="col-right">' + U.statusPill(a.status) + '</div></a>';
      }).join('') + '</div>';
      if (!results.length) h += U.empty('🔍', 'No asset found', 'Check the serial, or scan the tag on the device.');
      return h;
    }
  };

  A['scan-open'] = function (el) {
    var siteId = el && el.getAttribute('data-arg');
    U.scan(function (code) {
      if (!code) return;
      var found = S.searchAssets(code, siteId);
      if (!found.length) { U.toast('No asset matches "' + code + '"', 'warn'); RA.filters.scanQ = code; location.hash = '#/scan'; RA.render(); return; }
      location.hash = '#/asset/' + found[0].id;
      RA.render();
    });
  };

  /* =========================================================
     ASSET DETAIL
     ========================================================= */
  Sc.asset = {
    title: function (p) { var a = S.asset(p[0]); return a ? a.tag : 'Asset'; },
    render: function (p) {
      var a = S.asset(p[0]);
      if (!a) return U.empty('❓', 'Asset not found', '');
      var site = S.site(a.site_id);
      var history = S.qcForAsset(a.id);
      var dupes = S.duplicateCheck(a);
      var h = '';

      if (dupes.length) {
        h += '<div class="card pad fail-card"><b>⚠️ BR-06: duplicate serial / tag detected</b>' +
          '<div class="small">Also present at: ' + dupes.map(function (d) {
            var s = S.site(d.site_id); return U.esc((s ? s.site : d.site_id) + ' (' + d.tag + ')');
          }).join(', ') + '. Supervisor review required.</div></div>';
      }

      h += '<div class="card pad">' +
        '<div class="row-between"><b>' + U.esc(a.make + ' ' + a.model) + '</b>' + U.statusPill(a.status) + '</div>' +
        '<div class="kv-grid mt8">' +
          kv('Serial', a.serial) + kv('Asset tag', a.tag) +
          kv('Category', D.CATEGORY_LABEL[a.category]) + kv('Site', site ? site.site : '—') +
          kv('Storage location', a.storage_location || '—') + kv('Inventory type', a.inventory_type || '—') +
          kv('Base / agreed price', U.money(a.base_price)) + kv('MRP', U.money(a.mrp)) +
        '</div></div>';

      if (a.status === 'pending_qc' && S.can('qc')) {
        h += '<div class="pad-x"><button class="btn btn-green block" data-act="goto" data-arg="#/qc/' + a.id + '">' +
          '▶ Start Rapid QC</button></div>';
      }

      if (history.length) {
        h += '<div class="section-label">QC history (immutable — BR-05)</div><div class="card">';
        history.forEach(function (q) {
          var cm = S.commercialFor(q.id);
          h += '<div class="card-row col">' +
            '<div class="row-between"><b>' + U.esc(q.id) + ' · v' + q.version + '</b>' + U.statusPill(q.status) + '</div>' +
            '<div class="small muted">' + U.esc(q.codes.join(' + ')) + ' · ' + U.mmss(q.seconds) +
            ' · ' + U.esc(q.engineer) + ' · ' + U.dt(q.submitted_at) + '</div>' +
            (cm ? '<div class="small muted">Base ' + U.money(cm.base_price) + ' · deduction ' + cm.deduction_pct +
              '% (' + U.money(cm.deduction_amount) + ') · revised <b>' + U.money(cm.revised_price) + '</b></div>' : '') +
            (q.reason ? '<div class="small">Reason: ' + U.esc(q.reason) + '</div>' : '') +
            (q.photos && q.photos.length ? '<div class="thumbs mt6">' + q.photos.map(function (ph) {
              return ph.data ? '<img class="thumb" src="' + ph.data + '" alt="' + U.esc(ph.kind) + '" />'
                             : '<div class="thumb ph">🗜️</div>';
            }).join('') + '</div>' : '') +
          '</div>';
        });
        h += '</div>';
      }

      /* chain of custody */
      h += '<div class="section-label">Chain of custody</div><div class="card">';
      h += chainRow('QC submitted', a.qc_id ? 'ok' : 'pending', a.qc_id || 'Pending');
      var q0 = a.qc_id ? S.qcRecord(a.qc_id) : null;
      h += chainRow('Reliance acceptance', q0 && q0.status === 'accepted' ? 'ok' : 'pending', q0 ? U.status(q0.status).label : 'Pending');
      h += chainRow('Packed', a.package_id ? 'ok' : 'pending', a.package_id || 'Pending');
      h += chainRow('Dispatched', a.movement_id ? 'ok' : 'pending', a.movement_id || 'Pending');
      h += chainRow('Warehouse receipt', a.receipt_id ? 'ok' : 'pending', a.receipt_id ?
        (S.db.receipts.filter(function (r) { return r.id === a.receipt_id; })[0] || {}).grn : 'Pending');
      h += '</div>';

      var chk = S.closureCheck(a);
      if (['pmo', 'admin'].indexOf(S.me().role) > -1 && a.status !== 'closed') {
        h += '<div class="pad-x mt8">' +
          '<button class="btn ' + (chk.ok ? 'btn-primary' : 'btn-disabled') + ' block" data-act="close-asset" data-arg="' + a.id + '"' +
          (chk.ok ? '' : ' disabled') + '>🔒 Close asset (BR-12)</button>' +
          (chk.ok ? '' : '<div class="small muted mt6">' + chk.blockers.map(U.esc).join('<br/>') + '</div>') +
          '</div>';
      }
      return h;
    }
  };
  function chainRow(label, state, val) {
    return '<div class="card-row"><span class="chain-dot ' + state + '"></span>' +
      '<div class="grow"><div class="row-title small">' + U.esc(label) + '</div>' +
      '<div class="small muted">' + U.esc(val || '—') + '</div></div></div>';
  }
  A['close-asset'] = function (el) {
    try { S.closeAsset(el.getAttribute('data-arg')); U.toast('Asset closed', 'success'); RA.render(); }
    catch (e) { U.toast(e.message, 'error'); }
  };

  /* =========================================================
     SERIAL CAPTURE — the first step of every QC (FR-005, BR-06)
     The source inventory carries quantities per SKU per site, not serials.
     The engineer reads the serial off the device, the app maps it to a unit
     of that model at this site, and only then opens the QC form.
     ========================================================= */
  RA.serialState = null;

  Sc.serial = {
    title: 'Capture Serial',
    render: function (p) {
      var siteId = p[0];
      var site = S.site(siteId);
      if (!site) return U.empty('❓', 'Site not found', '');
      if (!RA.serialState || RA.serialState.site_id !== siteId) {
        RA.serialState = { site_id: siteId, serial: '', step: 'entry', error: '' };
      }
      var st = RA.serialState;
      var stats = S.serialStats(siteId);
      var groups = S.pendingSerialGroups(siteId);

      var h = '';
      h += '<div class="card pad">' +
        '<div class="row-between"><b>' + U.esc(site.site) + '</b>' +
        U.pill(stats.captured + ' / ' + stats.total + ' mapped', stats.pending ? 'warn' : 'ok') + '</div>' +
        '<div class="small muted">' + U.esc(site.city + ', ' + site.state) + ' · site code ' + U.esc(site.code || '—') + '</div>' +
        U.bar(stats.total ? stats.captured / stats.total * 100 : 0, 'green') +
      '</div>';

      /* ---- step 1: read the serial ---- */
      h += '<div class="serial-hero">' +
        '<div class="serial-step">Step 1 of 2</div>' +
        '<div class="serial-q">What is the serial number on this unit?</div>' +
        '<input class="serial-input" id="serial-in" placeholder="Type or scan the serial" ' +
          'autocomplete="off" autocapitalize="characters" spellcheck="false" value="' + U.esc(st.serial) + '" />' +
        '<div class="btn-row mt10">' +
          '<button class="btn btn-primary grow-btn" data-act="serial-go" data-arg="' + siteId + '">Continue →</button>' +
          '<button class="btn btn-outline" data-act="serial-scan" data-arg="' + siteId + '">📷 Scan</button>' +
        '</div>' +
        (st.error ? '<div class="serial-err">' + U.esc(st.error) + '</div>' : '') +
        '<div class="small muted mt8">Apple serials are on the underside of the unit or in ' +
        '<em>About This Mac</em>. Nothing else is asked until this is recorded.</div>' +
      '</div>';

      /* ---- step 2: which model is it? ---- */
      if (st.step === 'pick') {
        h += '<div class="section-label">Step 2 of 2 — which model is this unit?</div>' +
          '<div class="card pad blue-card small">Serial <b>' + U.esc(st.serial) + '</b> is new. ' +
          'Pick the model so it maps to the right line of the Reliance inventory for this site.</div>';
        if (!groups.length) {
          h += U.empty('✅', 'Every unit at this site already has a serial',
            'If this device belongs here, raise it with the coordinator — the inventory count may be short.');
        } else {
          h += '<div class="card">' + groups.map(function (g) {
            return '<button class="card-row link full" data-act="serial-bind" data-site="' + siteId +
              '" data-key="' + U.esc(g.key) + '">' +
              '<div class="grow"><div class="row-title">' + U.esc(g.model) + '</div>' +
              '<div class="small muted">' + U.esc(g.desc || '') + '</div>' +
              '<div class="small muted">Article ' + U.esc(g.article || '—') + ' · ' +
              U.money(g.price) + '</div></div>' +
              U.pill(g.assets.length + ' unmapped', 'warn') + '</button>';
          }).join('') + '</div>';
        }
      }

      /* ---- units already mapped at this site ---- */
      var done = S.assetsAt(siteId).filter(S.hasSerial);
      if (done.length) {
        h += '<div class="section-label">Serials captured at this site (' + done.length + ')</div>';
        h += '<div class="card">' + done.slice(0, 25).map(function (a) {
          return '<a class="card-row link" href="#/asset/' + a.id + '">' +
            '<div class="grow"><div class="row-title">' + U.esc(a.serial) + '</div>' +
            '<div class="small muted">' + U.esc(a.tag + ' · ' + a.model) + '</div></div>' +
            U.statusPill(a.status) + '</a>';
        }).join('') + '</div>';
        if (done.length > 25) h += '<div class="small muted pad-x">Showing 25 of ' + done.length + '.</div>';
      }
      return h;
    },
    mount: function () {
      var el = document.getElementById('serial-in');
      if (!el) return;
      if (RA.serialState && RA.serialState.step === 'entry') setTimeout(function () { el.focus(); }, 60);
      el.addEventListener('input', function () { RA.serialState.serial = el.value; });
      el.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          A['serial-go']({ getAttribute: function () { return RA.serialState.site_id; } });
        }
      });
    }
  };

  A['serial-go'] = function (el) {
    var siteId = el.getAttribute('data-arg');
    var st = RA.serialState;
    var input = document.getElementById('serial-in');
    var serial = S.normSerial(input ? input.value : st.serial);
    st.serial = serial; st.error = '';

    if (!serial) { st.error = 'Enter the serial number to continue.'; RA.render(); return; }
    if (serial.length < 4) { st.error = 'That serial looks too short — please re-check the device.'; RA.render(); return; }

    var found = S.findBySerial(serial);
    if (found) {
      if (found.site_id !== siteId) {
        var other = S.site(found.site_id);
        st.error = 'BR-06: this serial is already mapped to ' + found.tag + ' at ' +
          (other ? other.site : found.site_id) + '. Raise it with your supervisor before proceeding.';
        RA.render(); return;
      }
      if (found.status === 'pending_qc') {
        RA.serialState = null;
        location.hash = '#/qc/' + found.id;
      } else {
        U.toast('This unit already has a QC record — opening it.', 'warn');
        RA.serialState = null;
        location.hash = '#/asset/' + found.id;
      }
      RA.render();
      return;
    }
    st.step = 'pick';
    RA.render();
  };

  A['serial-scan'] = function (el) {
    var siteId = el.getAttribute('data-arg');
    U.scan(function (code) {
      if (!code) return;
      RA.serialState.serial = S.normSerial(code);
      RA.render();
      A['serial-go']({ getAttribute: function () { return siteId; } });
    });
  };

  A['serial-bind'] = function (el) {
    var siteId = el.getAttribute('data-site'), key = el.getAttribute('data-key');
    var serial = RA.serialState.serial;
    try {
      var a = S.mapSerialToArticle(siteId, key, serial);
      RA.serialState = null;
      U.toast('Serial ' + a.serial + ' mapped to ' + a.tag, 'success');
      location.hash = '#/qc/' + a.id;
      RA.render();
    } catch (e) {
      RA.serialState.error = e.message;
      RA.render();
    }
  };

  /* =========================================================
     RAPID QC (BRD Sec 6 + v3 inspection schema)
     ========================================================= */
  RA.qcState = null;

  Sc.qc = {
    title: 'Rapid QC',
    render: function (p) {
      var a = S.asset(p[0]);
      if (!a) return U.empty('❓', 'Asset not found', '');

      /* Serial first — no QC field is shown until the unit is identified */
      if (!S.hasSerial(a)) return serialGate(a);

      if (!RA.qcState || RA.qcState.asset_id !== a.id) {
        RA.qcState = {
          asset_id: a.id,
          started: Date.now(),
          specs: prefillSpecs(a),
          responses: {},
          photos: [],
          remarks: ''
        };
      }
      var st = RA.qcState;
      var blocks = D.CONDITION_BLOCKS[a.category] || D.CONDITION_BLOCKS.laptop;
      var codes = S.deriveCodes(st.responses);
      var price = S.computePrice(a.base_price, codes);
      var site = S.site(a.site_id);
      var bench = S.db.config.qc;

      var h = '';
      /* timer */
      h += '<div class="qc-timer-bar" id="qc-timer-bar">' +
        '<div><div class="t-val" id="qc-timer">0:00</div><div class="t-lbl">elapsed</div></div>' +
        '<div class="t-meta">' +
          '<div><b>' + bench.target_min + '–' + bench.max_min + ' min</b><span>benchmark</span></div>' +
          '<div><b>' + U.esc(a.tag) + '</b><span>' + U.esc(a.serial) + '</span></div>' +
        '</div></div>';

      h += '<div class="card pad"><div class="row-between"><b>' + U.esc(a.make + ' ' + a.model) + '</b>' +
        U.pill(D.CATEGORY_LABEL[a.category], 'blue') + '</div>' +
        '<div class="small muted">' + U.esc(site ? site.site : '') + ' · base price ' + U.money(a.base_price) + '</div></div>';

      /* A. Condition tap cards */
      h += '<div class="section-label">1 · Condition — tap to select</div>';
      h += '<div class="qc-blocks">';
      blocks.forEach(function (b) {
        var val = st.responses[b.key];
        var suppressed = b.suppress && st.responses.power === 'No Power';
        h += '<div class="qc-block' + (suppressed ? ' suppressed' : '') + '">' +
          '<div class="qc-block-head"><span class="qc-icon">' + b.icon + '</span>' +
          '<span class="qc-name">' + U.esc(b.label) + '</span>' +
          (val ? '<span class="qc-sel">' + U.esc(val) + '</span>' : '<span class="qc-sel req">required</span>') +
          '</div><div class="chips">' +
          b.values.filter(function (v) { return v !== D.NOT_TESTED || suppressed; }).map(function (v) {
            return '<button class="chip' + (val === v ? ' on' : '') + (isBad(b.key, v) ? ' bad' : '') + '"' +
              (suppressed ? ' disabled' : '') +
              ' data-act="qc-set" data-k="' + b.key + '" data-v="' + U.esc(v) + '">' + U.esc(v) + '</button>';
          }).join('') + '</div>' +
          (suppressed ? '<div class="small muted mt4">BR-03: auto-set to “' + D.NOT_TESTED + '”.</div>' : '') +
          '</div>';
      });
      h += '</div>';

      /* B. Derived codes + price */
      h += '<div class="section-label">2 · Derived defect codes &amp; commercial impact</div>';
      h += '<div class="card pad">' +
        '<div class="chips">' + codes.map(function (c) {
          var m = D.codeMeta(c);
          return '<span class="pill pill-' + (m.rank === 0 ? 'ok' : m.rank >= 3 ? 'fail' : 'warn') + '">' +
            U.esc(c + ' — ' + m.label) + '</span>';
        }).join('') + '</div>' +
        '<div class="kv-grid mt10">' +
          kv('Primary code', S.primaryCode(codes)) +
          kv('Deduction master', 'v' + price.version + ' · ' + price.master_status) +
          kv('Approved deduction %', price.pct + '%') +
          kv('Deduction amount', U.money(price.deduction_amount)) +
          kv('Base / agreed price', U.money(a.base_price)) +
          kv('Revised price after QC', U.money(price.revised_price)) +
        '</div>' +
        '<div class="small muted mt6">🔒 BR-02: deduction % is read-only for field roles — sourced from the approved master ' +
        '(' + S.db.config.multi_defect_rule + ' rule for multiple defects).</div>' +
      '</div>';

      /* C. Spec fields */
      h += '<div class="section-label">3 · Inspection details (' + U.esc(D.CATEGORY_LABEL[a.category]) + ')</div>';
      h += '<div class="card pad spec-grid">' + (D.SPEC_FIELDS[a.category] || []).map(function (f) {
        var v = st.specs[f.key] || '';
        if (f.key === 'serial') {
          /* captured in step 1 and mapped to this inventory line — corrections are audited */
          return '<label class="spec-fld"><span>Serial (captured)</span>' +
            '<div class="serial-locked"><b>' + U.esc(a.serial) + '</b>' +
            '<button class="link-btn" data-act="serial-correct" data-arg="' + a.id + '">Correct</button></div></label>';
        }
        if (f.type === 'text') {
          return '<label class="spec-fld"><span>' + U.esc(f.label) + '</span>' +
            '<input class="input-field" data-spec="' + f.key + '" value="' + U.esc(v) + '" /></label>';
        }
        /* a value carried in from the article master always stays selectable */
        var opts = f.values.indexOf(v) > -1 || !v ? f.values : [v].concat(f.values);
        return '<label class="spec-fld"><span>' + U.esc(f.label) + '</span>' +
          '<select class="input-field" data-spec="' + f.key + '">' +
          '<option value="">—</option>' +
          opts.map(function (o) {
            return '<option' + (o === v ? ' selected' : '') + '>' + U.esc(o) + '</option>';
          }).join('') + '</select></label>';
      }).join('') + '</div>';

      /* D. Photos */
      var rules = S.photoRules(codes, st.photos);
      h += '<div class="section-label">4 · Photo evidence</div>';
      h += '<div class="card pad">' +
        '<div class="thumbs">' +
          st.photos.map(function (ph, i) {
            return '<div class="thumb-wrap"><img class="thumb" src="' + ph.data + '" />' +
              '<span class="thumb-tag">' + U.esc(ph.kind) + '</span>' +
              '<button class="thumb-x" data-act="qc-photo-del" data-arg="' + i + '">✕</button></div>';
          }).join('') +
          (st.photos.length < S.db.config.photo.max_photos ?
            '<button class="thumb add" data-act="qc-photo" data-arg="overall">📷<span>Overall</span></button>' +
            '<button class="thumb add" data-act="qc-photo" data-arg="defect">🔍<span>Defect</span></button>' : '') +
        '</div>' +
        '<div class="small ' + (rules.ok ? 'muted' : 'err') + ' mt8">' +
          (rules.ok ? '✓ Photo requirements met' : rules.errors.map(U.esc).join(' ')) + '</div>' +
      '</div>';

      /* E. Remarks + submit */
      h += '<div class="section-label">5 · Remarks &amp; submit</div>';
      h += '<div class="card pad">' +
        '<textarea class="input-field" id="qc-remarks" rows="2" placeholder="Optional — exceptions only, no free-text on primary path">' +
        U.esc(st.remarks) + '</textarea>' +
        '<button class="btn btn-green block mt10" data-act="qc-submit" data-arg="' + a.id + '">✔ Submit QC Report</button>' +
        '<button class="btn btn-outline block mt8" data-act="qc-cancel">Cancel</button>' +
        '<div class="small muted mt8">On submit the record is timestamped, locked and queued for Reliance approval. ' +
        'Corrections require a re-QC event (BR-05).</div>' +
      '</div>';
      return h;
    },

    mount: function () {
      var gate = document.getElementById('gate-serial');
      if (gate) {
        setTimeout(function () { gate.focus(); }, 60);
        gate.addEventListener('keydown', function (e) {
          if (e.key === 'Enter') {
            e.preventDefault();
            document.querySelector('[data-act="gate-capture"]').click();
          }
        });
        return;
      }

      /* timer tick */
      if (RA.qcTimer) clearInterval(RA.qcTimer);
      RA.qcTimer = setInterval(function () {
        var el = document.getElementById('qc-timer');
        if (!el || !RA.qcState) { clearInterval(RA.qcTimer); RA.qcTimer = null; return; }
        var sec = Math.floor((Date.now() - RA.qcState.started) / 1000);
        el.textContent = U.mmss(sec);
        var bar = document.getElementById('qc-timer-bar');
        var cfg = S.db.config.qc;
        bar.className = 'qc-timer-bar' + (sec > cfg.alert_min * 60 ? ' over' : (sec > cfg.max_min * 60 ? ' warn' : ''));
      }, 1000);

      /* spec binding */
      document.querySelectorAll('[data-spec]').forEach(function (el) {
        el.addEventListener('change', function () {
          RA.qcState.specs[el.getAttribute('data-spec')] = el.value;
        });
        el.addEventListener('input', function () {
          RA.qcState.specs[el.getAttribute('data-spec')] = el.value;
        });
      });
      var rem = document.getElementById('qc-remarks');
      if (rem) rem.addEventListener('input', function () { RA.qcState.remarks = rem.value; });
    }
  };

  /* Serial gate shown in place of the QC form until the unit is identified */
  function serialGate(a) {
    var site = S.site(a.site_id);
    return '' +
      '<div class="serial-hero">' +
        '<div class="serial-step">Step 1 of 2</div>' +
        '<div class="serial-q">What is the serial number on this unit?</div>' +
        '<input class="serial-input" id="gate-serial" placeholder="Type or scan the serial" ' +
          'autocomplete="off" autocapitalize="characters" spellcheck="false" />' +
        '<div class="btn-row mt10">' +
          '<button class="btn btn-primary grow-btn" data-act="gate-capture" data-arg="' + a.id + '">Continue →</button>' +
          '<button class="btn btn-outline" data-act="gate-scan" data-arg="' + a.id + '">📷 Scan</button>' +
        '</div>' +
        '<div class="small muted mt8">The QC checklist opens once the serial is recorded. ' +
        'It is mapped to this inventory line and cannot be changed after submission.</div>' +
      '</div>' +
      '<div class="card pad">' +
        '<div class="row-between"><b>' + U.esc(a.make + ' ' + a.model) + '</b>' +
        U.pill(D.CATEGORY_LABEL[a.category], 'blue') + '</div>' +
        '<div class="kv-grid mt8">' +
          kv('Site', site ? site.site : '—') + kv('Asset tag', a.tag) +
          kv('Article', a.article || '—') + kv('Base price', U.money(a.base_price)) +
        '</div></div>' +
      '<div class="pad-x"><button class="btn btn-outline block" data-act="goto" data-arg="#/site/' +
        a.site_id + '">← Back to site</button></div>';
  }

  A['gate-capture'] = function (el) {
    var id = el.getAttribute('data-arg');
    var input = document.getElementById('gate-serial');
    try {
      var a = S.captureSerial(id, input ? input.value : '');
      /* keep any checklist already entered for this unit (serial correction path) */
      if (RA.qcState && RA.qcState.asset_id === a.id) RA.qcState.specs.serial = a.serial;
      else RA.qcState = null;
      U.toast('Serial ' + a.serial + ' recorded', 'success');
      RA.render();
    } catch (e) { U.toast(e.message, 'error'); }
  };
  A['serial-correct'] = function (el) {
    var a = S.asset(el.getAttribute('data-arg'));
    U.confirm('Correct the serial?',
      'The QC checklist stays as entered. You will be asked for the serial again before submitting. ' +
      'The change is recorded in the audit log.',
      function () {
        var from = a.serial;
        a.serial = 'PEND-' + a.id.replace(/^A/, '');
        S.audit('asset', a.id, 'serial_cleared', { from: from, reason: 'field correction' });
        S.persist();
        RA.render();
      }, 'Re-enter serial');
  };

  A['gate-scan'] = function (el) {
    var id = el.getAttribute('data-arg');
    U.scan(function (code) {
      if (!code) return;
      var input = document.getElementById('gate-serial');
      if (input) input.value = code;
      A['gate-capture']({ getAttribute: function () { return id; } });
    });
  };

  function isBad(key, v) {
    var m = D.CODE_MAP[key];
    return !!(m && m[v]);
  }
  /* Prefill from the source master; serial is blank until the engineer reads it
     off the device (the inventory workbook carries no serial numbers). */
  function prefillSpecs(a) {
    var s = {
      make: a.make,
      model: a.model,
      serial: /^PEND-/.test(a.serial) ? '' : a.serial
    };
    if (a.chip) {
      s.processor = a.chip;
      if (/^M[1-4]/.test(a.chip)) { s.generation = 'Apple Silicon'; s.ram_type = 'Unified'; }
    }
    if (a.ram) s.ram = a.ram;
    if (a.storage) { s.storage_cap = a.storage; s.storage_type = 'SSD'; }
    if (a.screen_size) s.screen_size = a.screen_size;
    if (a.category === 'desktop') s.form_factor = /iMac/.test(a.model || '') ? 'AIO' : 'Mini';
    return s;
  }

  A['qc-set'] = function (el) {
    var k = el.getAttribute('data-k'), v = el.getAttribute('data-v');
    var st = RA.qcState; if (!st) return;
    st.responses[k] = (st.responses[k] === v) ? null : v;
    var a = S.asset(st.asset_id);
    S.applySuppression(a.category, st.responses);
    RA.render();
  };
  A['qc-photo'] = function (el) {
    var kind = el.getAttribute('data-arg');
    U.pickPhoto(kind, function (p) {
      RA.qcState.photos.push(p);
      U.toast('Photo added (' + kind + ')', 'success');
      RA.render();
    });
  };
  A['qc-photo-del'] = function (el) {
    RA.qcState.photos.splice(+el.getAttribute('data-arg'), 1);
    RA.render();
  };
  A['qc-cancel'] = function () {
    U.confirm('Discard this QC?', 'Nothing will be saved for this unit.', function () {
      var id = RA.qcState.asset_id;
      RA.qcState = null;
      location.hash = '#/asset/' + id; RA.render();
    }, 'Discard', true);
  };

  A['qc-submit'] = function (el) {
    var a = S.asset(el.getAttribute('data-arg'));
    var st = RA.qcState;
    var blocks = D.CONDITION_BLOCKS[a.category] || [];
    var missing = blocks.filter(function (b) { return !st.responses[b.key]; }).map(function (b) { return b.label; });
    if (missing.length) { U.toast('Complete all condition blocks: ' + missing.join(', '), 'error'); return; }

    /* Serial is captured in step 1 and mapped to this inventory line (BR-06) */
    if (!S.hasSerial(a)) {
      U.toast('Capture the device serial number before submitting.', 'error');
      RA.render();
      return;
    }
    st.specs.serial = a.serial;
    var codes = S.deriveCodes(st.responses);
    var rules = S.photoRules(codes, st.photos);
    if (!rules.ok) { U.toast(rules.errors.join(' '), 'error'); return; }

    var seconds = Math.floor((Date.now() - st.started) / 1000);
    var bench = S.db.config.qc;
    var warn = seconds > bench.alert_min * 60
      ? '\n\n⚠ QC time ' + U.mmss(seconds) + ' exceeds the ' + bench.alert_min + '-minute alert threshold — a supervisor note will be logged.'
      : '';
    var price = S.computePrice(a.base_price, codes);

    U.confirm('Submit QC — ' + a.tag,
      'Codes: ' + codes.join(' + ') + '. Revised price ' + U.money(price.revised_price) +
      ' (deduction ' + price.pct + '%). Once submitted the record is immutable.' + warn,
      function () {
        try {
          var rec = S.submitQC({
            asset_id: a.id, specs: st.specs, responses: st.responses,
            photos: st.photos, remarks: st.remarks, seconds: seconds
          });
          if (seconds > bench.alert_min * 60) {
            S.audit('qc', rec.id, 'benchmark_exceeded', { seconds: seconds });
            S.persist();
          }
          RA.qcState = null;
          U.toast('QC ' + rec.id + ' submitted · ' + U.mmss(seconds), 'success');
          var next = nextPendingAt(a.site_id);
          location.hash = next ? '#/qc/' + next.id : '#/site/' + a.site_id;
          RA.render();
        } catch (e) { U.toast(e.message, 'error'); }
      }, 'Submit QC');
  };

  function nextPendingAt(siteId) {
    return S.assetsAt(siteId).filter(function (a) { return a.status === 'pending_qc'; })[0] || null;
  }

})(window.RA = window.RA || {});
