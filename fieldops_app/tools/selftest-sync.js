/* Self-test — shared-store sync. Needs the app served by the FastAPI route
   (app.oxypc.com/fieldops or a local run of routers/fieldops.py); standalone
   from a plain file server it reports the API as unavailable and stops.

     fetch('tools/selftest-sync.js').then(r=>r.text()).then(t=>eval(t)).then(console.log)

   Resets local data and writes test records to the shared store. Sign in again
   afterwards. */
(function () {
  var S = RA.store, Y = RA.sync, out = [];
  function t(ok, name, detail) {
    out.push((ok === true ? 'PASS' : 'FAIL') + ' · ' + name + (ok === true ? '' : ' → ' + detail));
  }
  function done() {
    var pass = out.filter(function (x) { return x.indexOf('PASS') === 0; }).length;
    return (pass + '/' + out.length + ' sync checks passed\n') + out.join('\n');
  }
  function api(body) {
    return fetch('api/sync', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin', body: JSON.stringify(body)
    }).then(function (r) { return r.json(); });
  }

  if (!Y) return Promise.resolve('sync module not loaded');

  S.reset();
  if (!S.db.sync) S.db.sync = {};
  S.db.sync.enabled = true;
  S.db.sync.cursor = null;

  return Y.run({ full: true, quiet: true }).then(function (first) {
    if (first && first.error) {
      return 'Shared store unreachable (' + first.error + ') — run this from the /fieldops route.';
    }
    t(Y.state.available === true, 'shared store reachable', Y.state.last_error);

    /* ---------- a QC submitted here reaches the server ---------- */
    S.login('U01', false);
    var site = S.mySites()[0];
    var asset = S.assetsAt(site.id).filter(function (a) { return a.category === 'laptop'; })[0];
    S.captureSerial(asset.id, 'SYNCCHK' + Date.now().toString().slice(-6));
    var qc = S.submitQC({
      asset_id: asset.id, specs: { serial: asset.serial },
      responses: { power: 'Power ON', display: 'OK', body: 'Scratch', keyboard: 'Working',
                   touchpad: 'Working', hinge: 'OK', ports: 'Visibly OK', charger: 'Missing' },
      photos: [{ kind: 'overall' }, { kind: 'defect' }], remarks: 'sync self-test', seconds: 750
    });
    t(Y.dirtyCount() > 0, 'submitting queues the record for the shared store', Y.dirtyCount());

    return Y.run().then(function (res) {
      t(res.pushed > 0 && Y.dirtyCount() === 0,
        'sync pushes the queue and empties it', JSON.stringify(res));
      t(S.qcRecord(qc.id).synced === true,
        'the record stops counting as pending sync', S.qcRecord(qc.id).synced);

      /* ---------- another device sees it ---------- */
      return api({ since: null, changes: [] }).then(function (server) {
        var seen = {};
        server.records.forEach(function (r) { seen[r.kind + ':' + r.id] = r.data; });
        t(!!seen['qc:' + qc.id], 'another device pulling fresh receives the QC', 'not on the server');
        t(seen['asset:' + asset.id] && seen['asset:' + asset.id].status === 'qc_submitted',
          'the asset status travels with it',
          seen['asset:' + asset.id] && seen['asset:' + asset.id].status);
        t(!!seen['commercial:CM-' + qc.id.slice(3)],
          'the commercial record travels with it', 'missing');

        /* ---------- a decision made elsewhere lands here ---------- */
        var approved = JSON.parse(JSON.stringify(S.qcRecord(qc.id)));
        approved.status = 'accepted';
        approved.approver = 'Remote Approver';
        approved.approved_at = new Date().toISOString();
        var assetCopy = JSON.parse(JSON.stringify(S.asset(asset.id)));
        assetCopy.status = 'accepted';
        return api({
          since: null,
          changes: [
            { kind: 'qc', id: qc.id, data: approved, updated_at: new Date().toISOString() },
            { kind: 'asset', id: asset.id, data: assetCopy, updated_at: new Date().toISOString() }
          ]
        });
      }).then(function () {
        return Y.run({ quiet: true });
      }).then(function (res2) {
        t(S.qcRecord(qc.id).status === 'accepted',
          'an approval made on another device appears here automatically',
          S.qcRecord(qc.id).status);
        t(S.qcRecord(qc.id).approver === 'Remote Approver',
          'the approver identity comes across', S.qcRecord(qc.id).approver);
        t(S.asset(asset.id).status === 'accepted',
          'the unit is released for packing here too', S.asset(asset.id).status);
        t(res2.pulled > 0, 'the pull is reported', JSON.stringify(res2));

        /* ---------- a stale local edit cannot undo it ---------- */
        var stale = JSON.parse(JSON.stringify(S.qcRecord(qc.id)));
        stale.status = 'pending';
        return api({
          since: null,
          changes: [{ kind: 'qc', id: qc.id, data: stale,
                      updated_at: new Date(Date.now() - 3600000).toISOString() }]
        });
      }).then(function (r) {
        t(r.rejected === 1 && r.accepted === 0,
          'an hour-old edit is refused rather than overwriting the decision', JSON.stringify(r));

        /* ---------- offline capture holds, then drains ---------- */
        var onlineDesc = Object.getOwnPropertyDescriptor(Navigator.prototype, 'onLine');
        Object.defineProperty(navigator, 'onLine', { configurable: true, get: function () { return false; } });
        var next = S.assetsAt(site.id).filter(function (a) { return a.status === 'pending_qc'; })[0];
        S.captureSerial(next.id, 'OFFLINE' + Date.now().toString().slice(-6));
        var queued = Y.dirtyCount();
        return Y.run().then(function (off) {
          t(off.skipped === 'offline' && queued > 0,
            'offline capture is held on the device, not lost', JSON.stringify(off));
          Object.defineProperty(navigator, 'onLine',
            onlineDesc || { configurable: true, get: function () { return true; } });
          return Y.run();
        }).then(function (back) {
          t(back.pushed > 0 && Y.dirtyCount() === 0,
            'the held changes drain when the connection returns', JSON.stringify(back));
          return fetch('api/status', { credentials: 'same-origin' }).then(function (r) { return r.json(); });
        });
      }).then(function (status) {
        t(status.records > 0 && !!status.by_kind.qc,
          'the shared store reports what it holds', JSON.stringify(status));
        S.db.sync.enabled = false;   // leave the device quiet after the test
        S.persist();
        return done();
      });
    });
  }).catch(function (e) {
    t(false, 'sync suite completed', e.message);
    return done();
  });
})()
