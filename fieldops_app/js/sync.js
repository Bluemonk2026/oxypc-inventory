/* ============================================================
   Reliance Asset FieldOps — shared-store sync

   The app stays local-first: everything is written to the device first and
   works with no network. This layer makes devices agree with each other —
   a QC submitted on an engineer's phone lands in the approver's queue, a
   handover lands at the warehouse — by pushing what changed here and pulling
   what changed elsewhere, in one round trip.

   The 3,957-unit inventory master never travels: every device seeds it
   identically from inventory.js, so only field activity syncs.

   With no server reachable (opened from a file, or hosted without the API)
   the app simply keeps working offline; sync reports itself unavailable and
   nothing is lost.
   ============================================================ */
(function (RA) {
  'use strict';

  var S = RA.store, D = RA.data;
  var Y = {};
  RA.sync = Y;

  var ENDPOINT = 'api/sync';         // relative → /fieldops/api/sync
  var STATUS_ENDPOINT = 'api/status';
  var PUSH_BATCH = 500;              // must not exceed the server's limit
  var AUTO_MS = 20000;               // background pull cadence
  var DEBOUNCE_MS = 1500;            // settle time after a burst of edits

  Y.state = {
    available: null,   // null = untested, true/false once known
    running: false,
    last_ok: null,
    last_error: null,
    pushed: 0,
    pulled: 0,
    server_user: null
  };

  /* ---------- which collection each record kind lives in ---------- */
  var COLLECTIONS = {
    qc:         { list: 'qc',          key: 'id' },
    commercial: { list: 'commercial',  key: 'id' },
    package:    { list: 'packages',    key: 'id' },
    movement:   { list: 'movements',   key: 'id' },
    receipt:    { list: 'receipts',    key: 'id' },
    asset:      { list: 'assets',      key: 'id' },
    site:       { list: 'sites',       key: 'id' },
    user:       { list: 'users',       key: 'id' },
    deduction:  { list: 'deductions',  key: 'version' },
    rate_card:  { list: 'rate_cards',  key: 'version' },
    audit:      { list: 'audit',       key: 'id' }
  };

  function bucket() {
    if (!S.db.sync) {
      S.db.sync = { cursor: null, dirty: {}, tombstones: {}, last_sync: null, enabled: true };
    }
    if (!S.db.sync.dirty) S.db.sync.dirty = {};
    if (!S.db.sync.tombstones) S.db.sync.tombstones = {};
    return S.db.sync;
  }

  /* ---------- marking records for the next push ---------- */
  Y.markDirty = function (kind, id) {
    if (!COLLECTIONS[kind] || id === undefined || id === null) return;
    bucket().dirty[kind + ':' + id] = new Date().toISOString();
  };
  Y.dirtyCount = function () {
    return Object.keys(bucket().dirty).length + Object.keys(bucket().tombstones || {}).length;
  };

  /* A deletion still has to travel, so it is queued as a tombstone rather than
     simply vanishing from the dirty set. */
  Y.markDeleted = function (kind, id) {
    if (!COLLECTIONS[kind] || id === undefined || id === null) return;
    var b = bucket();
    if (!b.tombstones) b.tombstones = {};
    delete b.dirty[kind + ':' + id];
    b.tombstones[kind + ':' + id] = new Date().toISOString();
  };

  function findRecord(kind, id) {
    var c = COLLECTIONS[kind];
    if (!c) return null;
    var list = S.db[c.list] || [];
    for (var i = 0; i < list.length; i++) {
      if (String(list[i][c.key]) === String(id)) return list[i];
    }
    return null;
  }

  /* ---------- applying what other devices changed ---------- */
  function applyRecord(rec) {
    var c = COLLECTIONS[rec.kind];
    if (!c) return false;
    var list = S.db[c.list] || (S.db[c.list] = []);
    var idx = -1;
    for (var i = 0; i < list.length; i++) {
      if (String(list[i][c.key]) === String(rec.id)) { idx = i; break; }
    }

    if (rec.deleted) {
      if (idx > -1) { list.splice(idx, 1); return true; }
      return false;
    }

    /* A record this device edited more recently wins — the server already
       arbitrates, but a push in flight can cross a pull. */
    var localDirty = bucket().dirty[rec.kind + ':' + rec.id];
    if (localDirty && rec.updated_at && localDirty > rec.updated_at) return false;

    if (idx > -1) list[idx] = rec.data;
    else list.push(rec.data);

    if (rec.kind === 'asset') D.hydrate(rec.data);
    return true;
  }

  /* ---------- the round trip ---------- */
  Y.run = function (opts) {
    opts = opts || {};
    var b = bucket();

    /* A round trip is already in flight. Don't drop this request — the caller
       has just written something and expects it to travel — run again as soon
       as the current one lands. One follow-up is enough; further overlapping
       callers ride on that same result. */
    if (Y.state.running && Y._current) {
      if (opts._chained) return Y._current;
      return Y._current.then(function () {
        return Y.run(Object.assign({}, opts, { _chained: true }));
      });
    }
    if (b.enabled === false) return Promise.resolve({ skipped: 'disabled' });
    if (navigator.onLine === false) {
      return Promise.resolve({ skipped: 'offline', pending: Y.dirtyCount() });
    }

    Y.state.running = true;

    /* Build this round's push, oldest edits first, capped to one batch. */
    var keys = Object.keys(b.dirty).sort(function (x, y) {
      return b.dirty[x] < b.dirty[y] ? -1 : 1;
    }).slice(0, PUSH_BATCH);

    var changes = [], sent = {}, sentTombs = {};
    keys.forEach(function (k) {
      var split = k.indexOf(':');
      var kind = k.slice(0, split), id = k.slice(split + 1);
      var data = findRecord(kind, id);
      if (!data) { delete b.dirty[k]; return; }   // deleted locally before syncing
      sent[k] = b.dirty[k];
      changes.push({
        kind: kind, id: id,
        data: JSON.parse(JSON.stringify(data)),
        updated_at: b.dirty[k]
      });
    });
    Object.keys(b.tombstones).slice(0, PUSH_BATCH - changes.length).forEach(function (k) {
      var split = k.indexOf(':');
      sentTombs[k] = b.tombstones[k];
      changes.push({
        kind: k.slice(0, split), id: k.slice(split + 1),
        data: {}, deleted: true, updated_at: b.tombstones[k]
      });
    });

    Y._current = fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ since: opts.full ? null : b.cursor, changes: changes })
    }).then(function (res) {
      if (res.status === 401 || res.status === 403 ||
          (res.redirected && /login/i.test(res.url))) {
        throw new Error('Session expired — sign in to OxyPC again to sync.');
      }
      if (!res.ok) throw new Error('Sync failed (' + res.status + ')');
      var ct = res.headers.get('content-type') || '';
      if (ct.indexOf('application/json') === -1) throw new Error('Sync endpoint unavailable');
      return res.json();
    }).then(function (out) {
      /* Clear only what we actually sent and that has not been re-edited since. */
      Object.keys(sent).forEach(function (k) {
        if (b.dirty[k] === sent[k]) delete b.dirty[k];
      });
      Object.keys(sentTombs).forEach(function (k) {
        if (b.tombstones[k] === sentTombs[k]) delete b.tombstones[k];
      });

      var applied = 0;
      (out.records || []).forEach(function (r) { if (applyRecord(r)) applied++; });

      b.cursor = out.cursor || out.server_time;
      b.last_sync = new Date().toISOString();

      /* Records that reached the server are no longer "pending sync". */
      S.db.qc.forEach(function (q) {
        if (!q.synced && !b.dirty['qc:' + q.id]) q.synced = true;
      });

      Y.state.available = true;
      Y.state.last_ok = b.last_sync;
      Y.state.last_error = null;
      Y.state.pushed += (out.accepted || 0);
      Y.state.pulled += applied;
      /* Shared device: if the signed-in account changed underneath us, the
         screen is showing someone else's scope. Reload rather than mislead. */
      if (out.user && Y.state.server_user && out.user.emp !== Y.state.server_user.emp) {
        location.reload();
        return { pushed: out.accepted || 0, pulled: applied, reloading: true };
      }
      Y.state.server_user = out.user || null;
      Y.state.running = false;
      Y._current = null;

      S.persist();

      var more = Y.dirtyCount() > 0 || out.truncated;
      if (more && !opts.noChain) return Y.run({ noChain: true });

      if (applied && RA.render && !opts.quiet) RA.render();
      return { pushed: out.accepted || 0, pulled: applied, pending: Y.dirtyCount() };
    }).catch(function (err) {
      Y.state.running = false;
      Y._current = null;
      Y.state.last_error = err.message;
      if (/unavailable|Failed to fetch|NetworkError/i.test(err.message)) {
        Y.state.available = false;      // hosted without the API, or truly offline
      }
      return { error: err.message, pending: Y.dirtyCount() };
    });

    return Y._current;
  };

  /* Nudge after a burst of edits rather than on every keystroke. */
  Y.schedule = function () {
    clearTimeout(Y._t);
    Y._t = setTimeout(function () { Y.run({ quiet: true }); }, DEBOUNCE_MS);
  };

  Y.status = function () {
    return fetch(STATUS_ENDPOINT, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  };

  /* ---------- wiring ----------
     Every mutation in the store ends with persist(), so that is the single
     place to notice "something changed, send it soon". */
  var _persist = S.persist;
  S.persist = function () {
    var r = _persist.apply(S, arguments);
    if (!Y.state.running && Y.dirtyCount()) Y.schedule();
    return r;
  };

  Y.start = function () {
    bucket();
    /* First contact: pull everything the shared store already holds. */
    Y.run({ full: !S.db.sync.cursor, quiet: true });

    clearInterval(Y._i);
    Y._i = setInterval(function () {
      if (navigator.onLine !== false) Y.run({ quiet: true });
    }, AUTO_MS);

    window.addEventListener('online', function () { Y.run(); });
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) Y.run({ quiet: true });
    });
  };

  /* Replaces the local-only stub: a real sync, with the same call site. */
  S.syncNow = function () {
    return Y.run().then(function (r) {
      if (r && r.error) {
        RA.ui.toast(r.error, 'error');
      } else if (r && (r.pushed || r.pulled)) {
        RA.ui.toast('Synced — ' + r.pushed + ' sent, ' + r.pulled + ' received', 'success');
      } else if (r && r.skipped === 'offline') {
        RA.ui.toast('Offline — ' + (r.pending || 0) + ' record(s) queued', 'warn');
      } else {
        RA.ui.toast('Up to date', 'success');
      }
      if (RA.render) RA.render();
      return r;
    });
  };

})(window.RA = window.RA || {});
