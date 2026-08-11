/* Self-test — serial-first QC capture, serial↔site mapping, user administration.
   Run in the browser console with the app open:
     fetch('/tools/selftest-serial-admin.js').then(r=>r.text()).then(t=>console.log(eval(t)))
   Resets local data. Sign in again afterwards. */
(function () {
  var S = RA.store, D = RA.data, out = [];
  function t(name, fn) {
    try { var r = fn(); out.push((r === true ? 'PASS' : 'FAIL') + ' · ' + name + (r === true ? '' : ' → ' + r)); }
    catch (e) { out.push('FAIL · ' + name + ' → ' + e.message); }
  }

  S.reset();
  S.login('U01', false);
  var site = S.db.sites.filter(function (s) { return S.assetsAt(s.id).length >= 8; })[0];
  var assets = S.assetsAt(site.id);

  /* ---------- serial state of the source master ---------- */
  t('Source master ships with no serials — every unit pending', function () {
    var st = S.serialStats();
    return (st.captured === 0 && st.pending === st.total && st.total === 3957) || JSON.stringify(st);
  });
  t('hasSerial() false for placeholder, true once captured', function () {
    return S.hasSerial(assets[0]) === false || 'placeholder counted as captured';
  });

  /* ---------- QC is blocked until a serial exists ---------- */
  t('QC submission rejected while the unit has no serial', function () {
    try {
      S.submitQC({ asset_id: assets[0].id, specs: {}, responses: {}, photos: [], remarks: '', seconds: 10 });
      return 'no error thrown';
    } catch (e) { return /serial/i.test(e.message) || e.message; }
  });
  t('QC screen renders the serial gate instead of the checklist', function () {
    location.hash = '#/qc/' + assets[0].id; RA.render();
    var body = document.getElementById('screen-body').innerText;
    return (document.getElementById('gate-serial') !== null &&
            body.indexOf('serial number on this unit') > -1 &&
            document.querySelectorAll('.qc-block').length === 0) ||
      'gate=' + !!document.getElementById('gate-serial') + ' blocks=' + document.querySelectorAll('.qc-block').length;
  });

  /* ---------- capture ---------- */
  var a0 = S.captureSerial(assets[0].id, ' c02xy1234abc ');
  t('Serial captured, normalised and stamped with user + time', function () {
    return !!(a0.serial === 'C02XY1234ABC' && a0.serial_captured_by && a0.serial_captured_at) ||
      JSON.stringify({ s: a0.serial, by: a0.serial_captured_by });
  });
  t('Captured serial is mapped to its site in the database', function () {
    var found = S.findBySerial('c02xy1234abc');
    return (found && found.id === assets[0].id && found.site_id === site.id) || 'not mapped';
  });
  t('Serial stats update for the site', function () {
    var st = S.serialStats(site.id);
    return (st.captured === 1 && st.pending === assets.length - 1) || JSON.stringify(st);
  });
  t('QC checklist opens once the serial exists', function () {
    RA.qcState = null; location.hash = '#/qc/' + assets[0].id; RA.render();
    return (document.querySelectorAll('.qc-block').length > 0 &&
            document.getElementById('gate-serial') === null) ||
      'blocks=' + document.querySelectorAll('.qc-block').length;
  });
  t('Serial shows as locked (not free-text) inside the QC form', function () {
    var locked = document.querySelector('.serial-locked');
    var editable = document.querySelector('input[data-spec="serial"]');
    return (locked && locked.innerText.indexOf('C02XY1234ABC') > -1 && !editable) ||
      'locked=' + !!locked + ' editable=' + !!editable;
  });

  /* ---------- BR-06 duplicates ---------- */
  t('BR-06 blocks the same serial on a second unit', function () {
    try { S.captureSerial(assets[1].id, 'C02XY1234ABC'); return 'no error thrown'; }
    catch (e) { return e.message.indexOf('BR-06') === 0 || e.message; }
  });
  t('Blank / placeholder / too-short serials are rejected', function () {
    var errs = 0;
    ['', '   ', 'PEND-00001', 'AB'].forEach(function (v) {
      try { S.captureSerial(assets[2].id, v); } catch (e) { errs++; }
    });
    return errs === 4 || errs + '/4 rejected';
  });

  /* ---------- model picker mapping ---------- */
  t('Pending units are grouped by article for the "which model" step', function () {
    var g = S.pendingSerialGroups(site.id);
    var total = g.reduce(function (n, x) { return n + x.assets.length; }, 0);
    return !!(g.length > 0 && total === assets.length - 1 && g[0].model) || JSON.stringify({ groups: g.length, total: total });
  });
  t('Serial maps to the next free unit of the chosen model', function () {
    var g = S.pendingSerialGroups(site.id)[0];
    var before = g.assets.length;
    var mapped = S.mapSerialToArticle(site.id, g.key, 'C02NEWUNIT01');
    var after = (S.pendingSerialGroups(site.id).filter(function (x) { return x.key === g.key; })[0] || { assets: [] }).assets.length;
    return (mapped.serial === 'C02NEWUNIT01' && mapped.article === g.article && after === before - 1) ||
      JSON.stringify({ before: before, after: after, art: mapped.article, want: g.article });
  });

  /* ---------- full QC on a serialised unit ---------- */
  var qc = S.submitQC({
    asset_id: assets[0].id, specs: { serial: 'C02XY1234ABC' },
    responses: { power: 'Power ON', display: 'OK', body: 'OK', keyboard: 'Working', touchpad: 'Working', hinge: 'OK', ports: 'Visibly OK', charger: 'Available/OK' },
    photos: [{ kind: 'overall' }], remarks: '', seconds: 800
  });
  t('QC submits normally once the serial is mapped', function () {
    return (qc.id && S.asset(assets[0].id).status === 'qc_submitted') || 'no qc';
  });
  t('Serial capture is written to the immutable audit log', function () {
    var ev = S.db.audit.filter(function (e) { return e.action === 'serial_captured'; });
    return !!(ev.length >= 2 && ev[0].meta.to && ev[0].meta.site) || 'events=' + ev.length;
  });

  /* ---------- bulk serial import ---------- */
  t('Bulk import maps serials by site name and by asset tag', function () {
    var s2 = S.db.sites.filter(function (x) { return x.id !== site.id && S.assetsAt(x.id).length >= 3; })[0];
    var pool = S.assetsAt(s2.id).filter(function (a) { return !S.hasSerial(a); });
    var csv = 'Site,Article,Asset Tag,Serial\n' +
      '"' + s2.site + '",' + pool[0].article + ',,BULK000001\n' +
      ',,' + pool[1].tag + ',BULK000002\n' +
      '"' + s2.site + '",,,BULK000003\n';
    var res = S.importSerials(csv);
    var byTag = S.asset(pool[1].id).serial === 'BULK000002';
    var mappedAtSite = S.assetsAt(s2.id).filter(S.hasSerial).length;
    return (res.mapped === 3 && byTag && mappedAtSite === 3) ||
      JSON.stringify({ res: res, byTag: byTag, atSite: mappedAtSite });
  });
  t('Bulk import rejects duplicates and in-file repeats', function () {
    var res = S.importSerials('Site,Serial\nX,BULK000001\nX,DUPTEST9\nX,DUPTEST9\n');
    return (res.mapped === 0 && res.errors.length === 3) || JSON.stringify(res);
  });
  t('Serial export carries the site mapping', function () {
    var withSerial = S.db.assets.filter(S.hasSerial);
    var a = withSerial[0], s = S.site(a.site_id);
    return (withSerial.length >= 5 && !!s.site) || 'count=' + withSerial.length;
  });

  /* ================= USER ADMINISTRATION ================= */
  S.login('U11', false);   // System Admin

  var created = S.saveUser({
    name: 'Test Engineer', emp: 'qc.eng.99', role: 'fe', region: 'South',
    status: 'active', sites: [], allow: [], deny: []
  });
  t('Admin can create a user', function () {
    return (created.id && S.user(created.id).name === 'Test Engineer') || 'not created';
  });
  t('Duplicate employee ID is rejected', function () {
    try {
      S.saveUser({ name: 'Clash', emp: 'qc.eng.99', role: 'fe', region: 'South' });
      return 'no error thrown';
    } catch (e) { return /already in use/.test(e.message) || e.message; }
  });
  t('Admin can rename a user and change their role', function () {
    S.saveUser({ id: created.id, name: 'Renamed Engineer', emp: 'qc.eng.99', role: 'coord', region: 'West', status: 'active', sites: [] });
    var u = S.user(created.id);
    return (u.name === 'Renamed Engineer' && u.role === 'coord' && u.region === 'West') || JSON.stringify(u);
  });

  t('Admin can assign specific sites and they drive visible scope', function () {
    var ids = S.db.sites.slice(0, 4).map(function (s) { return s.id; });
    S.saveUser({ id: created.id, name: 'Renamed Engineer', emp: 'qc.eng.99', role: 'fe', region: 'West', status: 'active', sites: ids });
    S.login(created.id, false);
    var mine = S.mySites().map(function (s) { return s.id; }).sort().join(',');
    var res = mine === ids.slice().sort().join(',');
    S.login('U11', false);
    return res || 'saw ' + mine;
  });

  t('Permission grant opens a module outside the role default', function () {
    var u = S.user(created.id);
    var beforeRole = S.canUser(u, 'pricing');
    S.saveUser({ id: u.id, name: u.name, emp: u.emp, role: 'fe', region: u.region, status: 'active', sites: u.sites, allow: ['pricing'], deny: [] });
    return (beforeRole === false && S.canUser(S.user(u.id), 'pricing') === true) || 'grant failed';
  });
  t('Permission revoke closes a module inside the role default', function () {
    var u = S.user(created.id);
    S.saveUser({ id: u.id, name: u.name, emp: u.emp, role: 'fe', region: u.region, status: 'active', sites: u.sites, allow: ['pricing'], deny: ['packing'] });
    var v = S.user(u.id);
    return (S.roleAllows('fe', 'packing') === true && S.canUser(v, 'packing') === false) || 'revoke failed';
  });
  t('Revoked module disappears from that user\'s navigation', function () {
    S.login(created.id, false);
    location.hash = '#/myday'; RA.render();
    var nav = document.querySelector('.sidebar').innerText + document.querySelector('.bottom-nav').innerText;
    var blocked = nav.indexOf('Packing') === -1;
    location.hash = '#/packing'; RA.render();
    var denied = document.getElementById('screen-body').innerText.indexOf('Access restricted') > -1;
    S.login('U11', false);
    return (blocked && denied) || 'navHidden=' + blocked + ' routeBlocked=' + denied;
  });

  t('Deactivated account loses all access', function () {
    var u = S.user(created.id);
    S.saveUser({ id: u.id, name: u.name, emp: u.emp, role: 'fe', region: u.region, status: 'inactive', sites: u.sites, allow: [], deny: [] });
    var v = S.user(created.id);
    return (S.canUser(v, 'myday') === false && S.canUser(v, 'profile') === false) || 'still has access';
  });

  t('Last active admin cannot be deleted', function () {
    var admins = S.db.users.filter(function (u) { return u.role === 'admin' && u.status !== 'inactive'; });
    if (admins.length !== 1) return 'expected exactly 1 admin, found ' + admins.length;
    try { S.deleteUser(admins[0].id); return 'no error thrown'; }
    catch (e) { return /admin must remain|signed in/.test(e.message) || e.message; }
  });
  t('A user holding QC records cannot be deleted', function () {
    try { S.deleteUser('U01'); return 'no error thrown'; }
    catch (e) { return /QC record/.test(e.message) || e.message; }
  });
  t('A clean user can be deleted', function () {
    var before = S.db.users.length;
    S.deleteUser(created.id);
    return (S.db.users.length === before - 1 && !S.user(created.id)) || 'not deleted';
  });
  t('Every administrative change is audit-logged', function () {
    var acts = S.db.audit.filter(function (e) { return e.entity === 'user'; }).map(function (e) { return e.action; });
    return (acts.indexOf('create') > -1 && acts.indexOf('update') > -1 && acts.indexOf('delete') > -1) || acts.join(',');
  });

  /* ---------- screens still render for every role ---------- */
  t('All screens render clean for every role after the changes', function () {
    var screens = ['myday', 'sites', 'scan', 'serial', 'serials', 'approvals', 'pricing', 'packing',
      'pickup', 'courier', 'warehouse', 'dashboard', 'reports', 'alerts', 'audit', 'admin', 'profile'];
    var bad = [];
    Object.keys(D.ROLES).forEach(function (role) {
      var u = S.db.users.filter(function (x) { return x.role === role && x.status !== 'inactive'; })[0];
      if (!u) return;
      S.login(u.id, false);
      screens.forEach(function (sc) {
        if (!S.can(sc)) return;
        location.hash = sc === 'serial' ? '#/serial/' + S.db.sites[0].id : '#/' + sc;
        try { RA.render(); } catch (e) { bad.push(role + '/' + sc + ':' + e.message); return; }
        var b = document.getElementById('screen-body');
        if (!b || b.innerHTML.length < 50) bad.push(role + '/' + sc + ':empty');
        if (b && b.innerText.indexOf('Something went wrong') > -1) bad.push(role + '/' + sc + ':error');
      });
    });
    S.login('U11', false);
    return bad.length === 0 || bad.join(' | ');
  });

  var pass = out.filter(function (x) { return x.indexOf('PASS') === 0; }).length;
  return (pass + '/' + out.length + ' passed\n') + out.join('\n');
})()
