/* ============================================================
   Reliance Asset FieldOps — Operations screens
   Approvals · Pricing · Packing · Pickup · Courier · Warehouse
   ============================================================ */
(function (RA) {
  'use strict';
  var U = RA.ui, S = RA.store, D = RA.data;
  var Sc = RA.screens = RA.screens || {};
  var A = RA.actions = RA.actions || {};

  function kv(k, v) { return '<div class="kv"><div class="k">' + U.esc(k) + '</div><div class="v">' + U.esc(v) + '</div></div>'; }

  /* =========================================================
     RELIANCE QC APPROVALS (FR-011)
     ========================================================= */
  Sc.approvals = {
    title: 'QC Approvals',
    badge: function () {
      var n = S.liveQC().filter(function (q) { return q.status === 'pending'; }).length;
      return n ? n + ' pending' : null;
    },
    render: function () {
      var tab = RA.filters.apprTab || 'pending';
      var all = S.liveQC().sort(function (a, b) { return a.submitted_at < b.submitted_at ? -1 : 1; });
      var list = all.filter(function (q) {
        if (tab === 'pending') return q.status === 'pending';
        if (tab === 'disputed') return q.status === 'disputed' || q.status === 're_qc';
        return q.status === 'accepted';
      });
      var readOnly = ['spoc', 'coord', 'pmo'].indexOf(S.me().role) > -1;

      var h = tabs('apprTab', tab, [
        ['pending', 'Pending (' + all.filter(function (q) { return q.status === 'pending'; }).length + ')'],
        ['disputed', 'Disputed / Re-QC'],
        ['accepted', 'Accepted']
      ]);

      if (readOnly) h += '<div class="card pad blue-card small">👁 Read-only view for your role. Only the Reliance QC Approver can Accept / Dispute / Re-QC.</div>';

      if (!list.length) return h + U.empty('✅', 'Queue is clear', 'No QC records in this state.');

      h += '<div class="list">';
      list.forEach(function (q) {
        var a = S.asset(q.asset_id), site = S.site(q.site_id), cm = S.commercialFor(q.id);
        var age = S.hoursSince(q.submitted_at);
        var breach = q.status === 'pending' && age > S.db.config.sla.qc_approval_h;
        h += '<div class="card pad' + (breach ? ' fail-card' : '') + '">' +
          '<div class="row-between"><b>' + U.esc(a ? a.tag : q.asset_id) + ' · ' + U.esc(a ? a.serial : '') + '</b>' +
          U.statusPill(q.status) + '</div>' +
          '<div class="small muted">' + U.esc(site ? site.site : '') + ' · ' + U.esc(a ? a.make + ' ' + a.model : '') +
          ' · ' + U.esc(q.engineer) + ' · ' + U.dt(q.submitted_at) + '</div>' +
          '<div class="small ' + (breach ? 'err' : 'muted') + '">Ageing ' + S.fmtAge(age) +
          (breach ? ' — SLA breached (≤1 business day). Escalation L1 active.' : '') + '</div>' +
          '<div class="chips mt8">' + q.codes.map(function (c) {
            var m = D.codeMeta(c);
            return U.pill(c + ' — ' + m.label, m.rank === 0 ? 'ok' : m.rank >= 3 ? 'fail' : 'warn');
          }).join('') + '</div>' +
          (q.photos && q.photos.length ? '<div class="thumbs mt8">' + q.photos.map(function (p) {
            return p.data ? '<img class="thumb" src="' + p.data + '" data-act="lightbox" data-arg="' + p.id + '" />' : '<div class="thumb ph">🗜️</div>';
          }).join('') + '</div>' : '<div class="small muted mt6">No photo cached locally.</div>') +
          (cm ? '<div class="kv-grid mt8">' +
            kv('Base price', U.money(cm.base_price)) +
            kv('Deduction', cm.deduction_pct + '% · ' + U.money(cm.deduction_amount)) +
            kv('Revised price', U.money(cm.revised_price)) +
            kv('QC time', U.mmss(q.seconds)) + '</div>' : '') +
          (q.remarks ? '<div class="small mt6"><b>Remarks:</b> ' + U.esc(q.remarks) + '</div>' : '') +
          '<div class="btn-row mt10">' +
            '<a class="btn btn-outline sm" href="#/asset/' + q.asset_id + '">View asset</a>' +
            (!readOnly && q.status === 'pending' ?
              '<button class="btn btn-green sm" data-act="qc-decide" data-arg="' + q.id + '" data-d="accepted">✔ Accept</button>' +
              '<button class="btn btn-red sm" data-act="qc-decide" data-arg="' + q.id + '" data-d="disputed">✕ Dispute</button>' +
              '<button class="btn btn-outline sm" data-act="qc-decide" data-arg="' + q.id + '" data-d="re_qc">↻ Re-QC</button>' : '') +
            (!readOnly && q.status === 'disputed' ?
              '<button class="btn btn-green sm" data-act="qc-decide" data-arg="' + q.id + '" data-d="accepted">✔ Accept after review</button>' +
              '<button class="btn btn-outline sm" data-act="qc-decide" data-arg="' + q.id + '" data-d="re_qc">↻ Request Re-QC</button>' : '') +
          '</div>' +
          '<div class="small muted mt6">🔒 Field evidence cannot be edited by the approver (BRD Sec 9).</div>' +
        '</div>';
      });
      h += '</div>';
      return h;
    }
  };

  function tabs(key, active, items) {
    return '<div class="tabs">' + items.map(function (it) {
      return '<button class="tab' + (active === it[0] ? ' on' : '') + '" data-act="set-filter" data-k="' + key +
        '" data-v="' + it[0] + '">' + U.esc(it[1]) + '</button>';
    }).join('') + '</div>';
  }
  A['set-filter'] = function (el) {
    RA.filters[el.getAttribute('data-k')] = el.getAttribute('data-v');
    RA.render();
  };

  A['qc-decide'] = function (el) {
    var qcId = el.getAttribute('data-arg'), decision = el.getAttribute('data-d');
    var labels = { accepted: 'Accept QC', disputed: 'Dispute QC', re_qc: 'Request Re-QC' };
    var needReason = decision !== 'accepted';
    U.modal({
      title: labels[decision],
      body: (needReason
        ? U.field('Reason code', U.select('dec-reason', [
            'Evidence insufficient', 'Defect code mismatch', 'Photo unclear / missing',
            'Serial mismatch', 'Condition disputed by SPOC', 'Other'], 'Evidence insufficient')) +
          U.field('Note', U.input('dec-note', 'Optional detail', ''))
        : '<p class="muted">Acceptance releases the asset for packing and applies the approved deduction master. ' +
          'Commercial acceptance is tracked separately (BRD Sec 7).</p>'),
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
        '<button class="btn ' + (decision === 'accepted' ? 'btn-green' : 'btn-primary') + '" id="dec-go">' +
        U.esc(labels[decision]) + '</button>',
      onOpen: function (host) {
        host.querySelector('#dec-go').addEventListener('click', function () {
          var reason = needReason ? (U.val('dec-reason') + (U.val('dec-note') ? ' — ' + U.val('dec-note') : '')) : null;
          try {
            S.decideQC(qcId, decision, reason);
            U.closeModal(); U.toast(labels[decision] + ' recorded', 'success'); RA.render();
          } catch (e) { U.toast(e.message, 'error'); }
        });
      }
    });
  };

  A.lightbox = function (el) {
    U.modal({ title: 'Photo evidence', body: '<img class="lightbox" src="' + el.getAttribute('src') + '" />' });
  };

  /* =========================================================
     PRICING / COMMERCIAL (FR-013, FR-014)
     ========================================================= */
  Sc.pricing = {
    title: 'Commercial & Pricing',
    render: function () {
      var master = S.activeDeduction();
      var tab = RA.filters.cmTab || 'pending';
      var list = S.db.commercial.filter(function (c) {
        if (tab === 'pending') return c.commercial_status === 'pending';
        if (tab === 'hold') return c.commercial_status === 'hold' || c.commercial_status === 'disputed';
        return c.commercial_status === 'accepted';
      });
      var canDecide = ['commercial', 'admin'].indexOf(S.me().role) > -1;

      var totals = S.db.commercial.reduce(function (t, c) {
        t.base += c.base_price; t.ded += c.deduction_amount; t.rev += c.revised_price;
        if (c.commercial_status === 'hold' || c.commercial_status === 'disputed') t.held += c.revised_price;
        return t;
      }, { base: 0, ded: 0, rev: 0, held: 0 });

      var h = '';
      h += '<div class="card pad ' + (master.approval_status === 'Approved' ? 'ok-card' : 'warn-card') + '">' +
        '<div class="row-between"><b>Active deduction master — ' + U.esc(master.label) + '</b>' +
        U.pill(master.approval_status, master.approval_status === 'Approved' ? 'ok' : 'warn') + '</div>' +
        '<div class="small muted">Effective ' + U.esc(master.effective_from) + ' · multiple-defect rule: <b>' +
        U.esc(master.rule) + '</b>' + (master.approved_by ? ' · approved by ' + U.esc(master.approved_by) : '') + '</div>' +
        (master.approval_status !== 'Approved' ?
          '<div class="small mt6">All percentages stay at 0% until written Reliance approval (BRD Sec 7 / Open Decision #3).</div>' : '') +
        (S.can('admin') ? '<button class="btn btn-outline sm mt8" data-act="goto" data-arg="#/admin">Manage versions</button>' : '') +
      '</div>';

      h += '<div class="stats-row">' +
        '<div class="stat-card"><div class="stat-val sm">' + U.money(totals.base) + '</div><div class="stat-label">Base value</div></div>' +
        '<div class="stat-card"><div class="stat-val sm">' + U.money(totals.ded) + '</div><div class="stat-label">Approved deductions</div></div>' +
        '<div class="stat-card highlight"><div class="stat-val sm">' + U.money(totals.rev) + '</div><div class="stat-label">Revised value</div></div>' +
        '<div class="stat-card"><div class="stat-val sm">' + U.money(totals.held) + '</div><div class="stat-label">Disputed / held</div></div>' +
      '</div>';

      h += tabs('cmTab', tab, [['pending', 'Pending'], ['hold', 'Hold / Disputed'], ['accepted', 'Accepted']]);

      if (!list.length) return h + U.empty('💰', 'Nothing in this queue', '');

      var rows = list.slice(0, 300).map(function (c) {
        var a = S.asset(c.asset_id), q = S.qcRecord(c.qc_id);
        return [
          '<b>' + U.esc(a ? a.tag : '') + '</b><div class="small muted">' + U.esc(a ? a.serial : '') + '</div>',
          U.esc(q ? q.codes.join('+') : ''),
          U.money(c.base_price),
          c.deduction_pct + '%',
          U.money(c.deduction_amount),
          '<b>' + U.money(c.revised_price) + '</b>',
          U.statusPill(c.qc_status),
          U.statusPill(c.commercial_status),
          canDecide && c.commercial_status !== 'accepted'
            ? '<button class="btn btn-green xs" data-act="cm-decide" data-arg="' + c.id + '" data-d="accepted">Accept</button> ' +
              '<button class="btn btn-outline xs" data-act="cm-decide" data-arg="' + c.id + '" data-d="hold">Hold</button>'
            : '—'
        ];
      });
      h += U.table(['Asset', 'Codes', 'Base', 'Ded %', 'Ded amt', 'Revised', 'QC', 'Commercial', ''], rows);
      h += '<div class="pad-x mt8"><button class="btn btn-outline block" data-act="export-pricing">⬇ Export pricing report (CSV)</button></div>';
      return h;
    }
  };

  A['cm-decide'] = function (el) {
    var id = el.getAttribute('data-arg'), d = el.getAttribute('data-d');
    U.modal({
      title: d === 'accepted' ? 'Accept commercial value' : 'Place commercial hold',
      body: U.field('Note', U.input('cm-note', d === 'hold' ? 'Reason for hold' : 'Optional', '')),
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
              '<button class="btn btn-primary" id="cm-go">Confirm</button>',
      onOpen: function (host) {
        host.querySelector('#cm-go').addEventListener('click', function () {
          S.decideCommercial(id, d, U.val('cm-note'));
          U.closeModal(); U.toast('Commercial status updated', 'success'); RA.render();
        });
      }
    });
  };

  /* =========================================================
     PACKING (FR-015, BR-01)
     ========================================================= */
  RA.packSel = {};
  Sc.packing = {
    title: 'Packing',
    render: function () {
      var sites = S.mySites();
      var siteId = RA.filters.packSite || (sites[0] && sites[0].id);
      var released = S.db.assets.filter(function (a) { return a.status === 'accepted' && a.site_id === siteId; });
      var pkgs = S.db.packages.filter(function (p) { return p.site_id === siteId; });
      var sel = Object.keys(RA.packSel).filter(function (k) { return RA.packSel[k]; });

      var h = '<div class="toolbar">' + U.select('pack-site', sites.map(function (s) {
        return { v: s.id, l: s.site + ' (' + S.db.assets.filter(function (a) { return a.status === 'accepted' && a.site_id === s.id; }).length + ' released)' };
      }), siteId) + '</div>';

      h += '<div class="card pad blue-card small">🔒 BR-01: only assets with Reliance QC status <b>Accepted</b> appear here.</div>';

      h += '<div class="section-label">Released assets — select for package</div>';
      if (!released.length) h += U.empty('📦', 'No released assets', 'Assets appear once the Reliance QC Approver accepts them.');
      else {
        h += '<div class="card">' + released.map(function (a) {
          return '<label class="card-row check">' +
            '<input type="checkbox" data-pack="' + a.id + '"' + (RA.packSel[a.id] ? ' checked' : '') + ' />' +
            '<div class="grow"><div class="row-title">' + U.esc(a.tag) + '</div>' +
            '<div class="small muted">' + U.esc(a.serial + ' · ' + a.make + ' ' + a.model) + '</div></div></label>';
        }).join('') + '</div>';
        h += '<div class="pad-x"><button class="btn btn-primary block" data-act="pack-create" data-arg="' + siteId + '">' +
          '🔐 Build &amp; seal package (' + sel.length + ' selected)</button></div>';
      }

      h += '<div class="section-label">Packages at this site</div>';
      if (!pkgs.length) h += U.empty('🗃️', 'No packages yet', '');
      else h += '<div class="card">' + pkgs.map(function (p) {
        return '<div class="card-row col">' +
          '<div class="row-between"><b>' + U.esc(p.id) + '</b>' + U.statusPill(p.status) + '</div>' +
          '<div class="small muted">' + p.assets.length + ' assets · ' + U.esc(p.type) + ' · seal ' + U.esc(p.seal) +
          ' · ' + U.esc(p.packed_by) + ' · ' + U.dt(p.packed_at) + '</div>' +
          (p.movement_id ? '<div class="small muted">Dispatch: ' + U.esc(p.movement_id) + '</div>' : '') +
          '<div class="btn-row mt6"><button class="btn btn-outline xs" data-act="pkg-manifest" data-arg="' + p.id + '">Manifest</button></div>' +
          '</div>';
      }).join('') + '</div>';
      return h;
    },
    mount: function () {
      var sel = document.getElementById('pack-site');
      if (sel) sel.addEventListener('change', function () { RA.filters.packSite = sel.value; RA.packSel = {}; RA.render(); });
      document.querySelectorAll('[data-pack]').forEach(function (cb) {
        cb.addEventListener('change', function () {
          RA.packSel[cb.getAttribute('data-pack')] = cb.checked;
          RA.render();
        });
      });
    }
  };

  A['pack-create'] = function (el) {
    var siteId = el.getAttribute('data-arg');
    var ids = Object.keys(RA.packSel).filter(function (k) { return RA.packSel[k]; });
    if (!ids.length) { U.toast('Select at least one asset', 'warn'); return; }
    var photoHolder = { p: null };
    U.modal({
      title: 'Seal package — ' + ids.length + ' assets',
      body: U.field('Packing type', U.select('pk-type', ['Carton', 'Pallet', 'Wooden Crate', 'Bubble + Carton'], 'Carton')) +
            U.field('Seal number', U.input('pk-seal', 'e.g. SEAL-88214', '')) +
            U.field('Accessory list', U.input('pk-acc', 'e.g. 3 chargers, 1 bag', '')) +
            '<div class="small muted">Confirm the count before sealing — ' + ids.length + ' assets will be locked into this package.</div>' +
            '<button class="btn btn-outline sm mt8" id="pk-photo">📷 Package photo</button><div id="pk-photo-prev"></div>',
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
              '<button class="btn btn-primary" id="pk-go">Seal package</button>',
      onOpen: function (host) {
        host.querySelector('#pk-photo').addEventListener('click', function () {
          U.pickPhoto('package', function (p) {
            photoHolder.p = p;
            host.querySelector('#pk-photo-prev').innerHTML = '<img class="thumb mt8" src="' + p.data + '" />';
          });
        });
        host.querySelector('#pk-go').addEventListener('click', function () {
          var seal = U.val('pk-seal');
          if (!seal) { U.toast('Seal number is required', 'error'); return; }
          try {
            var p = S.createPackage(siteId, ids, U.val('pk-type'), seal, U.val('pk-acc'), photoHolder.p);
            RA.packSel = {};
            U.closeModal(); U.toast('Package ' + p.id + ' sealed', 'success'); RA.render();
          } catch (e) { U.toast(e.message, 'error'); }
        });
      }
    });
  };

  A['pkg-manifest'] = function (el) {
    var p = S.pkg(el.getAttribute('data-arg'));
    var site = S.site(p.site_id);
    var rows = p.assets.map(function (id) {
      var a = S.asset(id), q = a.qc_id ? S.qcRecord(a.qc_id) : null;
      return '<tr><td>' + U.esc(a.tag) + '</td><td>' + U.esc(a.serial) + '</td><td>' +
        U.esc(a.make + ' ' + a.model) + '</td><td>' + U.esc(D.CATEGORY_LABEL[a.category]) + '</td><td>' +
        U.esc(q ? q.codes.join('+') : '') + '</td></tr>';
    }).join('');
    U.printReport('Package manifest ' + p.id,
      '<h1>Package Manifest — ' + U.esc(p.id) + '</h1>' +
      '<div class="sub">' + U.esc(site ? site.site + ', ' + site.city : '') + ' · sealed ' + U.esc(p.packed_at) + '</div>' +
      '<div class="kv"><div><b>Type:</b> ' + U.esc(p.type) + '</div><div><b>Seal:</b> ' + U.esc(p.seal) +
      '</div><div><b>Assets:</b> ' + p.assets.length + '</div><div><b>Packed by:</b> ' + U.esc(p.packed_by) + '</div></div>' +
      '<table><thead><tr><th>Asset tag</th><th>Serial</th><th>Make / model</th><th>Category</th><th>Defect codes</th></tr></thead><tbody>' +
      rows + '</tbody></table>' +
      '<p style="font-size:11px">Accessories: ' + U.esc(p.accessories || '—') + '</p>' +
      '<p style="font-size:11px;margin-top:26px">Handover signature (Reliance SPOC): ____________________  ' +
      'Received by (Partner): ____________________</p>');
  };

  /* =========================================================
     PICKUP HANDOVER (FR-017)
     ========================================================= */
  Sc.pickup = {
    title: 'Pickup & Handover',
    render: function () {
      var ready = S.db.packages.filter(function (p) { return !p.movement_id; });
      var movs = S.db.movements.filter(function (m) { return m.mode !== 'courier'; });
      var h = '';
      h += '<div class="card pad">' +
        '<div class="row-between"><b>Logistics thresholds (FR-016)</b>' + U.pill('configurable', 'gray') + '</div>' +
        '<div class="small muted">≥' + S.db.config.logistics.dedicated_min + ' dedicated · ' +
        S.db.config.logistics.cluster_min + '–' + (S.db.config.logistics.dedicated_min - 1) + ' cluster · ≤' +
        S.db.config.logistics.courier_max + ' approved courier</div></div>';

      h += '<div class="section-label">Sealed packages awaiting dispatch</div>';
      if (!ready.length) h += U.empty('🚛', 'Nothing awaiting dispatch', 'Seal a package in the Packing screen first.');
      else h += '<div class="card">' + ready.map(function (p) {
        var site = S.site(p.site_id);
        var mode = D.logisticsMode(p.assets.length, S.db.config);
        return '<div class="card-row col">' +
          '<div class="row-between"><b>' + U.esc(p.id) + '</b>' + U.pill(mode.label, 'blue') + '</div>' +
          '<div class="small muted">' + U.esc(site ? site.site : '') + ' · ' + p.assets.length + ' assets · seal ' + U.esc(p.seal) + '</div>' +
          '<div class="btn-row mt6">' +
            '<button class="btn btn-primary xs" data-act="dispatch" data-arg="' + p.id + '" data-mode="pickup">Pickup handover</button>' +
            '<button class="btn btn-outline xs" data-act="dispatch" data-arg="' + p.id + '" data-mode="courier">Book courier / AWB</button>' +
          '</div></div>';
      }).join('') + '</div>';

      h += '<div class="section-label">Pickup movements</div>';
      h += movs.length ? '<div class="card">' + movs.map(movRow).join('') + '</div>'
        : U.empty('📋', 'No pickups recorded', '');
      return h;
    }
  };

  function movRow(m) {
    var site = S.site(m.site_id);
    return '<div class="card-row col">' +
      '<div class="row-between"><b>' + U.esc(m.id) + (m.awb ? ' · AWB ' + U.esc(m.awb) : '') + '</b>' +
      U.statusPill(m.status) + '</div>' +
      '<div class="small muted">' + U.esc(site ? site.site : '') + ' → ' + U.esc(m.destination) +
      ' · ' + m.assets.length + ' assets · ' + U.dt(m.created_at) + '</div>' +
      '<div class="small muted">' + U.esc(m.mode === 'courier' ? (m.courier_name || 'Courier') : (m.vehicle + ' · ' + m.driver)) + '</div>' +
      '<div class="btn-row mt6">' +
        '<button class="btn btn-outline xs" data-act="mov-track" data-arg="' + m.id + '">Track</button>' +
        (m.status === 'in_transit' ? '<button class="btn btn-outline xs" data-act="mov-rto" data-arg="' + m.id + '">Flag RTO / exception</button>' : '') +
      '</div></div>';
  }

  A.dispatch = function (el) {
    var pkg = S.pkg(el.getAttribute('data-arg'));
    var mode = el.getAttribute('data-mode');
    var photoHolder = { p: null };
    var body = mode === 'courier'
      ? U.field('Courier name', U.select('mv-courier', ['Blue Dart Express', 'Delhivery', 'DTDC', 'Gati', 'Safexpress'], 'Blue Dart Express')) +
        U.field('AWB number', U.input('mv-awb', 'e.g. DTCS-2026-BKC-0089', '')) +
        U.field('Weight (kg)', U.input('mv-weight', '14.2', '')) +
        U.field('Destination warehouse', U.input('mv-dest', 'WH-Mumbai-01', 'WH-Mumbai-01')) +
        U.field('ETA', U.input('mv-eta', '', '', 'date')) +
        '<div class="small muted">Approved courier mode requires Reliance authorisation for ≤2 assets (BRD Open Decision #7).</div>'
      : U.field('Vehicle number', U.input('mv-vehicle', 'e.g. MH-04-AK-7890', '')) +
        U.field('Driver name', U.input('mv-driver', '', '')) +
        U.field('Driver mobile', U.input('mv-phone', '', '', 'tel')) +
        U.field('Logistics partner', U.input('mv-partner', 'e.g. Deshwal Logistics', '')) +
        U.field('Gate pass reference', U.input('mv-gate', '', '')) +
        U.field('Destination warehouse', U.input('mv-dest', 'WH-Mumbai-01', 'WH-Mumbai-01'));

    U.modal({
      title: (mode === 'courier' ? 'Book courier — ' : 'Pickup handover — ') + pkg.id,
      body: body + '<button class="btn btn-outline sm mt8" id="mv-photo">📷 Handover proof</button><div id="mv-prev"></div>' +
        '<div class="small muted mt6">' + pkg.assets.length + ' assets · seal ' + U.esc(pkg.seal) +
        ' · count validated against released quantity (BR-08).</div>',
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
              '<button class="btn btn-primary" id="mv-go">' + (mode === 'courier' ? 'Book AWB' : 'Complete handover') + '</button>',
      onOpen: function (host) {
        host.querySelector('#mv-photo').addEventListener('click', function () {
          U.pickPhoto('handover', function (p) {
            photoHolder.p = p;
            host.querySelector('#mv-prev').innerHTML = '<img class="thumb mt8" src="' + p.data + '" />';
          });
        });
        host.querySelector('#mv-go').addEventListener('click', function () {
          var data = {
            mode: mode, site_id: pkg.site_id, packages: [pkg.id],
            destination: U.val('mv-dest') || 'WH-Mumbai-01', handover_proof: photoHolder.p
          };
          if (mode === 'courier') {
            if (!U.val('mv-awb')) { U.toast('AWB number is required', 'error'); return; }
            data.courier_name = U.val('mv-courier'); data.awb = U.val('mv-awb');
            data.weight = U.val('mv-weight'); data.eta = U.val('mv-eta');
          } else {
            if (!U.val('mv-vehicle') || !U.val('mv-driver')) { U.toast('Vehicle and driver are required', 'error'); return; }
            data.vehicle = U.val('mv-vehicle'); data.driver = U.val('mv-driver');
            data.driver_phone = U.val('mv-phone'); data.partner = U.val('mv-partner');
            data.gate_pass = U.val('mv-gate');
          }
          try {
            var m = S.createMovement(data);
            U.closeModal(); U.toast(m.id + ' created · in transit', 'success');
            location.hash = mode === 'courier' ? '#/courier' : '#/pickup';
            RA.render();
          } catch (e) { U.toast(e.message, 'error'); }
        });
      }
    });
  };

  A['mov-track'] = function (el) {
    var m = S.movement(el.getAttribute('data-arg'));
    var steps = m.events.map(function (e, i) {
      return '<div class="track-step"><div class="step-line"><div class="step-dot ' +
        (i === m.events.length - 1 && m.status === 'in_transit' ? 'blue' : 'green') + '"></div>' +
        (i < m.events.length - 1 ? '<div class="step-connector"></div>' : '') + '</div>' +
        '<div class="step-content"><div class="step-title">' + U.esc(e.label) + '</div>' +
        '<div class="step-meta">' + U.dt(e.at) + ' · ' + U.esc(e.by || '') + '</div></div></div>';
    }).join('');
    if (m.status === 'in_transit') {
      steps += '<div class="track-step"><div class="step-line"><div class="step-dot"></div></div>' +
        '<div class="step-content"><div class="step-title muted">Warehouse receipt (GRN)</div>' +
        '<div class="step-meta">Pending · ' + U.esc(m.destination) + '</div></div></div>';
    }
    U.modal({
      title: m.id + (m.awb ? ' · AWB ' + m.awb : ''),
      body: '<div class="kv-grid">' +
        kv('Mode', m.mode === 'courier' ? (m.courier_name || 'Courier') : 'Pickup') +
        kv('Assets', String(m.assets.length)) +
        kv('Packages', m.packages.join(', ')) +
        kv('Destination', m.destination) +
        (m.vehicle ? kv('Vehicle', m.vehicle) : '') +
        (m.driver ? kv('Driver', m.driver + (m.driver_phone ? ' · ' + m.driver_phone : '')) : '') +
        (m.gate_pass ? kv('Gate pass', m.gate_pass) : '') +
        (m.weight ? kv('Weight', m.weight + ' kg') : '') +
        (m.eta ? kv('ETA', m.eta) : '') +
        '</div>' +
        (m.handover_proof && m.handover_proof.data ? '<img class="thumb mt8" src="' + m.handover_proof.data + '" />' : '') +
        '<div class="section-label">Tracking timeline</div>' + steps +
        (m.exception ? '<div class="small err mt6">Exception: ' + U.esc(m.exception) + '</div>' : ''),
      footer: '<button class="btn btn-outline" data-act="modal-close">Close</button>' +
        (m.status === 'in_transit' ? '<button class="btn btn-primary" data-act="mov-event" data-arg="' + m.id + '">+ Add tracking event</button>' : '')
    });
  };
  A['mov-event'] = function (el) {
    var id = el.getAttribute('data-arg');
    U.closeModal();
    U.modal({
      title: 'Add tracking event',
      body: U.field('Status update', U.select('ev-label', [
        'In transit — hub scan', 'Out for delivery', 'Delayed — carrier issue', 'Held at checkpoint', 'Arrived at destination city'
      ], 'In transit — hub scan')),
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
              '<button class="btn btn-primary" id="ev-go">Add</button>',
      onOpen: function (host) {
        host.querySelector('#ev-go').addEventListener('click', function () {
          S.updateMovement(id, {}, U.val('ev-label'));
          U.closeModal(); U.toast('Tracking updated', 'success'); RA.render();
        });
      }
    });
  };
  A['mov-rto'] = function (el) {
    var id = el.getAttribute('data-arg');
    U.modal({
      title: 'RTO / transit exception',
      body: U.field('Exception type', U.select('rto-type', [
        'RTO — returned to origin', 'Consignment damaged in transit', 'Partial delivery',
        'Address / gate access refused', 'Carrier delay >72h'], 'RTO — returned to origin')) +
        U.field('Note', U.input('rto-note', '', '')),
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
              '<button class="btn btn-red" id="rto-go">Flag exception</button>',
      onOpen: function (host) {
        host.querySelector('#rto-go').addEventListener('click', function () {
          var t = U.val('rto-type');
          S.updateMovement(id, { rto: t.indexOf('RTO') === 0, exception: t + (U.val('rto-note') ? ' — ' + U.val('rto-note') : '') },
            'Exception flagged: ' + t);
          U.closeModal(); U.toast('Exception flagged — PMO notified', 'warn'); RA.render();
        });
      }
    });
  };

  /* =========================================================
     COURIER / AWB (FR-018)
     ========================================================= */
  Sc.courier = {
    title: 'Courier / AWB',
    render: function () {
      var movs = S.db.movements.filter(function (m) { return m.mode === 'courier'; });
      var ready = S.db.packages.filter(function (p) { return !p.movement_id && p.assets.length <= S.db.config.logistics.courier_max; });
      var h = '';
      h += '<div class="card pad blue-card small">📮 Approved-courier mode applies to ≤' +
        S.db.config.logistics.courier_max + ' assets per site and requires Reliance authorisation (BRD Open Decision #7).</div>';

      if (ready.length) {
        h += '<div class="section-label">Eligible packages</div><div class="card">' + ready.map(function (p) {
          var site = S.site(p.site_id);
          return '<div class="card-row"><div class="grow"><div class="row-title">' + U.esc(p.id) + '</div>' +
            '<div class="small muted">' + U.esc(site ? site.site : '') + ' · ' + p.assets.length + ' assets</div></div>' +
            '<button class="btn btn-primary xs" data-act="dispatch" data-arg="' + p.id + '" data-mode="courier">Book AWB</button></div>';
        }).join('') + '</div>';
      }

      h += '<div class="section-label">AWB log</div>';
      if (!movs.length) return h + U.empty('📮', 'No AWBs booked', '');
      movs.forEach(function (m) {
        var site = S.site(m.site_id);
        h += '<div class="card">' +
          '<div class="awb-summary">' +
            '<div class="awb-k">Airway Bill</div>' +
            '<div class="awb-num">' + U.esc(m.awb || m.id) + '</div>' +
            '<div class="awb-sub">' + U.esc(m.courier_name || 'Courier') + ' · tracked shipment</div>' +
            '<div class="awb-row">' +
              '<div class="kv"><div class="k">Packages</div><div class="v">' + m.packages.length + '</div></div>' +
              '<div class="kv"><div class="k">Units</div><div class="v">' + m.assets.length + '</div></div>' +
              '<div class="kv"><div class="k">Weight</div><div class="v">' + U.esc(m.weight || '—') + ' kg</div></div>' +
            '</div>' +
            '<div class="awb-row">' +
              '<div class="kv"><div class="k">Origin</div><div class="v">' + U.esc(site ? site.city : '—') + '</div></div>' +
              '<div class="kv"><div class="k">Destination</div><div class="v">' + U.esc(m.destination) + '</div></div>' +
              '<div class="kv"><div class="k">Status</div><div class="v">' + U.esc(U.status(m.status).label) + '</div></div>' +
            '</div>' +
          '</div>' +
          '<div class="card-row"><div class="btn-row">' +
            '<button class="btn btn-outline xs" data-act="mov-track" data-arg="' + m.id + '">Track</button>' +
            (m.status === 'in_transit' ?
              '<button class="btn btn-outline xs" data-act="mov-rto" data-arg="' + m.id + '">RTO / exception</button>' : '') +
          '</div></div></div>';
      });
      h += '<div class="pad-x mt8"><button class="btn btn-outline block" data-act="export-awb">⬇ Export AWB log (CSV)</button></div>';
      return h;
    }
  };

  /* =========================================================
     WAREHOUSE RECEIPT (FR-019, BR-09)
     ========================================================= */
  Sc.warehouse = {
    title: 'Warehouse Receipt',
    render: function () {
      var inbound = S.db.movements.filter(function (m) { return m.status === 'in_transit'; });
      var receipts = S.db.receipts.slice().reverse();
      var open = receipts.filter(function (r) { return r.discrepancy && r.discrepancy_status === 'open'; });
      var h = '';

      h += '<div class="stats-row">' +
        '<div class="stat-card"><div class="stat-val">' + inbound.length + '</div><div class="stat-label">Inbound in transit</div></div>' +
        '<div class="stat-card highlight"><div class="stat-val">' + receipts.length + '</div><div class="stat-label">GRNs recorded</div></div>' +
        '<div class="stat-card"><div class="stat-val">' + open.length + '</div><div class="stat-label">Open discrepancies</div></div>' +
        '<div class="stat-card"><div class="stat-val">' + receipts.reduce(function (a, r) { return a + r.received_count; }, 0) +
        '</div><div class="stat-label">Units received</div></div>' +
      '</div>';

      h += '<div class="section-label">Expected inbound</div>';
      if (!inbound.length) h += U.empty('🚚', 'Nothing in transit', '');
      else h += '<div class="card">' + inbound.map(function (m) {
        var site = S.site(m.site_id);
        var age = S.hoursSince(m.created_at);
        var late = age > S.db.config.sla.wh_total_breach_h;
        return '<div class="card-row col' + (late ? ' fail-bg' : '') + '">' +
          '<div class="row-between"><b>' + U.esc(m.id + (m.awb ? ' · ' + m.awb : '')) + '</b>' +
          U.pill(S.fmtAge(age), late ? 'fail' : 'gray') + '</div>' +
          '<div class="small muted">' + U.esc(site ? site.site : '') + ' · expected ' + m.assets.length + ' units · ' +
          U.esc(m.mode === 'courier' ? m.courier_name : m.vehicle) + '</div>' +
          '<div class="btn-row mt6"><button class="btn btn-primary xs" data-act="wh-receive" data-arg="' + m.id + '">Receive / GRN</button>' +
          '<button class="btn btn-outline xs" data-act="mov-track" data-arg="' + m.id + '">Track</button></div></div>';
      }).join('') + '</div>';

      h += '<div class="section-label">Goods receipt notes</div>';
      if (!receipts.length) h += U.empty('🏷️', 'No GRN recorded yet', '');
      else h += '<div class="card">' + receipts.map(function (r) {
        var site = S.site(r.site_id);
        return '<div class="card-row col">' +
          '<div class="row-between"><b>' + U.esc(r.grn) + '</b>' +
          U.pill(r.discrepancy ? (r.discrepancy_status === 'resolved' ? 'Discrepancy resolved' : 'Discrepancy open') : 'Clean receipt',
                 r.discrepancy ? (r.discrepancy_status === 'resolved' ? 'warn' : 'fail') : 'ok') + '</div>' +
          '<div class="small muted">' + U.esc(site ? site.site : '') + ' · expected ' + r.expected_count +
          ' / received ' + r.received_count + ' · variance ' + (r.variance > 0 ? '+' : '') + r.variance +
          ' · seal ' + U.esc(r.seal_status) + '</div>' +
          '<div class="small muted">' + U.esc(r.received_by) + ' · ' + U.dt(r.received_at) + '</div>' +
          (r.damage === 'Yes' ? '<div class="small err">Visible damage: ' + U.esc(r.damage_note) + '</div>' : '') +
          (r.discrepancy && r.discrepancy_status === 'open' ?
            '<div class="btn-row mt6"><button class="btn btn-primary xs" data-act="wh-resolve" data-arg="' + r.id + '">Record disposition</button></div>' +
            '<div class="small muted mt4">BR-09: asset closure locked until disposition is agreed.</div>' : '') +
          (r.resolution ? '<div class="small muted">Disposition: ' + U.esc(r.resolution) + ' · ' + U.esc(r.resolved_by) + '</div>' : '') +
          '</div>';
      }).join('') + '</div>';
      return h;
    }
  };

  A['wh-receive'] = function (el) {
    var m = S.movement(el.getAttribute('data-arg'));
    var photoHolder = { p: null };
    U.modal({
      title: 'Warehouse receipt — ' + m.id,
      body: '<div class="kv-grid">' + kv('Expected units', String(m.assets.length)) +
        kv('Origin', (S.site(m.site_id) || {}).site || '—') +
        kv('Mode', m.mode === 'courier' ? m.courier_name : m.vehicle) + '</div>' +
        U.field('Received count', U.input('wh-count', '', String(m.assets.length), 'number')) +
        U.field('Seal status', U.select('wh-seal', ['Intact', 'Tampered', 'Broken', 'Missing'], 'Intact')) +
        U.field('Seal number', U.input('wh-sealno', 'as on package', '')) +
        U.field('Visible damage', U.select('wh-damage', ['No', 'Yes'], 'No')) +
        U.field('Damage note', U.input('wh-dnote', 'if any', '')) +
        U.field('Discrepancy owner (if any)', U.select('wh-owner', ['—', 'Transporter', 'Packing partner', 'Site / SPOC', 'Warehouse', 'Under review'], '—')) +
        '<button class="btn btn-outline sm mt8" id="wh-photo">📷 Receipt photo</button><div id="wh-prev"></div>',
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
              '<button class="btn btn-primary" id="wh-go">Record GRN</button>',
      onOpen: function (host) {
        host.querySelector('#wh-photo').addEventListener('click', function () {
          U.pickPhoto('grn', function (p) {
            photoHolder.p = p;
            host.querySelector('#wh-prev').innerHTML = '<img class="thumb mt8" src="' + p.data + '" />';
          });
        });
        host.querySelector('#wh-go').addEventListener('click', function () {
          try {
            var r = S.receive({
              movement_id: m.id, received_count: U.val('wh-count'),
              seal_status: U.val('wh-seal'), seal_no: U.val('wh-sealno'),
              damage: U.val('wh-damage'), damage_note: U.val('wh-dnote'),
              discrepancy_owner: U.val('wh-owner') === '—' ? '' : U.val('wh-owner'),
              photo: photoHolder.p
            });
            U.closeModal();
            U.toast(r.grn + ' recorded' + (r.discrepancy ? ' — discrepancy raised, PMO alerted' : ''),
              r.discrepancy ? 'warn' : 'success');
            RA.render();
          } catch (e) { U.toast(e.message, 'error'); }
        });
      }
    });
  };

  A['wh-resolve'] = function (el) {
    var id = el.getAttribute('data-arg');
    U.modal({
      title: 'Discrepancy disposition',
      body: U.field('Agreed disposition', U.select('ds-type', [
        'Short quantity accepted — inventory adjusted',
        'Unit traced and received separately',
        'Damage accepted — commercial hold raised',
        'Carrier claim initiated',
        'Site re-count confirmed original quantity'], 'Short quantity accepted — inventory adjusted')) +
        U.field('Note', U.input('ds-note', '', '')),
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
              '<button class="btn btn-primary" id="ds-go">Record disposition</button>',
      onOpen: function (host) {
        host.querySelector('#ds-go').addEventListener('click', function () {
          S.resolveDiscrepancy(id, U.val('ds-type') + (U.val('ds-note') ? ' — ' + U.val('ds-note') : ''));
          U.closeModal(); U.toast('Disposition recorded — closure unlocked', 'success'); RA.render();
        });
      }
    });
  };

})(window.RA = window.RA || {});
