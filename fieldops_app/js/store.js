/* ============================================================
   Reliance Asset FieldOps — Persistence, Audit & Business Rules
   Local-first store (localStorage). Swap `RA.store.persist`
   for an API call to move to a server backend.
   ============================================================ */
(function (RA) {
  'use strict';

  var KEY = 'relianceFieldOps.db.v1';
  var SESSION_KEY = 'relianceFieldOps.session.v1';
  var D = RA.data;

  var S = {};
  RA.store = S;

  /* ---------------- Core state ---------------- */
  S.db = null;

  function stamp() {
    if (!RA.inventory) return 'none';
    return RA.inventory.units + '@' + RA.inventory.sites.length +
           '#' + (RA.inventory.build || '0');
  }

  function blank() {
    var seeded = D.seed();
    return {
      meta: { schema: 1, created_at: new Date().toISOString(), demo: true, inventory: stamp() },
      project: JSON.parse(JSON.stringify(D.PROJECT)),
      config: JSON.parse(JSON.stringify(D.CONFIG)),
      users: JSON.parse(JSON.stringify(D.USERS)),
      sites: seeded.sites,
      assets: seeded.assets,
      qc: [],
      deductions: [JSON.parse(JSON.stringify(D.DEDUCTION_V1))],
      rate_cards: [JSON.parse(JSON.stringify(D.RATE_CARD))],
      commercial: [],
      packages: [],
      movements: [],   // pickups + courier AWBs
      receipts: [],    // warehouse GRN
      audit: [],
      notifications_read: [],
      counters: { qc: 0, pkg: 0, mov: 0, rcpt: 0, grn: 0 }
    };
  }

  S.load = function () {
    try {
      var raw = localStorage.getItem(KEY);
      if (raw) { S.db = JSON.parse(raw); }
    } catch (e) { S.db = null; }
    if (!S.db || !S.db.assets) { S.db = blank(); S.persist(); }
    if (!S.db.counters) S.db.counters = { qc: 0, pkg: 0, mov: 0, rcpt: 0, grn: 0 };
    D.hydrateAll(S.db.assets);

    /* Inventory master changed since this device was seeded. Re-seed when no
       field work would be lost; otherwise flag it for the PMO to reconcile. */
    if (S.db.meta && S.db.meta.inventory !== stamp()) {
      var untouched = !S.db.qc.length && !S.db.packages.length &&
                      !S.db.movements.length && !S.db.receipts.length;
      if (untouched) {
        var cfg = S.db.config;   /* keep tuned thresholds; users re-seed with new site IDs */
        S.db = blank();
        S.db.config = cfg;
        S.audit('master', 'inventory', 'reseed', { inventory: stamp() });
        S.persist();
      } else {
        S.db.meta.inventory_mismatch = stamp();
      }
    }
    return S.db;
  };

  S.persist = function () {
    try {
      localStorage.setItem(KEY, JSON.stringify(S.db));
      S.lastError = null;
      return true;
    } catch (e) {
      /* Quota exceeded — most likely photo payloads. Shed photo data, keep records. */
      S.lastError = e;
      var shed = 0;
      S.db.qc.forEach(function (q) {
        (q.photos || []).forEach(function (p) {
          if (p.data) { p.data = null; p.shed = true; shed++; }
        });
      });
      try {
        localStorage.setItem(KEY, JSON.stringify(S.db));
        RA.ui && RA.ui.toast('Storage full — ' + shed + ' photo(s) dropped from local cache. Records kept.', 'warn');
        return true;
      } catch (e2) {
        RA.ui && RA.ui.toast('Local storage full. Export data and reset from Admin.', 'error');
        return false;
      }
    }
  };

  S.reset = function () { S.db = blank(); S.persist(); };

  S.exportJSON = function () { return JSON.stringify(S.db, null, 2); };
  S.importJSON = function (text) {
    var obj = JSON.parse(text);
    if (!obj.assets || !obj.sites) throw new Error('Not a FieldOps backup file');
    S.db = obj; D.hydrateAll(S.db.assets); S.persist();
  };

  /* ---------------- Session ---------------- */
  S.session = function () {
    try { return JSON.parse(sessionStorage.getItem(SESSION_KEY) || localStorage.getItem(SESSION_KEY) || 'null'); }
    catch (e) { return null; }
  };
  S.login = function (userId, remember) {
    var u = S.user(userId);
    if (!u) return null;
    var sess = { user_id: u.id, role: u.role, at: new Date().toISOString() };
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(sess));
    if (remember) localStorage.setItem(SESSION_KEY, JSON.stringify(sess));
    else localStorage.removeItem(SESSION_KEY);
    S.audit('session', u.id, 'login', { role: u.role });
    return sess;
  };
  S.logout = function () {
    var s = S.session();
    if (s) S.audit('session', s.user_id, 'logout', {});
    sessionStorage.removeItem(SESSION_KEY);
    localStorage.removeItem(SESSION_KEY);
  };
  S.me = function () { var s = S.session(); return s ? S.user(s.user_id) : null; };
  S.user = function (id) { return S.db.users.filter(function (u) { return u.id === id; })[0] || null; };
  /* Role default, then per-user grants and revocations set by the admin */
  S.canUser = function (u, screen) {
    if (!u) return false;
    if (u.status === 'inactive') return false;
    var list = D.ACCESS[screen];
    if (!list) return false;
    var perms = u.perms || {};
    if ((perms.deny || []).indexOf(screen) > -1) return false;
    if ((perms.allow || []).indexOf(screen) > -1) return true;
    return list.indexOf('*') > -1 || list.indexOf(u.role) > -1;
  };
  S.can = function (screen) { return S.canUser(S.me(), screen); };
  S.roleAllows = function (role, screen) {
    var list = D.ACCESS[screen] || [];
    return list.indexOf('*') > -1 || list.indexOf(role) > -1;
  };

  /* ---------------- User administration (FR-002) ---------------- */
  S.saveUser = function (data) {
    var existing = data.id ? S.user(data.id) : null;
    var before = existing ? JSON.parse(JSON.stringify(existing)) : null;

    var clash = S.db.users.filter(function (u) {
      return u.emp.toLowerCase() === data.emp.toLowerCase() && u.id !== data.id;
    });
    if (clash.length) throw new Error('Employee ID "' + data.emp + '" is already in use.');
    if (!data.name || !data.emp) throw new Error('Name and employee ID are required.');
    if (!D.ROLES[data.role]) throw new Error('Unknown role.');

    var u = existing;
    if (!u) {
      var n = 1;
      while (S.user('U' + (n < 10 ? '0' + n : n))) n++;
      u = { id: 'U' + (n < 10 ? '0' + n : n) };
      S.db.users.push(u);
    }
    u.name = data.name;
    u.emp = data.emp;
    u.role = data.role;
    u.region = data.region;
    u.sites = (data.sites || []).slice();
    u.status = data.status || 'active';
    u.perms = { allow: (data.allow || []).slice(), deny: (data.deny || []).slice() };

    S.audit('user', u.id, existing ? 'update' : 'create', {
      name: u.name, emp: u.emp, role: u.role, region: u.region,
      sites: u.sites.length, status: u.status,
      allow: u.perms.allow.join('|'), deny: u.perms.deny.join('|'),
      was: before ? (before.role + '/' + (before.sites || []).length + ' sites') : ''
    });
    dirty('user', u.id);
    S.persist();
    return u;
  };

  S.deleteUser = function (id) {
    var u = S.user(id);
    if (!u) throw new Error('User not found');
    var me = S.me();
    if (me && me.id === id) throw new Error('You cannot delete the account you are signed in with.');
    if (u.role === 'admin' && S.db.users.filter(function (x) {
      return x.role === 'admin' && x.status !== 'inactive';
    }).length <= 1) throw new Error('At least one active System Admin must remain.');
    var work = S.db.qc.filter(function (q) { return q.engineer_id === id; }).length;
    if (work) throw new Error('This user has ' + work + ' QC record(s). Set the account to inactive instead of deleting it.');
    S.db.users = S.db.users.filter(function (x) { return x.id !== id; });
    S.audit('user', id, 'delete', { name: u.name, emp: u.emp });
    gone('user', id);
    S.persist();
  };

  /* ---------------- Serial ↔ site mapping (FR-005 / BR-06) ---------------- */
  S.PENDING_SERIAL = /^PEND-/i;
  S.hasSerial = function (a) { return !!a && !S.PENDING_SERIAL.test(a.serial || ''); };
  S.normSerial = function (s) { return String(s || '').trim().toUpperCase(); };

  S.findBySerial = function (serial) {
    var q = S.normSerial(serial);
    if (!q) return null;
    return S.db.assets.filter(function (a) { return S.normSerial(a.serial) === q; })[0] || null;
  };

  /* Assets at a site still awaiting a serial, grouped by article/model */
  S.pendingSerialGroups = function (siteId) {
    var groups = {};
    S.assetsAt(siteId).forEach(function (a) {
      if (S.hasSerial(a)) return;
      var key = a.article || a.model;
      if (!groups[key]) {
        groups[key] = {
          key: key, article: a.article, model: a.model, category: a.category,
          desc: a.article_desc, price: a.base_price, assets: []
        };
      }
      groups[key].assets.push(a);
    });
    return Object.keys(groups).map(function (k) { return groups[k]; })
      .sort(function (x, y) { return y.assets.length - x.assets.length; });
  };

  /* Bind a scanned/typed serial to a specific asset record (BR-06 enforced) */
  S.captureSerial = function (assetId, serial) {
    var a = S.asset(assetId);
    if (!a) throw new Error('Asset not found');
    var s = S.normSerial(serial);
    if (!s) throw new Error('Serial number is required.');
    if (S.PENDING_SERIAL.test(s)) throw new Error('Enter the serial printed on the device.');
    if (s.length < 4) throw new Error('Serial looks too short — please re-check.');
    var clash = S.findBySerial(s);
    if (clash && clash.id !== a.id) {
      var site = S.site(clash.site_id);
      throw new Error('BR-06: serial ' + s + ' is already mapped to ' + clash.tag +
        ' at ' + (site ? site.site : clash.site_id) + '. Supervisor review required.');
    }
    var from = a.serial;
    a.serial = s;
    a.serial_captured_at = new Date().toISOString();
    a.serial_captured_by = (S.me() || {}).name || 'unknown';
    S.audit('asset', a.id, 'serial_captured', { from: from, to: s, site: a.site_id, tag: a.tag });
    dirty('asset', a.id);
    S.persist();
    return a;
  };

  /* Pick the next unserialised asset of a given article at a site and bind to it */
  S.mapSerialToArticle = function (siteId, articleKey, serial) {
    var group = S.pendingSerialGroups(siteId).filter(function (g) { return g.key === articleKey; })[0];
    if (!group || !group.assets.length) throw new Error('No unmapped unit of that model is left at this site.');
    return S.captureSerial(group.assets[0].id, serial);
  };

  S.serialStats = function (siteId) {
    var pool = siteId ? S.assetsAt(siteId) : S.db.assets;
    var captured = 0;
    pool.forEach(function (a) { if (S.hasSerial(a)) captured++; });
    return { total: pool.length, captured: captured, pending: pool.length - captured };
  };

  /* Bulk serial import — CSV with Site (name/code/id) + Serial [+ Article] */
  S.importSerials = function (text) {
    var rows = S.parseCSV(text);
    if (rows.length < 2) throw new Error('CSV appears empty.');
    var head = rows[0].map(function (h) {
      return h.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
    });
    var idx = function (names) {
      for (var i = 0; i < names.length; i++) { var p = head.indexOf(names[i]); if (p > -1) return p; }
      return -1;
    };
    var cSite = idx(['site', 'site_description', 'site_name', 'site_code', 'location']);
    var cSerial = idx(['serial', 'serial_no', 'serial_number', 'sr_no']);
    var cArticle = idx(['article', 'article_code', 'sku']);
    var cTag = idx(['asset_tag', 'tag']);
    if (cSerial < 0) throw new Error('Required column "Serial" not found.');

    var mapped = 0, errors = [], seen = {};
    for (var r = 1; r < rows.length; r++) {
      var row = rows[r];
      var get = function (c) { return c > -1 && row[c] !== undefined ? String(row[c]).trim() : ''; };
      var serial = S.normSerial(get(cSerial));
      var line = 'Row ' + (r + 1) + ': ';
      if (!serial) { errors.push(line + 'blank serial'); continue; }
      if (seen[serial]) { errors.push(line + serial + ' repeated in this file'); continue; }
      seen[serial] = 1;

      var existing = S.findBySerial(serial);
      if (existing) { errors.push(line + serial + ' already mapped to ' + existing.tag); continue; }

      var target = null;
      var tag = get(cTag);
      if (tag) {
        target = S.db.assets.filter(function (a) { return a.tag === tag; })[0] || null;
        if (target && S.hasSerial(target)) { errors.push(line + 'tag ' + tag + ' already has a serial'); continue; }
      }
      if (!target) {
        var siteKey = get(cSite);
        if (!siteKey) { errors.push(line + 'no Site or Asset Tag to map against'); continue; }
        var site = S.db.sites.filter(function (s) {
          return s.site.toLowerCase() === siteKey.toLowerCase() ||
                 s.id.toLowerCase() === siteKey.toLowerCase() ||
                 (s.code && String(s.code).toLowerCase() === siteKey.toLowerCase()) ||
                 (s.codes || []).some(function (c) { return String(c).toLowerCase() === siteKey.toLowerCase(); });
        })[0];
        if (!site) { errors.push(line + 'site "' + siteKey + '" not found'); continue; }
        var pool = S.assetsAt(site.id).filter(function (a) { return !S.hasSerial(a); });
        var art = get(cArticle);
        if (art) {
          var byArt = pool.filter(function (a) { return String(a.article) === art; });
          if (!byArt.length) { errors.push(line + 'no unmapped unit of article ' + art + ' at ' + site.site); continue; }
          target = byArt[0];
        } else {
          if (!pool.length) { errors.push(line + 'no unmapped units left at ' + site.site); continue; }
          target = pool[0];
        }
      }
      target.serial = serial;
      target.serial_captured_at = new Date().toISOString();
      target.serial_captured_by = (S.me() || {}).name + ' (import)';
      dirty('asset', target.id);
      mapped++;
    }
    S.audit('master', 'serials', 'import', { mapped: mapped, errors: errors.length });
    S.persist();
    return { mapped: mapped, errors: errors };
  };

  /* ---------------- Audit (BRD FR-023, immutable) ---------------- */
  S.audit = function (entity, recordId, action, meta) {
    var me = null;
    try { me = S.me(); } catch (e) { }
    S.db.audit.push({
      id: 'EV' + S.deviceCode() + '-' + (S.db.audit.length + 1),
      entity: entity, record_id: recordId, action: action,
      user: me ? (me.name + ' (' + D.ROLES[me.role].label + ')') : 'system',
      user_id: me ? me.id : 'system',
      ts: new Date().toISOString(),
      meta: meta || {}
    });
    dirty('audit', S.db.audit[S.db.audit.length - 1].id);
  };

  /* ---------------- Lookups ---------------- */
  S.site = function (id) { return S.db.sites.filter(function (s) { return s.id === id; })[0] || null; };
  S.asset = function (id) { return S.db.assets.filter(function (a) { return a.id === id; })[0] || null; };
  S.qcRecord = function (id) { return S.db.qc.filter(function (q) { return q.id === id; })[0] || null; };
  S.qcForAsset = function (assetId) {
    return S.db.qc.filter(function (q) { return q.asset_id === assetId; })
      .sort(function (a, b) { return a.submitted_at < b.submitted_at ? 1 : -1; });
  };
  S.commercialFor = function (qcId) { return S.db.commercial.filter(function (c) { return c.qc_id === qcId; })[0] || null; };
  S.pkg = function (id) { return S.db.packages.filter(function (p) { return p.id === id; })[0] || null; };
  S.movement = function (id) { return S.db.movements.filter(function (m) { return m.id === id; })[0] || null; };

  S.assetsAt = function (siteId) { return S.db.assets.filter(function (a) { return a.site_id === siteId; }); };

  /* Sites visible to current user (RBAC scope) */
  S.mySites = function () {
    var me = S.me(); if (!me) return [];
    if (me.role === 'fe' || me.role === 'spoc') {
      return S.db.sites.filter(function (s) { return me.sites.indexOf(s.id) > -1; });
    }
    if (me.role === 'coord' || me.role === 'packer' || me.role === 'warehouse') {
      if (me.region && me.region !== 'All') return S.db.sites.filter(function (s) { return s.region === me.region; });
    }
    return S.db.sites.slice();
  };

  /* ---------------- ID helpers ----------------
     Records are minted on the device, offline, and later merged into one
     shared store — so every id carries a short device code. Without it two
     engineers working the same day would both create QC-000001 and overwrite
     each other on sync. */
  S.deviceCode = function () {
    if (!S.db.meta) S.db.meta = {};
    if (!S.db.meta.device) {
      var chars = 'ACDEFGHJKLMNPQRTUVWXY3456789', c = '';
      for (var i = 0; i < 3; i++) c += chars[Math.floor(Math.random() * chars.length)];
      S.db.meta.device = c;
    }
    return S.db.meta.device;
  };

  function nextId(kind, prefix, width) {
    S.db.counters[kind] = (S.db.counters[kind] || 0) + 1;
    var n = String(S.db.counters[kind]);
    while (n.length < width) n = '0' + n;
    return prefix + S.deviceCode() + '-' + n;
  }

  /* Queue a record for the next sync push (no-op when sync is not loaded). */
  function dirty(kind, id) { if (RA.sync) RA.sync.markDirty(kind, id); }
  function gone(kind, id) { if (RA.sync) RA.sync.markDeleted(kind, id); }

  /* ---------------- Asset search (BRD FR-005, fuzzy) ---------------- */
  S.searchAssets = function (q, siteId) {
    q = (q || '').trim().toUpperCase();
    var pool = siteId ? S.assetsAt(siteId) : S.db.assets;
    if (!q) return pool.slice(0, 40);
    var out = [];
    pool.forEach(function (a) {
      var hay = [a.serial, a.tag, a.model, a.make, a.id].join(' ').toUpperCase();
      var score = 0;
      if (a.serial.toUpperCase() === q || a.tag.toUpperCase() === q) score = 100;
      else if (hay.indexOf(q) > -1) score = 60 - Math.min(30, hay.indexOf(q));
      else if (fuzzy(hay, q)) score = 20;
      if (score) out.push({ a: a, score: score });
    });
    return out.sort(function (x, y) { return y.score - x.score; }).slice(0, 40).map(function (o) { return o.a; });
  };
  function fuzzy(hay, needle) {
    var i = 0;
    for (var j = 0; j < hay.length && i < needle.length; j++) if (hay[j] === needle[i]) i++;
    return i === needle.length;
  }

  /* BR-06 duplicate serial/tag detection */
  S.duplicateCheck = function (asset) {
    return S.db.assets.filter(function (a) {
      return a.id !== asset.id && (a.serial === asset.serial || a.tag === asset.tag);
    });
  };

  /* ---------------- QC: defect derivation (BRD Sec 6.2) ---------------- */
  S.deriveCodes = function (responses) {
    var codes = [];
    Object.keys(responses || {}).forEach(function (k) {
      var map = D.CODE_MAP[k];
      if (!map) return;
      var c = map[responses[k]];
      if (c && codes.indexOf(c) === -1) codes.push(c);
      if (k === 'body' && responses[k] === 'Multiple' && codes.indexOf('SC') === -1) codes.push('SC');
    });
    if (!codes.length) codes = ['OK'];
    codes.sort(function (a, b) { return D.codeMeta(b).rank - D.codeMeta(a).rank; });
    return codes;
  };
  S.primaryCode = function (codes) { return (codes && codes[0]) || 'OK'; };

  /* Conditional suppression — BR-03 (No Power path) */
  S.applySuppression = function (category, responses) {
    var blocks = D.CONDITION_BLOCKS[category] || [];
    var noPower = responses.power === 'No Power';
    blocks.forEach(function (b) {
      if (b.suppress) {
        if (noPower) responses[b.key] = D.NOT_TESTED;
        else if (responses[b.key] === D.NOT_TESTED) responses[b.key] = null;
      }
    });
    return responses;
  };

  /* Photo requirement — BR-04 / FR-008 */
  S.photoRules = function (codes, photos) {
    var cfg = S.db.config.photo;
    var overall = (photos || []).some(function (p) { return p.kind === 'overall'; });
    var defect = (photos || []).some(function (p) { return p.kind === 'defect'; });
    var needDefect = false;
    (codes || []).forEach(function (c) { if (D.codeMeta(c).photo) needDefect = true; });
    var errs = [];
    if (cfg.overall_required && !overall) errs.push('Overall photo is mandatory.');
    if (cfg.defect_required_for_exception && needDefect && !defect) errs.push('Defect photo required for the selected exception code(s).');
    return { ok: errs.length === 0, errors: errs, needDefect: needDefect };
  };

  /* ---------------- Pricing engine (BRD Sec 7) ---------------- */
  S.activeDeduction = function () {
    var act = S.db.deductions.filter(function (d) { return d.active; });
    return act[act.length - 1] || S.db.deductions[S.db.deductions.length - 1];
  };
  S.computePrice = function (basePrice, codes) {
    var master = S.activeDeduction();
    var rule = master.rule || S.db.config.multi_defect_rule;
    var pcts = (codes || []).map(function (c) { return +(master.rates[c] || 0); });
    var pct = 0;
    if (!pcts.length) pct = 0;
    else if (rule === 'additive') pct = pcts.reduce(function (a, b) { return a + b; }, 0);
    else if (rule === 'capped') pct = Math.min(pcts.reduce(function (a, b) { return a + b; }, 0), S.db.config.multi_defect_cap_pct);
    else pct = Math.max.apply(null, pcts);
    pct = Math.min(pct, 100);
    var amt = Math.round(basePrice * pct) / 100;
    return {
      version: master.version, rule: rule, pct: pct,
      deduction_amount: amt,
      revised_price: Math.round((basePrice - amt) * 100) / 100,
      master_status: master.approval_status
    };
  };

  /* ---------------- QC submission (BRD FR-010, BR-05 immutable) ---------------- */
  S.submitQC = function (payload) {
    var asset = S.asset(payload.asset_id);
    if (!asset) throw new Error('Asset not found');
    if (!S.hasSerial(asset)) throw new Error('Capture the device serial number before submitting QC.');
    var me = S.me();
    var codes = S.deriveCodes(payload.responses);
    var prior = S.qcForAsset(asset.id);
    var id = nextId('qc', 'QC-', 6);

    var rec = {
      id: id,
      asset_id: asset.id,
      site_id: asset.site_id,
      category: asset.category,
      specs: payload.specs || {},
      responses: payload.responses || {},
      codes: codes,
      primary_code: S.primaryCode(codes),
      photos: payload.photos || [],
      remarks: payload.remarks || '',
      seconds: payload.seconds || 0,
      engineer: me ? me.name : 'unknown',
      engineer_id: me ? me.id : null,
      submitted_at: new Date().toISOString(),
      status: 'pending',           // pending | accepted | disputed | re_qc
      approver: null, approved_at: null, reason: null,
      version: prior.length + 1,
      supersedes: prior.length ? prior[0].id : null,
      synced: navigator.onLine !== false,
      immutable: true
    };
    S.db.qc.push(rec);

    /* Commercial record (BRD Sec 7.3) */
    var price = S.computePrice(asset.base_price, codes);
    S.db.commercial.push({
      id: 'CM-' + id.slice(3),
      qc_id: id, asset_id: asset.id,
      base_price: asset.base_price,
      deduction_pct: price.pct,
      deduction_amount: price.deduction_amount,
      revised_price: price.revised_price,
      master_version: price.version,
      qc_status: 'pending',
      commercial_status: 'pending',
      updated_at: new Date().toISOString(),
      history: []
    });

    /* Serial captured at QC is written back to the asset master (source workbook
       carries no serial numbers) — recorded as an auditable master change. */
    var capturedSerial = (payload.specs && payload.specs.serial || '').trim();
    if (capturedSerial && capturedSerial !== asset.serial) {
      S.audit('asset', asset.id, 'serial_captured', { from: asset.serial, to: capturedSerial, qc: id });
      asset.serial = capturedSerial;
    }

    asset.qc_id = id;
    asset.status = 'qc_submitted';
    S.audit('qc', id, 'submit', { asset: asset.tag, codes: codes.join('+'), seconds: rec.seconds, version: rec.version });
    dirty('qc', id); dirty('commercial', 'CM-' + id.slice(3)); dirty('asset', asset.id);
    S.persist();
    return rec;
  };

  /* ---------------- Reliance approval (BRD FR-011) ---------------- */
  S.decideQC = function (qcId, decision, reason) {
    var q = S.qcRecord(qcId); if (!q) throw new Error('QC record not found');
    var a = S.asset(q.asset_id);
    var me = S.me();
    q.status = decision;               // accepted | disputed | re_qc
    q.approver = me ? me.name : 'unknown';
    q.approved_at = new Date().toISOString();
    q.reason = reason || null;

    var cm = S.commercialFor(qcId);
    if (cm) { cm.qc_status = decision; cm.updated_at = q.approved_at; }

    if (decision === 'accepted') a.status = 'accepted';
    else if (decision === 'disputed') a.status = 'disputed';
    else if (decision === 're_qc') { a.status = 'pending_qc'; a.qc_id = null; }

    S.audit('qc', qcId, 'decision:' + decision, { asset: a.tag, reason: reason || '' });
    dirty('qc', qcId); dirty('asset', a.id);
    if (cm) dirty('commercial', cm.id);
    S.persist();
    return q;
  };

  /* ---------------- Commercial decision (BRD FR-014) ---------------- */
  S.decideCommercial = function (cmId, decision, note) {
    var cm = S.db.commercial.filter(function (c) { return c.id === cmId; })[0];
    if (!cm) throw new Error('Commercial record not found');
    cm.history.push({ from: cm.commercial_status, to: decision, note: note || '', at: new Date().toISOString(), by: (S.me() || {}).name });
    cm.commercial_status = decision;   // accepted | hold | disputed
    cm.updated_at = new Date().toISOString();
    S.audit('commercial', cmId, 'decision:' + decision, { note: note || '' });
    dirty('commercial', cmId);
    S.persist();
    return cm;
  };

  /* ---------------- Deduction master versions (BRD FR-012, BR-11) ---------------- */
  S.publishDeductionVersion = function (rates, rule, effectiveFrom, approvedBy, status) {
    var cur = S.activeDeduction();
    var v = {
      version: cur.version + 1,
      label: 'v' + (cur.version + 1) + ' — ' + (status === 'Approved' ? 'Reliance approved' : 'Draft'),
      effective_from: effectiveFrom,
      approved_by: approvedBy,
      approval_status: status,
      rule: rule,
      rates: rates,
      active: status === 'Approved',
      created_at: new Date().toISOString()
    };
    if (v.active) S.db.deductions.forEach(function (d) { d.active = false; });
    S.db.deductions.push(v);
    S.audit('deduction_master', 'v' + v.version, 'publish', { rule: rule, status: status, approved_by: approvedBy });
    dirty('deduction', v.version);
    /* Re-price only records not yet commercially accepted (historic QC keeps its version) */
    if (v.active) {
      S.db.commercial.forEach(function (cm) {
        if (cm.commercial_status === 'pending') {
          var q = S.qcRecord(cm.qc_id); if (!q) return;
          var p = S.computePrice(cm.base_price, q.codes);
          cm.deduction_pct = p.pct; cm.deduction_amount = p.deduction_amount;
          cm.revised_price = p.revised_price; cm.master_version = p.version;
          cm.updated_at = new Date().toISOString();
          dirty('commercial', cm.id);
        }
      });
    }
    S.persist();
    return v;
  };

  /* ===============================================================
     CHARGE RATE CARD & COSTING ENGINE (BRD v3 §21 costing fields)
     Planning / commercial inputs — distinct from the asset-condition
     deduction matrix in Sec 7.
     =============================================================== */
  S.activeRateCard = function () {
    if (!S.db.rate_cards || !S.db.rate_cards.length) {
      S.db.rate_cards = [JSON.parse(JSON.stringify(D.RATE_CARD))];
    }
    var act = S.db.rate_cards.filter(function (c) { return c.active; });
    return act[act.length - 1] || S.db.rate_cards[S.db.rate_cards.length - 1];
  };

  /* Shipment value = Σ RRP of the units standing at the site */
  S.shipmentValue = function (siteId) {
    return S.assetsAt(siteId).reduce(function (t, a) { return t + (a.rrp || a.base_price || 0); }, 0);
  };

  S.computeCharges = function (site, card) {
    card = card || S.activeRateCard();
    var r = card.rates;
    var units = S.assetsAt(site.id).length;
    var shipment = S.shipmentValue(site.id);

    var blocks = units ? Math.ceil(units / (r.qc_block_units || 20)) : 0;
    var qc = blocks * r.qc_block_rate;
    var packing = units * r.packing_per_unit;
    var weight = units * r.weight_per_unit;

    var pickup;
    if (!units) pickup = 0;
    else if (units >= r.pickup_per_unit_from) pickup = units * r.pickup_per_unit;
    else if (units <= r.pickup_single_max) pickup = r.pickup_single;
    else if (units <= r.pickup_cluster_max) pickup = r.pickup_cluster;
    else pickup = r.pickup_dedicated;

    var fov = site.fov_applicable === false ? 0 : round2(shipment * r.fov_pct / 100);
    var total = round2(qc + packing + pickup + fov);
    return {
      shipment_value: shipment,
      qc_charges: qc,
      packing_charges: packing,
      weight_kg: round2(weight),
      pickup_charges: round2(pickup),
      fov_charges: fov,
      total_charges: total,
      post_confirmation_total: round2(total + r.post_confirmation_addon),
      basis: 'rate-card',
      rate_version: card.version,
      qc_blocks: blocks,
      units: units
    };
  };
  function round2(n) { return Math.round((+n || 0) * 100) / 100; }

  /* Preview the effect of a rate card before anything is written */
  S.previewCharges = function (card, opts) {
    opts = opts || {};
    var rows = [], t = { oldTotal: 0, newTotal: 0, oldPost: 0, newPost: 0, changed: 0, skipped: 0 };
    S.db.sites.forEach(function (s) {
      var c = s.costing || {};
      if (!opts.includeOverrides && c.basis === 'override') { t.skipped++; return; }
      if (opts.siteIds && opts.siteIds.indexOf(s.id) === -1) return;
      var next = S.computeCharges(s, card);
      t.oldTotal += c.total_charges || 0; t.newTotal += next.total_charges;
      t.oldPost += c.post_confirmation_total || 0; t.newPost += next.post_confirmation_total;
      var delta = round2(next.total_charges - (c.total_charges || 0));
      if (delta !== 0) t.changed++;
      rows.push({ site: s, from: c, to: next, delta: delta });
    });
    t.oldTotal = round2(t.oldTotal); t.newTotal = round2(t.newTotal);
    t.oldPost = round2(t.oldPost); t.newPost = round2(t.newPost);
    t.delta = round2(t.newTotal - t.oldTotal);
    rows.sort(function (a, b) { return Math.abs(b.delta) - Math.abs(a.delta); });
    return { rows: rows, totals: t };
  };

  S.publishRateCard = function (rates, effectiveFrom, approvedBy, status, apply, opts) {
    var cur = S.activeRateCard();
    var card = {
      version: cur.version + 1,
      label: 'v' + (cur.version + 1) + ' — ' + (status === 'Approved' ? 'approved rate card' : 'draft'),
      effective_from: effectiveFrom,
      approved_by: approvedBy,
      approval_status: status,
      active: status === 'Approved',
      created_at: new Date().toISOString(),
      rates: rates
    };
    if (card.active) S.db.rate_cards.forEach(function (c) { c.active = false; });
    S.db.rate_cards.push(card);
    S.audit('rate_card', 'v' + card.version, 'publish', {
      status: status, approved_by: approvedBy, effective_from: effectiveFrom
    });
    dirty('rate_card', card.version);

    var applied = 0;
    if (apply && card.active) {
      var pre = S.previewCharges(card, opts || {});
      pre.rows.forEach(function (row) {
        row.site.costing = row.to;
        dirty('site', row.site.id);
        applied++;
      });
      S.audit('rate_card', 'v' + card.version, 'apply', {
        sites: applied, delta: pre.totals.delta, new_total: pre.totals.newTotal
      });
    }
    S.persist();
    return { card: card, applied: applied };
  };

  /* Manual per-site charge override */
  S.setSiteCharges = function (siteId, values, note) {
    var s = S.site(siteId);
    if (!s) throw new Error('Site not found');
    var before = JSON.parse(JSON.stringify(s.costing || {}));
    var c = s.costing || (s.costing = {});
    ['qc_charges', 'packing_charges', 'weight_kg', 'pickup_charges', 'fov_charges'].forEach(function (k) {
      if (values[k] !== undefined && values[k] !== '') c[k] = round2(values[k]);
    });
    if (values.shipment_value !== undefined && values.shipment_value !== '') {
      c.shipment_value = round2(values.shipment_value);
    }
    var card = S.activeRateCard();
    c.total_charges = round2((c.qc_charges || 0) + (c.packing_charges || 0) +
      (c.pickup_charges || 0) + (c.fov_charges || 0));
    c.post_confirmation_total = round2(c.total_charges + card.rates.post_confirmation_addon);
    c.basis = 'override';
    c.rate_version = card.version;
    S.audit('site', siteId, 'charges_override', {
      note: note || '', from_total: before.total_charges, to_total: c.total_charges
    });
    dirty('site', siteId);
    S.persist();
    return s;
  };

  S.resetSiteCharges = function (siteId) {
    var s = S.site(siteId);
    s.costing = S.computeCharges(s);
    S.audit('site', siteId, 'charges_recalculated', { total: s.costing.total_charges });
    dirty('site', siteId);
    S.persist();
    return s;
  };

  S.chargeTotals = function () {
    return S.db.sites.reduce(function (t, s) {
      var c = s.costing || {};
      t.shipment += c.shipment_value || 0;
      t.qc += c.qc_charges || 0;
      t.packing += c.packing_charges || 0;
      t.pickup += c.pickup_charges || 0;
      t.fov += c.fov_charges || 0;
      t.total += c.total_charges || 0;
      t.post += c.post_confirmation_total || 0;
      t.weight += c.weight_kg || 0;
      if (c.basis === 'override') t.overrides++;
      return t;
    }, { shipment: 0, qc: 0, packing: 0, pickup: 0, fov: 0, total: 0, post: 0, weight: 0, overrides: 0 });
  };

  /* ===============================================================
     BULK UPLOADS — sites / SPOC, charges, users
     (asset master and serials live in importAssets / importSerials)
     =============================================================== */
  function csvIndex(head, names) {
    for (var i = 0; i < names.length; i++) { var p = head.indexOf(names[i]); if (p > -1) return p; }
    return -1;
  }
  function csvHead(rows) {
    return rows[0].map(function (h) {
      return h.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
    });
  }
  S.matchSite = function (key) {
    if (!key) return null;
    var k = String(key).trim().toLowerCase();
    return S.db.sites.filter(function (s) {
      return s.site.toLowerCase() === k || s.id.toLowerCase() === k ||
        (s.code && String(s.code).toLowerCase() === k) ||
        (s.codes || []).some(function (c) { return String(c).toLowerCase() === k; });
    })[0] || null;
  };

  /* Site / SPOC / readiness details */
  S.importSiteDetails = function (text) {
    var rows = S.parseCSV(text);
    if (rows.length < 2) throw new Error('CSV appears empty.');
    var head = csvHead(rows);
    var col = {
      site: csvIndex(head, ['site', 'site_description', 'site_name', 'site_code', 'location']),
      spoc: csvIndex(head, ['spoc', 'spoc_name', 'contact']),
      phone: csvIndex(head, ['spoc_phone', 'phone', 'mobile', 'contact_number']),
      window: csvIndex(head, ['access_window', 'window']),
      readiness: csvIndex(head, ['readiness', 'status']),
      date: csvIndex(head, ['planned_date', 'visit_date', 'appointment']),
      partner: csvIndex(head, ['executed_by', 'partner', 'executing_partner']),
      tat: csvIndex(head, ['tat', 'tat_days']),
      blackout: csvIndex(head, ['blackout', 'blackout_dates']),
      notes: csvIndex(head, ['notes', 'remarks'])
    };
    if (col.site < 0) throw new Error('Required column "Site" not found.');
    var updated = 0, errors = [];
    for (var r = 1; r < rows.length; r++) {
      var row = rows[r];
      var get = function (c) { return c > -1 && row[c] !== undefined ? String(row[c]).trim() : ''; };
      var s = S.matchSite(get(col.site));
      if (!s) { errors.push('Row ' + (r + 1) + ': site "' + get(col.site) + '" not found'); continue; }
      if (get(col.spoc)) s.spoc = get(col.spoc);
      if (get(col.phone)) s.spoc_phone = get(col.phone);
      if (get(col.window)) s.access_window = get(col.window);
      if (get(col.readiness)) s.readiness = get(col.readiness);
      if (get(col.date)) s.planned_date = get(col.date);
      if (get(col.partner)) s.partner = get(col.partner);
      if (get(col.tat)) { s.tat = get(col.tat); s.tat_risk = /30-45|45/.test(s.tat); }
      if (get(col.blackout)) s.blackout = get(col.blackout);
      if (get(col.notes)) s.notes = get(col.notes);
      dirty('site', s.id);
      updated++;
    }
    S.audit('master', 'sites', 'import_details', { updated: updated, errors: errors.length });
    S.persist();
    return { updated: updated, errors: errors };
  };

  /* Site charges */
  S.importCharges = function (text) {
    var rows = S.parseCSV(text);
    if (rows.length < 2) throw new Error('CSV appears empty.');
    var head = csvHead(rows);
    var col = {
      site: csvIndex(head, ['site', 'site_description', 'site_name', 'site_code']),
      qc: csvIndex(head, ['qc_charges', 'qc_charge', 'qc']),
      pack: csvIndex(head, ['packing_charges', 'packing']),
      weight: csvIndex(head, ['weight', 'weight_kg']),
      pickup: csvIndex(head, ['pickup_charges', 'pickup']),
      fov: csvIndex(head, ['fov_charges', 'fov']),
      ship: csvIndex(head, ['value_of_shipment', 'shipment_value', 'shipment'])
    };
    if (col.site < 0) throw new Error('Required column "Site" not found.');
    var updated = 0, errors = [];
    for (var r = 1; r < rows.length; r++) {
      var row = rows[r];
      var get = function (c) { return c > -1 && row[c] !== undefined ? String(row[c]).trim() : ''; };
      var num = function (c) {
        var v = get(c).replace(/[₹,\s]/g, '');
        return v === '' ? undefined : (isNaN(parseFloat(v)) ? undefined : parseFloat(v));
      };
      var s = S.matchSite(get(col.site));
      if (!s) { errors.push('Row ' + (r + 1) + ': site "' + get(col.site) + '" not found'); continue; }
      S.setSiteCharges(s.id, {
        qc_charges: num(col.qc), packing_charges: num(col.pack), weight_kg: num(col.weight),
        pickup_charges: num(col.pickup), fov_charges: num(col.fov), shipment_value: num(col.ship)
      }, 'bulk upload');
      updated++;
    }
    S.audit('master', 'charges', 'import', { updated: updated, errors: errors.length });
    S.persist();
    return { updated: updated, errors: errors };
  };

  /* Users */
  S.importUsers = function (text) {
    var rows = S.parseCSV(text);
    if (rows.length < 2) throw new Error('CSV appears empty.');
    var head = csvHead(rows);
    var col = {
      name: csvIndex(head, ['name', 'full_name']),
      emp: csvIndex(head, ['employee_id', 'emp', 'login', 'user_id']),
      role: csvIndex(head, ['role']),
      region: csvIndex(head, ['region', 'zone']),
      sites: csvIndex(head, ['sites', 'assigned_sites']),
      status: csvIndex(head, ['status'])
    };
    if (col.name < 0 || col.emp < 0) throw new Error('Required columns "Name" and "Employee ID" not found.');
    var roleByLabel = {};
    Object.keys(D.ROLES).forEach(function (k) {
      roleByLabel[k] = k;
      roleByLabel[D.ROLES[k].label.toLowerCase()] = k;
    });
    var created = 0, updated = 0, errors = [];
    for (var r = 1; r < rows.length; r++) {
      var row = rows[r];
      var get = function (c) { return c > -1 && row[c] !== undefined ? String(row[c]).trim() : ''; };
      var emp = get(col.emp);
      if (!emp) { errors.push('Row ' + (r + 1) + ': missing employee ID'); continue; }
      var role = roleByLabel[get(col.role).toLowerCase()];
      if (!role) { errors.push('Row ' + (r + 1) + ': unknown role "' + get(col.role) + '"'); continue; }
      var siteIds = [];
      get(col.sites).split(/[;|]/).forEach(function (k) {
        k = k.trim(); if (!k) return;
        var s = S.matchSite(k);
        if (s) siteIds.push(s.id); else errors.push('Row ' + (r + 1) + ': site "' + k + '" not found');
      });
      var existing = S.db.users.filter(function (u) { return u.emp.toLowerCase() === emp.toLowerCase(); })[0];
      try {
        S.saveUser({
          id: existing ? existing.id : null,
          name: get(col.name), emp: emp, role: role,
          region: get(col.region) || 'All',
          status: (get(col.status) || 'active').toLowerCase() === 'inactive' ? 'inactive' : 'active',
          sites: siteIds.length ? siteIds : (existing ? existing.sites : []),
          allow: existing && existing.perms ? existing.perms.allow : [],
          deny: existing && existing.perms ? existing.perms.deny : []
        });
        if (existing) updated++; else created++;
      } catch (e) { errors.push('Row ' + (r + 1) + ': ' + e.message); }
    }
    S.audit('master', 'users', 'import', { created: created, updated: updated, errors: errors.length });
    S.persist();
    return { created: created, updated: updated, errors: errors };
  };

  /* ===============================================================
     DELETION — master data only; QC evidence is archived, never deleted
     (BRD NFR "no delete, soft-archive only")
     =============================================================== */
  S.assetDependencies = function (a) {
    var d = [];
    if (a.qc_id || S.qcForAsset(a.id).length) d.push('QC record');
    if (a.package_id) d.push('package');
    if (a.movement_id) d.push('dispatch');
    if (a.receipt_id) d.push('warehouse receipt');
    return d;
  };

  S.deleteAssets = function (ids, opts) {
    opts = opts || {};
    var removed = 0, blocked = [];
    ids.forEach(function (id) {
      var a = S.asset(id);
      if (!a) return;
      var dep = S.assetDependencies(a);
      if (dep.length && !opts.force) { blocked.push(a.tag + ' (' + dep.join(', ') + ')'); return; }
      if (dep.length && opts.force) {
        S.db.qc = S.db.qc.filter(function (q) { return q.asset_id !== id; });
        S.db.commercial = S.db.commercial.filter(function (c) { return c.asset_id !== id; });
        S.db.packages.forEach(function (p) {
          p.assets = p.assets.filter(function (x) { return x !== id; });
        });
        S.db.movements.forEach(function (m) {
          m.assets = m.assets.filter(function (x) { return x !== id; });
        });
      }
      S.db.assets = S.db.assets.filter(function (x) { return x.id !== id; });
      removed++;
    });
    S.audit('asset', 'bulk', 'delete', { removed: removed, blocked: blocked.length, forced: !!opts.force });
    S.persist();
    return { removed: removed, blocked: blocked };
  };

  S.deleteSite = function (siteId, opts) {
    opts = opts || {};
    var s = S.site(siteId);
    if (!s) throw new Error('Site not found');
    var assets = S.assetsAt(siteId);
    var withWork = assets.filter(function (a) { return S.assetDependencies(a).length; });
    if (withWork.length && !opts.force) {
      throw new Error(s.site + ' has ' + withWork.length + ' unit(s) with QC or movement history. ' +
        'Tick "delete recorded work as well" to remove them.');
    }
    var res = S.deleteAssets(assets.map(function (a) { return a.id; }), { force: !!opts.force });
    S.db.packages = S.db.packages.filter(function (p) { return p.site_id !== siteId; });
    S.db.movements = S.db.movements.filter(function (m) { return m.site_id !== siteId; });
    S.db.receipts = S.db.receipts.filter(function (r) { return r.site_id !== siteId; });
    S.db.sites = S.db.sites.filter(function (x) { return x.id !== siteId; });
    S.db.users.forEach(function (u) {
      u.sites = (u.sites || []).filter(function (x) { return x !== siteId; });
    });
    S.audit('site', siteId, 'delete', { site: s.site, assets: res.removed, forced: !!opts.force });
    S.persist();
    return { site: s, assets: res.removed };
  };

  /* QC evidence is archived rather than deleted */
  S.archiveQC = function (qcId, reason) {
    var q = S.qcRecord(qcId);
    if (!q) throw new Error('QC record not found');
    if (q.archived) throw new Error('Already archived.');
    q.archived = true;
    q.archived_at = new Date().toISOString();
    q.archived_by = (S.me() || {}).name;
    q.archive_reason = reason || '';
    var a = S.asset(q.asset_id);
    if (a && a.qc_id === qcId) {
      a.qc_id = null;
      if (['qc_submitted', 'accepted', 'disputed'].indexOf(a.status) > -1) a.status = 'pending_qc';
    }
    var cm = S.commercialFor(qcId);
    if (cm) cm.commercial_status = 'archived';
    S.audit('qc', qcId, 'archive', { reason: reason || '', asset: a ? a.tag : '' });
    dirty('qc', qcId);
    if (a) dirty('asset', a.id);
    if (cm) dirty('commercial', cm.id);
    S.persist();
    return q;
  };

  /* Clear transactional records but keep the inventory master */
  S.purgeTransactions = function () {
    var counts = {
      qc: S.db.qc.length, packages: S.db.packages.length,
      movements: S.db.movements.length, receipts: S.db.receipts.length
    };
    S.db.qc = []; S.db.commercial = []; S.db.packages = [];
    S.db.movements = []; S.db.receipts = [];
    S.db.counters = { qc: 0, pkg: 0, mov: 0, rcpt: 0, grn: 0 };
    S.db.assets.forEach(function (a) {
      a.status = 'pending_qc';
      a.qc_id = null; a.package_id = null; a.movement_id = null; a.receipt_id = null;
    });
    S.audit('master', 'transactions', 'purge', counts);
    S.persist();
    return counts;
  };

  S.clearSerials = function () {
    var n = 0;
    S.db.assets.forEach(function (a) {
      if (S.hasSerial(a)) {
        a.serial = 'PEND-' + a.id.replace(/^A/, '');
        delete a.serial_captured_at; delete a.serial_captured_by;
        n++;
      }
    });
    S.audit('master', 'serials', 'clear', { cleared: n });
    S.persist();
    return n;
  };

  /* ---------------- Packing (BRD FR-015, BR-01) ---------------- */
  S.createPackage = function (siteId, assetIds, type, seal, accessories, photo) {
    var bad = assetIds.filter(function (id) { var a = S.asset(id); return !a || a.status !== 'accepted'; });
    if (bad.length) throw new Error('BR-01: only Reliance-accepted assets can be packed (' + bad.length + ' invalid).');
    var id = nextId('pkg', 'PKG-', 5);
    var p = {
      id: id, site_id: siteId, type: type, seal: seal,
      assets: assetIds.slice(), accessories: accessories || '',
      photo: photo || null,
      packed_by: (S.me() || {}).name || 'unknown',
      packed_at: new Date().toISOString(),
      status: 'sealed', movement_id: null
    };
    S.db.packages.push(p);
    assetIds.forEach(function (aid) {
      var a = S.asset(aid); a.status = 'packed'; a.package_id = id; dirty('asset', aid);
    });
    dirty('package', id);
    S.audit('package', id, 'seal', { site: siteId, count: assetIds.length, seal: seal, type: type });
    S.persist();
    return p;
  };

  /* ---------------- Dispatch: pickup or courier (FR-017 / FR-018, BR-08) ---------------- */
  S.createMovement = function (data) {
    var pkgs = data.packages.map(S.pkg).filter(Boolean);
    if (!pkgs.length) throw new Error('Select at least one sealed package.');
    var already = pkgs.filter(function (p) { return p.movement_id; });
    if (already.length) throw new Error('BR-08: package ' + already[0].id + ' is already dispatched.');
    var assetIds = [];
    pkgs.forEach(function (p) { assetIds = assetIds.concat(p.assets); });

    var id = nextId('mov', data.mode === 'courier' ? 'AWB-' : 'PU-', 5);
    var m = {
      id: id, mode: data.mode, site_id: data.site_id,
      packages: data.packages.slice(), assets: assetIds,
      vehicle: data.vehicle || '', driver: data.driver || '', driver_phone: data.driver_phone || '',
      partner: data.partner || '', gate_pass: data.gate_pass || '',
      courier_name: data.courier_name || '', awb: data.awb || '',
      weight: data.weight || '', destination: data.destination || 'WH-Mumbai-01',
      eta: data.eta || '', handover_proof: data.handover_proof || null,
      status: 'in_transit', pod: null, rto: false, exception: '',
      created_by: (S.me() || {}).name, created_at: new Date().toISOString(),
      events: [{ at: new Date().toISOString(), label: 'Picked up from site', by: (S.me() || {}).name }]
    };
    S.db.movements.push(m);
    pkgs.forEach(function (p) { p.movement_id = id; p.status = 'dispatched'; dirty('package', p.id); });
    assetIds.forEach(function (aid) {
      var a = S.asset(aid); a.status = 'dispatched'; a.movement_id = id; dirty('asset', aid);
    });
    dirty('movement', id);
    S.audit('movement', id, 'dispatch:' + data.mode, { site: data.site_id, assets: assetIds.length, awb: data.awb || '', vehicle: data.vehicle || '' });
    S.persist();
    return m;
  };

  S.updateMovement = function (id, patch, eventLabel) {
    var m = S.movement(id); if (!m) throw new Error('Movement not found');
    Object.keys(patch).forEach(function (k) { m[k] = patch[k]; });
    if (eventLabel) m.events.push({ at: new Date().toISOString(), label: eventLabel, by: (S.me() || {}).name });
    S.audit('movement', id, 'update', patch);
    dirty('movement', id);
    S.persist();
    return m;
  };

  /* ---------------- Warehouse receipt (FR-019, BR-09) ---------------- */
  S.receive = function (data) {
    var m = S.movement(data.movement_id); if (!m) throw new Error('Movement not found');
    var expected = m.assets.length;
    var received = +data.received_count;
    var id = nextId('rcpt', 'RC-', 5);
    var grn = 'GRN-' + new Date().getFullYear() + '-' + S.deviceCode() + '-' +
              (1000 + (S.db.counters.grn = (S.db.counters.grn || 0) + 1));
    var variance = received - expected;
    var r = {
      id: id, grn: grn, movement_id: m.id, site_id: m.site_id,
      expected_count: expected, received_count: received, variance: variance,
      seal_status: data.seal_status, seal_no: data.seal_no || '',
      damage: data.damage, damage_note: data.damage_note || '',
      discrepancy: variance !== 0 || data.seal_status !== 'Intact' || data.damage === 'Yes',
      discrepancy_owner: data.discrepancy_owner || '',
      discrepancy_status: 'open',
      received_by: (S.me() || {}).name, received_at: new Date().toISOString(),
      photo: data.photo || null
    };
    if (!r.discrepancy) r.discrepancy_status = 'none';
    S.db.receipts.push(r);
    m.status = 'delivered'; m.pod = r.received_at;
    m.events.push({ at: r.received_at, label: 'Warehouse receipt · ' + grn, by: r.received_by });
    m.assets.forEach(function (aid) {
      var a = S.asset(aid); if (!a) return;
      a.receipt_id = id;
      a.status = r.discrepancy ? 'received_discrepancy' : 'received';
      dirty('asset', aid);
    });
    dirty('receipt', id); dirty('movement', m.id);
    S.audit('receipt', id, 'grn', { grn: grn, expected: expected, received: received, variance: variance, seal: data.seal_status });
    S.persist();
    return r;
  };

  S.resolveDiscrepancy = function (receiptId, note) {
    var r = S.db.receipts.filter(function (x) { return x.id === receiptId; })[0];
    if (!r) throw new Error('Receipt not found');
    r.discrepancy_status = 'resolved';
    r.resolution = note; r.resolved_at = new Date().toISOString();
    r.resolved_by = (S.me() || {}).name;
    S.audit('receipt', receiptId, 'discrepancy:resolved', { note: note });
    dirty('receipt', receiptId);
    S.persist();
    return r;
  };

  /* BR-09 / BR-12 asset closure */
  S.closeAsset = function (assetId) {
    var a = S.asset(assetId);
    var chk = S.closureCheck(a);
    if (!chk.ok) throw new Error(chk.blockers.join(' '));
    a.status = 'closed';
    S.audit('asset', assetId, 'close', { tag: a.tag });
    dirty('asset', assetId);
    S.persist();
    return a;
  };
  S.closureCheck = function (a) {
    var blockers = [];
    var q = a.qc_id ? S.qcRecord(a.qc_id) : null;
    if (!q || q.status !== 'accepted') blockers.push('BR-12: QC acceptance missing.');
    if (!a.package_id) blockers.push('BR-12: packing record missing.');
    if (!a.movement_id) blockers.push('BR-12: dispatch / AWB record missing.');
    if (!a.receipt_id) blockers.push('BR-12: warehouse receipt missing.');
    else {
      var r = S.db.receipts.filter(function (x) { return x.id === a.receipt_id; })[0];
      if (r && r.discrepancy && r.discrepancy_status === 'open') blockers.push('BR-09: warehouse discrepancy open.');
    }
    return { ok: blockers.length === 0, blockers: blockers };
  };

  /* ---------------- SLA ageing & notifications (BRD Sec 15, FR-022) ---------------- */
  S.hoursSince = function (iso) {
    if (!iso) return 0;
    return (Date.now() - new Date(iso).getTime()) / 36e5;
  };
  S.liveQC = function () { return S.db.qc.filter(function (q) { return !q.archived; }); };

  S.notifications = function () {
    var cfg = S.db.config.sla, out = [];

    S.liveQC().filter(function (q) { return q.status === 'pending'; }).forEach(function (q) {
      var age = S.hoursSince(q.submitted_at);
      if (age > cfg.qc_approval_h) {
        var a = S.asset(q.asset_id);
        out.push(mk('sla-qc-' + q.id, 'red', '🚨 Approval overdue — ' + (a ? a.tag : q.asset_id),
          'QC submitted ' + fmtAge(age) + ' ago. Reliance SLA ≤1 business day. Escalation L1: Regional Coordinator → Reliance SPOC.',
          q.submitted_at, '#/approvals'));
      }
    });

    S.liveQC().filter(function (q) { return q.status === 'disputed'; }).forEach(function (q) {
      var age = S.hoursSince(q.approved_at);
      if (age > cfg.dispute_h) {
        var a = S.asset(q.asset_id);
        out.push(mk('sla-disp-' + q.id, 'amber', '⚠️ Disputed QC pending disposition — ' + (a ? a.tag : ''),
          'Disputed ' + fmtAge(age) + ' ago. Escalation L1: PMO → Reliance QC Approver.', q.approved_at, '#/approvals'));
      }
    });

    S.liveQC().filter(function (q) { return q.status === 'accepted'; }).forEach(function (q) {
      var a = S.asset(q.asset_id); if (!a || a.status !== 'accepted') return;
      var age = S.hoursSince(q.approved_at);
      if (age > cfg.pickup_release_breach_h) {
        out.push(mk('sla-pick-' + q.id, 'amber', '📦 Pickup release pending — ' + a.tag,
          'Accepted ' + fmtAge(age) + ' ago, not yet packed. Target ≤4 business hours.', q.approved_at, '#/packing'));
      }
    });

    S.db.movements.filter(function (m) { return m.status === 'in_transit'; }).forEach(function (m) {
      var age = S.hoursSince(m.created_at);
      if (age > cfg.wh_total_breach_h) {
        out.push(mk('sla-trans-' + m.id, 'red', '🚚 Transit exception — ' + m.id,
          'Dispatched ' + fmtAge(age) + ' ago; warehouse receipt pending (>72 h). Logistics Controller to check vehicle/AWB.',
          m.created_at, '#/' + (m.mode === 'courier' ? 'courier' : 'pickup')));
      }
    });

    S.db.receipts.filter(function (r) { return r.discrepancy && r.discrepancy_status === 'open'; }).forEach(function (r) {
      out.push(mk('sla-disc-' + r.id, 'red', '🏷️ Warehouse discrepancy — ' + r.grn,
        'Expected ' + r.expected_count + ' / received ' + r.received_count + ' · seal ' + r.seal_status + '. Closure locked until resolved (BR-09).',
        r.received_at, '#/warehouse'));
    });

    /* Site readiness — individually for a short list, aggregated at scale */
    var notReady = S.db.sites.filter(function (s) { return s.readiness === 'Pending'; });
    if (notReady.length > 5) {
      out.push(mk('site-ready-all', 'amber', '📍 Site readiness pending — ' + notReady.length + ' locations',
        'Access window, SPOC and readiness not yet confirmed (Day 0 checklist items 3 & 9). ' +
        'Coordinators to confirm before the visit plan locks.', null, '#/sites'));
    } else {
      notReady.forEach(function (s) {
        out.push(mk('site-ready-' + s.id, 'amber', '📍 Site readiness pending — ' + s.site,
          'SPOC ' + (s.spoc || 'not nominated') + ' has not confirmed readiness. Coordinator to follow up.',
          null, '#/site/' + s.id));
      });
    }

    /* Milestone alert */
    var st = S.stats();
    var mNext = S.nextMilestone();
    if (mNext && st.pct_closed < mNext.pct) {
      out.push(mk('milestone', 'amber', '⚠️ Milestone alert — ' + mNext.label,
        'Current closure ' + st.pct_closed.toFixed(1) + '% of ' + st.total + ' assets. Gap ' +
        Math.max(0, Math.ceil(st.total * mNext.pct / 100 - st.closed)) + ' units.', null, '#/dashboard'));
    }

    /* Deduction master not approved */
    var dm = S.activeDeduction();
    if (dm.approval_status !== 'Approved') {
      out.push(mk('ded-master', 'blue', '💰 Deduction matrix not approved',
        'Active master ' + dm.label + ' — all deduction % remain 0 until written Reliance approval (BRD Sec 7).', null, '#/admin'));
    }

    var read = S.db.notifications_read || [];
    out.forEach(function (n) { n.read = read.indexOf(n.id) > -1; });
    return out.sort(function (a, b) {
      var w = { red: 0, amber: 1, blue: 2, green: 3 };
      return (w[a.level] - w[b.level]) || 0;
    });
  };
  function mk(id, level, title, body, ts, link) {
    return { id: id, level: level, title: title, body: body, ts: ts, link: link };
  }
  function fmtAge(h) {
    if (h < 1) return Math.round(h * 60) + ' min';
    if (h < 48) return Math.round(h) + ' hrs';
    return Math.round(h / 24) + ' days';
  }
  S.fmtAge = fmtAge;
  S.markAllRead = function () {
    S.db.notifications_read = S.notifications().map(function (n) { return n.id; });
    S.persist();
  };

  /* ---------------- Stats / dashboard aggregation (FR-020) ---------------- */
  var CLOSED_STATES = ['received', 'received_discrepancy', 'closed'];
  S.stats = function (scopeSiteIds) {
    var assets = S.db.assets;
    if (scopeSiteIds && scopeSiteIds.length) {
      assets = assets.filter(function (a) { return scopeSiteIds.indexOf(a.site_id) > -1; });
    }
    var s = {
      total: assets.length, pending_qc: 0, qc_done: 0, accepted: 0, disputed: 0,
      packed: 0, dispatched: 0, received: 0, closed: 0, discrepancy: 0
    };
    assets.forEach(function (a) {
      if (a.status === 'pending_qc') s.pending_qc++;
      if (a.status !== 'pending_qc') s.qc_done++;
      if (['accepted', 'packed', 'dispatched', 'received', 'received_discrepancy', 'closed'].indexOf(a.status) > -1) s.accepted++;
      if (a.status === 'disputed') s.disputed++;
      if (['packed', 'dispatched', 'received', 'received_discrepancy', 'closed'].indexOf(a.status) > -1) s.packed++;
      if (['dispatched', 'received', 'received_discrepancy', 'closed'].indexOf(a.status) > -1) s.dispatched++;
      if (CLOSED_STATES.indexOf(a.status) > -1) s.received++;
      if (a.status === 'closed') s.closed++;
      if (a.status === 'received_discrepancy') s.discrepancy++;
    });
    s.pct_qc = s.total ? s.qc_done / s.total * 100 : 0;
    s.pct_accepted = s.total ? s.accepted / s.total * 100 : 0;
    s.pct_dispatched = s.total ? s.dispatched / s.total * 100 : 0;
    s.pct_received = s.total ? s.received / s.total * 100 : 0;
    /* "Closed" for milestone purposes = chain complete at warehouse */
    s.pct_closed = s.pct_received;
    return s;
  };

  S.projectDay = function () {
    var start = new Date(S.db.project.start_date).getTime();
    var d = Math.floor((Date.now() - start) / 864e5) + 1;
    return Math.max(1, Math.min(d, 999));
  };
  S.nextMilestone = function () {
    var day = S.projectDay(), ms = S.db.project.milestones;
    for (var i = 0; i < ms.length; i++) if (day <= ms[i].day) return ms[i];
    return ms[ms.length - 1];
  };
  S.milestoneRag = function (m) {
    var st = S.stats(), day = S.projectDay();
    if (st.pct_closed >= m.pct) return 'green';
    if (day > m.day) return 'red';
    var expected = m.pct * Math.min(1, day / m.day);
    return st.pct_closed >= expected * 0.9 ? 'green' : (st.pct_closed >= expected * 0.7 ? 'amber' : 'red');
  };

  S.todayQC = function () {
    var today = new Date().toISOString().slice(0, 10);
    return S.liveQC().filter(function (q) { return q.submitted_at.slice(0, 10) === today; });
  };

  S.pendingSync = function () { return S.liveQC().filter(function (q) { return !q.synced; }); };
  S.syncNow = function () {
    var n = 0;
    S.db.qc.forEach(function (q) { if (!q.synced) { q.synced = true; n++; } });
    if (n) S.audit('sync', 'batch', 'sync', { records: n });
    S.persist();
    return n;
  };

  /* ---------------- CSV import / export ---------------- */
  S.parseCSV = function (text) {
    var rows = [], row = [], cur = '', q = false;
    for (var i = 0; i < text.length; i++) {
      var c = text[i];
      if (q) {
        if (c === '"' && text[i + 1] === '"') { cur += '"'; i++; }
        else if (c === '"') q = false;
        else cur += c;
      } else {
        if (c === '"') q = true;
        else if (c === ',') { row.push(cur); cur = ''; }
        else if (c === '\n') { row.push(cur); rows.push(row); row = []; cur = ''; }
        else if (c !== '\r') cur += c;
      }
    }
    if (cur.length || row.length) { row.push(cur); rows.push(row); }
    return rows.filter(function (r) { return r.some(function (x) { return String(x).trim() !== ''; }); });
  };

  S.toCSV = function (headers, rows) {
    var esc = function (v) {
      v = v === null || v === undefined ? '' : String(v);
      return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
    };
    return headers.join(',') + '\n' + rows.map(function (r) { return r.map(esc).join(','); }).join('\n');
  };

  /* Master import — BRD FR-003 / v3 inventory columns */
  S.importAssets = function (text, replace) {
    var rows = S.parseCSV(text);
    if (rows.length < 2) throw new Error('CSV appears empty.');
    var head = rows[0].map(function (h) { return h.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, ''); });
    var idx = function (names) {
      for (var i = 0; i < names.length; i++) { var p = head.indexOf(names[i]); if (p > -1) return p; }
      return -1;
    };
    var col = {
      state: idx(['state']), city: idx(['city']), site: idx(['site', 'site_name']),
      site_desc: idx(['site_description', 'site_desc']),
      family: idx(['mh_family', 'family']), cls: idx(['mh_class', 'class']), brick: idx(['mh_brick', 'brick']),
      article: idx(['article']), article_desc: idx(['article_description', 'article_desc']),
      sl: idx(['storage_location']), inv: idx(['inventory_type']),
      qty: idx(['stock_quantity', 'quantity', 'qty']),
      rrp: idx(['rrp']), mrp: idx(['mrp']),
      serial: idx(['serial', 'serial_no', 'serial_number']), tag: idx(['asset_tag', 'tag'])
    };
    if (col.site < 0) throw new Error('Required column "Site" not found. Header row must include Site.');

    var errors = [], created = 0, sitesAdded = 0;
    if (replace) {
      S.db.assets = []; S.db.sites = []; S.db.qc = []; S.db.commercial = [];
      S.db.packages = []; S.db.movements = []; S.db.receipts = [];
      S.db.counters = { qc: 0, pkg: 0, mov: 0, rcpt: 0, grn: 0 };
    }
    var siteIndex = {};
    S.db.sites.forEach(function (s) { siteIndex[s.site.toLowerCase()] = s; });
    var seq = S.db.assets.length;

    for (var r = 1; r < rows.length; r++) {
      var row = rows[r];
      var get = function (c) { return c > -1 && row[c] !== undefined ? String(row[c]).trim() : ''; };
      var siteName = get(col.site);
      if (!siteName) { errors.push('Row ' + (r + 1) + ': missing Site'); continue; }
      var site = siteIndex[siteName.toLowerCase()];
      if (!site) {
        var sid = 'S' + String(S.db.sites.length + 1).padStart(2, '0');
        site = {
          id: sid, state: get(col.state) || '—', city: get(col.city) || '—',
          site: siteName, site_desc: get(col.site_desc) || siteName,
          spoc: '', spoc_phone: '', partner: 'Deshwal',
          region: regionOf(get(col.state)),
          address: [get(col.site_desc), get(col.city), get(col.state)].filter(Boolean).join(', '),
          access_window: '10:00 – 18:00', blackout: '', readiness: 'Pending',
          planned_date: '', planned_qty: 0, status: 'Scheduled',
          tat: '', tat_after: '', tat_risk: false, code: sid,
          costing: { shipment_value: 0, qc_charges: 0, packing_charges: 0, weight_kg: 0,
                     pickup_charges: 0, fov_charges: 0, total_charges: 0, post_confirmation_total: 0 },
          notes: ''
        };
        S.db.sites.push(site); siteIndex[siteName.toLowerCase()] = site; sitesAdded++;
      }
      var qty = Math.max(1, parseInt(get(col.qty) || '1', 10) || 1);
      var desc = get(col.article_desc) || get(col.brick) || 'Asset';
      var cat = categoryOf(desc + ' ' + get(col.cls) + ' ' + get(col.brick));
      var rrp = parseFloat((get(col.rrp) || '0').replace(/[^0-9.]/g, '')) || 0;
      var mrp = parseFloat((get(col.mrp) || '0').replace(/[^0-9.]/g, '')) || 0;

      for (var k = 0; k < qty; k++) {
        seq++;
        S.db.assets.push({
          id: 'A' + String(seq).padStart(5, '0'),
          tag: get(col.tag) && qty === 1 ? get(col.tag) : ('REL-' + site.id + '-' + String(seq).padStart(4, '0')),
          serial: get(col.serial) && qty === 1 ? get(col.serial) : ('PEND-' + String(seq).padStart(5, '0')),
          category: cat,
          make: (desc.split(' ')[0] || 'NA'), model: desc, year: '',
          site_id: site.id,
          storage_location: get(col.sl), inventory_type: get(col.inv) || 'Demo Unit',
          mh_family: get(col.family), mh_class: get(col.cls), mh_brick: get(col.brick),
          article: get(col.article), article_desc: desc, stock_qty: 1,
          rrp: rrp, mrp: mrp, base_price: rrp || mrp,
          status: 'pending_qc', qc_id: null, package_id: null, movement_id: null, receipt_id: null
        });
        created++;
      }
      site.planned_qty = S.assetsAt(site.id).length;
    }
    S.audit('master', 'assets', 'import', { created: created, sites_added: sitesAdded, replaced: !!replace });
    S.persist();
    return { created: created, sitesAdded: sitesAdded, errors: errors };
  };

  function regionOf(state) {
    var m = {
      'Maharashtra': 'West', 'Gujarat': 'West', 'Goa': 'West', 'Rajasthan': 'North',
      'Delhi': 'North', 'Haryana': 'North', 'Punjab': 'North', 'Uttar Pradesh': 'North',
      'Karnataka': 'South', 'Tamil Nadu': 'South', 'Telangana': 'South', 'Kerala': 'South', 'Andhra Pradesh': 'South',
      'West Bengal': 'East', 'Odisha': 'East', 'Bihar': 'East', 'Assam': 'East', 'Jharkhand': 'East'
    };
    return m[state] || 'Other';
  }
  function categoryOf(text) {
    var t = (text || '').toLowerCase();
    if (/tft|monitor|display|screen|led/.test(t)) return 'tft';
    if (/desktop|cpu|tower|all.?in.?one|aio|pc\b/.test(t)) return 'desktop';
    return 'laptop';
  }
  S.categoryOf = categoryOf;

})(window.RA = window.RA || {});
