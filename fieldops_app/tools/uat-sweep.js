/* UAT sweep — walks every screen as every role and reports anything broken.

   Looks for the failures a person would actually hit: a screen that will not
   render, a button wired to nothing, a link pointing at a screen that does not
   exist, a nav entry that goes nowhere, a form control with no handler.

     fetch('tools/uat-sweep.js').then(r=>r.text()).then(t=>eval(t)).then(console.log)

   Read-only: it renders and inspects, and never clicks anything destructive.
   Resets local data at the start so every role sees the same ground truth. */
(function () {
  var S = RA.store, D = RA.data;
  var issues = [], checked = { screens: 0, controls: 0, links: 0 };

  function note(severity, where, what) {
    issues.push({ severity: severity, where: where, what: what });
  }

  var ROUTES = {
    myday: '#/myday', sites: '#/sites', scan: '#/scan', serials: '#/serials',
    approvals: '#/approvals', pricing: '#/pricing', packing: '#/packing',
    pickup: '#/pickup', courier: '#/courier', warehouse: '#/warehouse',
    dashboard: '#/dashboard', reports: '#/reports', alerts: '#/alerts',
    audit: '#/audit', admin: '#/admin', profile: '#/profile'
  };

  S.reset();
  if (S.db.sync) S.db.sync.enabled = false;      // don't push UAT noise upstream

  /* Give the workflow screens something to show, so empty states don't mask
     broken controls. One unit taken all the way through the chain. */
  function seedOneOfEverything() {
    S.login('U01', false);
    var site = S.db.sites[0];
    var a = S.assetsAt(site.id)[0];
    S.captureSerial(a.id, 'UAT0000001');
    var qc = S.submitQC({
      asset_id: a.id, specs: { serial: 'UAT0000001' },
      responses: { power: 'Power ON', display: 'OK', body: 'Scratch', keyboard: 'Working',
                   touchpad: 'Working', hinge: 'OK', ports: 'Visibly OK', charger: 'Missing' },
      photos: [{ kind: 'overall' }, { kind: 'defect' }], remarks: 'uat', seconds: 720
    });
    S.login('U06', false);
    S.decideQC(qc.id, 'accepted', null);
    S.login('U08', false);
    var pkg = S.createPackage(site.id, [a.id], 'Carton', 'UAT-SEAL-1', '', null);
    var mov = S.createMovement({ mode: 'pickup', site_id: site.id, packages: [pkg.id],
      vehicle: 'MH-01-AA-0001', driver: 'UAT Driver', gate_pass: 'GP-UAT' });
    S.login('U10', false);
    S.receive({ movement_id: mov.id, received_count: 1, seal_status: 'Intact',
                seal_no: 'UAT-SEAL-1', damage: 'No', damage_note: '', discrepancy_owner: '' });
    /* a second unit left mid-flow so queues are not all empty */
    S.login('U01', false);
    var b = S.assetsAt(site.id)[1];
    S.captureSerial(b.id, 'UAT0000002');
    S.submitQC({
      asset_id: b.id, specs: { serial: 'UAT0000002' },
      responses: { power: 'Power ON', display: 'OK', body: 'OK', keyboard: 'Working',
                   touchpad: 'Working', hinge: 'OK', ports: 'Visibly OK', charger: 'Available/OK' },
      photos: [{ kind: 'overall' }], remarks: '', seconds: 640
    });
  }
  seedOneOfEverything();

  /* ---------- the sweep ---------- */
  Object.keys(D.ROLES).forEach(function (role) {
    var user = S.db.users.filter(function (u) {
      return u.role === role && u.status !== 'inactive';
    })[0];
    if (!user) { note('warn', 'roles', 'no account exists for role ' + role); return; }
    S.login(user.id, false);

    Object.keys(ROUTES).forEach(function (key) {
      if (!S.can(key)) return;
      var where = role + ' → ' + key;

      location.hash = ROUTES[key];
      try { RA.render(); }
      catch (e) { note('blocker', where, 'render threw: ' + e.message); return; }
      checked.screens++;

      var body = document.getElementById('screen-body');
      if (!body) { note('blocker', where, 'no screen body rendered'); return; }
      var text = body.innerText || '';
      if (text.indexOf('Something went wrong') > -1) {
        note('blocker', where, 'error card shown on screen');
      }
      if (text.indexOf('Screen not found') > -1) {
        note('blocker', where, 'screen is not registered');
      }
      if (body.innerHTML.length < 60) note('major', where, 'screen rendered empty');

      /* every actionable control must resolve to a handler */
      body.querySelectorAll('[data-act]').forEach(function (el) {
        checked.controls++;
        var act = el.getAttribute('data-act');
        if (!RA.actions[act]) {
          note('blocker', where, 'control "' + (el.textContent || '').trim().slice(0, 32) +
               '" has no handler for action "' + act + '"');
        }
      });

      /* every internal link must point at a screen that exists */
      body.querySelectorAll('a[href^="#/"]').forEach(function (el) {
        checked.links++;
        var target = el.getAttribute('href').replace(/^#\//, '').split('/')[0];
        if (!RA.screens[target]) {
          note('blocker', where, 'link "' + (el.textContent || '').trim().slice(0, 32) +
               '" points at missing screen "' + target + '"');
        } else if (!S.can(target)) {
          note('major', where, 'link "' + (el.textContent || '').trim().slice(0, 32) +
               '" points at "' + target + '" which this role cannot open');
        }
      });

      /* chrome: header, nav and drawer are part of every screen */
      var shell = document.getElementById('app');
      shell.querySelectorAll('.bottom-nav a, .sidebar a, #drawer a').forEach(function (el) {
        var href = el.getAttribute('href') || '';
        if (href.indexOf('#/') !== 0) return;
        var target = href.replace(/^#\//, '').split('/')[0];
        if (!RA.screens[target]) {
          note('blocker', where, 'nav entry "' + (el.textContent || '').trim() +
               '" points at missing screen "' + target + '"');
        }
      });
      shell.querySelectorAll('.app-header [data-act], #drawer [data-act]').forEach(function (el) {
        var act = el.getAttribute('data-act');
        if (!RA.actions[act]) {
          note('blocker', where, 'header/drawer control has no handler for "' + act + '"');
        }
      });
    });
  });

  /* ---------- the drawer actually navigates ---------- */
  S.login('U11', false);
  location.hash = '#/admin'; RA.render();
  var burger = document.querySelector('[data-act="drawer"]');
  if (!burger) {
    note('major', 'chrome', 'no menu button rendered on a top-level screen');
  } else {
    burger.click();
    var drawer = document.getElementById('drawer');
    if (!drawer || !drawer.classList.contains('open')) {
      note('blocker', 'chrome', 'the menu button does not open the drawer');
    } else {
      var link = drawer.querySelector('a[href="#/dashboard"]');
      if (!link) note('major', 'chrome', 'drawer has no Dashboard entry');
      else {
        var before = location.hash;
        link.click();
        if (location.hash === before) {
          note('blocker', 'chrome', 'drawer menu items do not navigate');
        }
        RA.render();
        if (document.getElementById('drawer').classList.contains('open')) {
          note('minor', 'chrome', 'drawer stays open after choosing an item');
        }
      }
    }
  }

  /* ---------- deep routes ---------- */
  S.login('U11', false);
  var deep = [
    ['#/site/' + S.db.sites[0].id, 'site detail'],
    ['#/asset/' + S.db.assets[0].id, 'asset detail'],
    ['#/serial/' + S.db.sites[0].id, 'serial capture'],
    ['#/qc/' + S.db.assets[0].id, 'QC screen'],
    ['#/nonsense-route', 'unknown route']
  ];
  deep.forEach(function (pair) {
    location.hash = pair[0];
    try { RA.render(); } catch (e) { note('blocker', pair[1], 'render threw: ' + e.message); return; }
    var t = (document.getElementById('screen-body') || {}).innerText || '';
    if (pair[1] === 'unknown route') {
      if (t.indexOf('Screen not found') === -1) note('minor', pair[1], 'no friendly message for a bad URL');
    } else if (t.indexOf('Something went wrong') > -1) {
      note('blocker', pair[1], 'error card shown');
    }
  });

  /* ---------- admin tabs ---------- */
  ['users', 'charges', 'serials', 'upload', 'deduction', 'config', 'delete', 'data'].forEach(function (tab) {
    RA.filters.adminTab = tab;
    location.hash = '#/admin';
    try { RA.render(); } catch (e) { note('blocker', 'admin/' + tab, 'render threw: ' + e.message); return; }
    var b = document.getElementById('screen-body');
    var t = (b || {}).innerText || '';
    if (t.indexOf('Something went wrong') > -1) note('blocker', 'admin/' + tab, 'error card shown');
    if (b && b.innerHTML.length < 200) note('major', 'admin/' + tab, 'tab rendered nearly empty');
    if (b) b.querySelectorAll('[data-act]').forEach(function (el) {
      var act = el.getAttribute('data-act');
      if (!RA.actions[act]) {
        note('blocker', 'admin/' + tab, 'control "' + (el.textContent || '').trim().slice(0, 30) +
             '" has no handler for "' + act + '"');
      }
    });
  });

  /* ---------- modals open and close ---------- */
  var modalChecks = [
    ['usr-edit', '', 'add user'],
    ['scan-open', '', 'scanner'],
    ['change-password', '', 'change password']
  ];
  S.login('U11', false);
  RA.filters.adminTab = 'users'; location.hash = '#/admin'; RA.render();
  modalChecks.forEach(function (m) {
    try {
      RA.actions[m[0]]({ getAttribute: function () { return m[1]; } });
      var open = document.querySelector('#modal-host.open');
      if (!open) note('major', 'modal: ' + m[2], 'did not open');
      RA.ui.closeModal();
      if (document.querySelector('#modal-host.open')) note('major', 'modal: ' + m[2], 'did not close');
    } catch (e) {
      note('blocker', 'modal: ' + m[2], 'threw: ' + e.message);
    }
  });

  S.reset();
  var order = { blocker: 0, major: 1, minor: 2, warn: 3 };
  issues.sort(function (a, b) { return order[a.severity] - order[b.severity]; });
  var counts = issues.reduce(function (m, i) { m[i.severity] = (m[i.severity] || 0) + 1; return m; }, {});

  return 'UAT sweep — ' + checked.screens + ' screen renders, ' + checked.controls +
    ' controls, ' + checked.links + ' links\n' +
    (issues.length
      ? Object.keys(counts).map(function (k) { return counts[k] + ' ' + k; }).join(', ') + '\n\n' +
        issues.map(function (i) {
          return '[' + i.severity.toUpperCase() + '] ' + i.where + ' — ' + i.what;
        }).join('\n')
      : 'no issues found');
})()
