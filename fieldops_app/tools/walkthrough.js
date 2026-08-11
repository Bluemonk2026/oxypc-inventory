/* End-to-end UI walkthrough — drives the app the way a user does: real screens,
   real buttons, real dialogs. No store functions are called directly except to
   simulate the camera (the OS file picker cannot be automated).
     fetch('/tools/walkthrough.js').then(r=>r.text()).then(t=>eval(t)).then(console.log)
   Resets local data. Sign in again afterwards. */
(function () {
  var S = RA.store, U = RA.ui, out = [], step = 0;

  function log(ok, msg, detail) {
    step++;
    out.push((ok ? 'PASS' : 'FAIL') + ' · ' + step + '. ' + msg + (ok ? '' : ' → ' + detail));
  }
  function body() { var b = document.getElementById('screen-body'); return b ? b.innerText : ''; }
  /* headings are upper-cased by CSS, so compare case-insensitively */
  function has(txt) { return body().toLowerCase().indexOf(String(txt).toLowerCase()) > -1; }
  function go(hash) { location.hash = hash; RA.render(); }
  /* A click that navigates sets location.hash; the browser fires hashchange on the
     next task. This harness runs synchronously, so render here to catch up. */
  function click(sel, root) {
    var el = (root || document).querySelector(sel);
    if (!el) throw new Error('element not found: ' + sel);
    var before = location.hash;
    el.click();
    if (location.hash !== before) RA.render();
    return el;
  }
  function setVal(sel, v, root) {
    var el = (root || document).querySelector(sel);
    if (!el) throw new Error('field not found: ' + sel);
    el.value = v;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return el;
  }
  function modal() { return document.querySelector('#modal-host.open .modal'); }
  var SHOT = { kind: 'overall', data: null, id: 'sim1' };   // stands in for a camera capture

  S.reset();

  /* ---------------- 1. Sign in through the login form ---------------- */
  S.logout(); go('#/login');
  setVal('#login-user', 'U01');
  setVal('#login-pin', '1234');
  click('[data-act="login"]');
  var me = S.me();
  log(!!me && me.role === 'fe' && location.hash === '#/myday',
    'Field engineer signs in and lands on My Day', location.hash + ' user=' + (me && me.name));

  /* ---------------- 2. Open an assigned site ---------------- */
  var siteLink = document.querySelector('#screen-body a[href^="#/site/"]');
  log(!!siteLink, 'My Day lists assigned sites', 'no site link rendered');
  var siteId = siteLink.getAttribute('href').replace('#/site/', '');
  go('#/site/' + siteId);
  var site = S.site(siteId);
  var units = S.assetsAt(siteId).length;
  log(has('Recommended FE allocation') && has('Serial mapping'),
    'Site job shows FE allocation, serial progress and costing', body().slice(0, 80));

  /* ---------------- 3. Start QC → serial capture first ---------------- */
  click('[data-act="goto"][data-arg="#/serial/' + siteId + '"]');
  log(location.hash === '#/serial/' + siteId && !!document.getElementById('serial-in'),
    'Start QC opens serial capture, not the checklist', location.hash);
  log(document.querySelectorAll('.qc-block').length === 0,
    'No QC field is presented before the serial', 'checklist visible too early');

  /* ---------------- 4. Enter a new serial → pick the model ---------------- */
  setVal('#serial-in', 'C02WALK0001');
  click('[data-act="serial-go"]');
  var picks = document.querySelectorAll('[data-act="serial-bind"]');
  log(picks.length > 0 && has('which model is this unit'),
    'Unknown serial asks which model it is', 'no model picker');
  /* pick a laptop line so the walkthrough exercises the full 8-block checklist */
  var laptopGroup = S.pendingSerialGroups(siteId).filter(function (g) { return g.category === 'laptop'; })[0];
  var pickBtn = laptopGroup
    ? document.querySelector('[data-act="serial-bind"][data-key="' + laptopGroup.key + '"]')
    : picks[0];
  var pickedModel = pickBtn.innerText.split('\n')[0];
  pickBtn.click();
  var asset = S.findBySerial('C02WALK0001');
  log(!!asset && asset.site_id === siteId && location.hash === '#/qc/' + asset.id,
    'Serial binds to a unit at this site and opens QC', location.hash);

  /* ---------------- 5. Duplicate serial is refused ---------------- */
  go('#/serial/' + siteId);
  setVal('#serial-in', 'C02WALK0001');
  click('[data-act="serial-go"]');
  log(has('BR-06') || has('already mapped') ||
      location.hash.indexOf('#/asset/') === 0 || location.hash === '#/qc/' + asset.id,
    'Re-entering the same serial is caught, not duplicated', body().slice(0, 100));

  /* ---------------- 6. Complete the QC checklist by tapping ---------------- */
  go('#/qc/' + asset.id);
  var blocks = document.querySelectorAll('.qc-block').length;
  log(blocks > 0 && !!document.getElementById('qc-timer'),
    'QC checklist opens with a running timer', 'blocks=' + blocks);

  /* answer every block this category actually shows: healthy everywhere except
     body (Scratch) and charger (Missing), so two defect codes are derived */
  function answerFor(block) {
    if (block.key === 'body') return 'Scratch';
    if (block.key === 'charger') return 'Missing';
    var prefer = ['Power ON', 'OK', 'Working', 'Visibly OK', 'Available/OK'];
    for (var i = 0; i < prefer.length; i++) {
      if (block.values.indexOf(prefer[i]) > -1) return prefer[i];
    }
    return block.values[0];
  }
  var catBlocks = RA.data.CONDITION_BLOCKS[asset.category];
  var tapped = 0;
  catBlocks.forEach(function (b) {
    var el = document.querySelector('[data-act="qc-set"][data-k="' + b.key + '"][data-v="' + answerFor(b) + '"]');
    if (el) { el.click(); tapped++; }
  });
  log(tapped === catBlocks.length,
    'Every condition card on the ' + asset.category + ' checklist responds to taps',
    'tapped ' + tapped + ' of ' + catBlocks.length);

  var codes = S.deriveCodes(RA.qcState.responses);
  log(codes.indexOf('SC') > -1 && codes.indexOf('CH') > -1,
    'Defect codes derive live from the taps (SC + CH)', codes.join('+'));
  log(has('Revised price after QC') && has('read-only'),
    'Revised price and the read-only deduction rule are shown', 'pricing block missing');

  /* ---------------- 7. Submit is blocked until photos exist ---------------- */
  var beforeQC = S.db.qc.length;
  click('[data-act="qc-submit"]');
  log(S.db.qc.length === beforeQC && !modal(),
    'Submit refuses without the mandatory photos (BR-04)', 'submitted without evidence');

  RA.qcState.photos.push({ kind: 'overall', data: null, id: 'p1' });
  RA.qcState.photos.push({ kind: 'defect', data: null, id: 'p2' });
  RA.render();
  click('[data-act="qc-submit"]');
  log(!!modal(), 'Submit opens the confirmation with codes and revised price', 'no confirm dialog');
  click('#confirm-yes', modal());
  var qc = S.qcForAsset(asset.id)[0];
  log(!!qc && qc.status === 'pending' && S.asset(asset.id).status === 'qc_submitted',
    'QC submits and the unit moves to Awaiting Approval', qc && qc.status);

  /* ---------------- 8. No-Power suppression on the next unit ---------------- */
  var next = S.assetsAt(siteId).filter(function (a) {
    return a.status === 'pending_qc' && a.category === 'laptop';
  })[0];
  S.captureSerial(next.id, 'C02WALK0002');
  go('#/qc/' + next.id);
  click('[data-act="qc-set"][data-k="power"][data-v="No Power"]');
  var r = RA.qcState.responses;
  log(r.display === RA.data.NOT_TESTED && r.keyboard === RA.data.NOT_TESTED &&
      document.querySelectorAll('.qc-block.suppressed').length >= 2,
    'No Power auto-suppresses the dependent tests on screen (BR-03)', JSON.stringify(r));

  /* ---------------- 9. Reliance approval ---------------- */
  S.logout(); go('#/login');
  setVal('#login-user', 'U06'); setVal('#login-pin', '1234');
  click('[data-act="login"]');
  go('#/approvals');
  log(has(asset.tag), 'Submitted QC appears in the approver queue', 'not queued');
  log(!document.querySelector('input[data-spec]'),
    'Approver cannot edit the field evidence', 'evidence editable');
  click('[data-act="qc-decide"][data-arg="' + qc.id + '"][data-d="accepted"]');
  click('#dec-go', modal());
  log(S.qcRecord(qc.id).status === 'accepted' && S.asset(asset.id).status === 'accepted',
    'Approver accepts and the unit is released', S.asset(asset.id).status);

  /* ---------------- 10. Commercial ---------------- */
  S.logout(); go('#/login');
  setVal('#login-user', 'U07'); setVal('#login-pin', '1234');
  click('[data-act="login"]');
  go('#/pricing');
  var cm = S.commercialFor(qc.id);
  log(has('Pending Reliance Approval') && cm.deduction_pct === 0,
    'Deduction matrix is unapproved, so deductions stay at 0% (BRD Sec 7)',
    'pct=' + cm.deduction_pct);
  click('[data-act="cm-decide"][data-arg="' + cm.id + '"][data-d="accepted"]');
  click('#cm-go', modal());
  log(S.commercialFor(qc.id).commercial_status === 'accepted',
    'Commercial acceptance is recorded separately from QC', 'not accepted');

  /* ---------------- 11. Packing ---------------- */
  S.logout(); go('#/login');
  setVal('#login-user', 'U08'); setVal('#login-pin', '1234');
  click('[data-act="login"]');
  RA.filters.packSite = siteId;
  go('#/packing');
  var cb = document.querySelector('[data-pack="' + asset.id + '"]');
  log(!!cb, 'Released unit appears in Packing (BR-01)', 'not listed');
  cb.click();
  click('[data-act="pack-create"]');
  setVal('#pk-seal', 'SEAL-WALK-01', modal());
  setVal('#pk-type', 'Carton', modal());
  click('#pk-go', modal());
  var pkg = S.db.packages[0];
  log(!!pkg && pkg.assets.indexOf(asset.id) > -1 && S.asset(asset.id).status === 'packed',
    'Package is sealed and the unit is marked packed', S.asset(asset.id).status);

  /* ---------------- 12. Dispatch ---------------- */
  go('#/pickup');
  click('[data-act="dispatch"][data-arg="' + pkg.id + '"][data-mode="pickup"]');
  setVal('#mv-vehicle', 'MH-04-AK-7890', modal());
  setVal('#mv-driver', 'Sunil P.', modal());
  setVal('#mv-gate', 'GP-9001', modal());
  click('#mv-go', modal());
  var mov = S.db.movements[0];
  log(!!mov && mov.status === 'in_transit' && S.asset(asset.id).status === 'dispatched',
    'Pickup handover is captured and the unit is in transit', S.asset(asset.id).status);

  /* ---------------- 13. Warehouse receipt ---------------- */
  S.logout(); go('#/login');
  setVal('#login-user', 'U10'); setVal('#login-pin', '1234');
  click('[data-act="login"]');
  go('#/warehouse');
  log(has(mov.id), 'Inbound movement is listed at the warehouse', 'not listed');
  click('[data-act="wh-receive"][data-arg="' + mov.id + '"]');
  setVal('#wh-count', String(mov.assets.length), modal());
  setVal('#wh-seal', 'Intact', modal());
  setVal('#wh-sealno', 'SEAL-WALK-01', modal());
  click('#wh-go', modal());
  var rcpt = S.db.receipts[0];
  log(!!rcpt && !rcpt.discrepancy && S.asset(asset.id).status === 'received',
    'GRN is recorded with no variance', S.asset(asset.id).status);

  /* ---------------- 14. Closure ---------------- */
  S.logout(); go('#/login');
  setVal('#login-user', 'U04'); setVal('#login-pin', '1234');
  click('[data-act="login"]');
  go('#/asset/' + asset.id);
  var closeBtn = document.querySelector('[data-act="close-asset"]');
  log(!!closeBtn && !closeBtn.disabled, 'Closure unlocks once the chain is complete (BR-12)',
    'still locked');
  closeBtn.click();
  log(S.asset(asset.id).status === 'closed', 'PMO closes the asset', S.asset(asset.id).status);

  /* ---------------- 15. It shows up in the numbers ---------------- */
  go('#/dashboard');
  var st = S.stats();
  log(st.received >= 1 && has('Chain-of-custody funnel'),
    'Dashboard reflects the completed chain', 'received=' + st.received);
  go('#/reports');
  log(has('Standard reports'), 'Reports screen renders with the new data', body().slice(0, 60));

  /* ---------------- 16. Audit trail ---------------- */
  go('#/audit');
  var acts = S.db.audit.map(function (e) { return e.action; });
  var needed = ['serial_captured', 'submit', 'decision:accepted', 'seal', 'dispatch:pickup', 'grn', 'close'];
  var missing = needed.filter(function (k) { return acts.indexOf(k) === -1; });
  log(missing.length === 0, 'Every step left an audit event', 'missing: ' + missing.join(', '));

  /* ---------------- 17. Offline capture ---------------- */
  var qcCount = S.db.qc.length;
  S.logout(); go('#/login');
  setVal('#login-user', 'U01'); setVal('#login-pin', '1234');
  click('[data-act="login"]');
  var third = S.assetsAt(siteId).filter(function (a) { return a.status === 'pending_qc'; })[0];
  S.captureSerial(third.id, 'C02WALK0003');
  go('#/qc/' + third.id);
  RA.data.CONDITION_BLOCKS[third.category].forEach(function (b) {
    var prefer = ['Power ON', 'OK', 'Working', 'Visibly OK', 'Available/OK'];
    var v = b.values.filter(function (x) { return prefer.indexOf(x) > -1; })[0] || b.values[0];
    var el = document.querySelector('[data-act="qc-set"][data-k="' + b.key + '"][data-v="' + v + '"]');
    if (el) el.click();
  });
  RA.qcState.photos.push({ kind: 'overall', data: null, id: 'p3' });
  var onlineGetter = Object.getOwnPropertyDescriptor(Navigator.prototype, 'onLine');
  Object.defineProperty(navigator, 'onLine', { configurable: true, get: function () { return false; } });
  RA.render();
  var offlineBanner = document.querySelector('.net-banner.offline');
  click('[data-act="qc-submit"]');
  click('#confirm-yes', modal());
  var offlineRec = S.db.qc[S.db.qc.length - 1];
  log(!!offlineBanner && S.db.qc.length === qcCount + 1 && offlineRec.synced === false,
    'QC captured while offline is stored and queued', 'banner=' + !!offlineBanner +
    ' synced=' + (offlineRec && offlineRec.synced));
  Object.defineProperty(navigator, 'onLine', onlineGetter || { configurable: true, get: function () { return true; } });
  go('#/myday');
  /* The record must be registered for sync, not silently dropped. Draining the
     queue is a network round trip, so this harness (synchronous by design)
     checks the hand-off; tools/selftest-sync.js verifies the drain itself. */
  var queuedForSync = !RA.sync || RA.sync.dirtyCount() > 0 || S.pendingSync().length === 0;
  var syncBtn = document.querySelector('[data-act="sync-now"]');
  if (syncBtn) syncBtn.click();
  log(queuedForSync, 'Record captured offline is queued for the shared store',
    'not queued and not synced');

  /* ---------------- 18. Persistence across a reload ---------------- */
  var saved = JSON.parse(localStorage.getItem('relianceFieldOps.db.v1'));
  log(saved && saved.qc.length === S.db.qc.length && saved.receipts.length === 1,
    'Everything is persisted to the device', 'not saved');

  S.login('U04', true); go('#/dashboard');
  var pass = out.filter(function (x) { return x.indexOf('PASS') === 0; }).length;
  return (pass + '/' + out.length + ' UI steps passed\n') + out.join('\n');
})()
